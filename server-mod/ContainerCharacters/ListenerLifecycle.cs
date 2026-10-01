using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Threading;
using MonoMod.RuntimeDetour;
using Terraria;
using Terraria.ModLoader;
using Terraria.Net.Sockets;

namespace ContainerCharacters;

// Each accept loop owns its listener. An old loop must never stop a new socket.
public class ListenerLifecycle : ModSystem
{
    private readonly object gate = new();
    private readonly Dictionary<TcpSocket, TcpListener> listeners = new();
    private Hook startHook;
    private Hook stopHook;
    private delegate bool StartOriginal(TcpSocket socket, SocketConnectionAccepted callback);
    private delegate void StopOriginal(TcpSocket socket);

    public override void Load()
    {
        if (!Main.dedServ) return;
        var map = typeof(TcpSocket).GetInterfaceMap(typeof(ISocket));
        MethodInfo start = null, stop = null;
        for (int i = 0; i < map.InterfaceMethods.Length; i++) {
            if (map.InterfaceMethods[i].Name == nameof(ISocket.StartListening)) start = map.TargetMethods[i];
            if (map.InterfaceMethods[i].Name == nameof(ISocket.StopListening)) stop = map.TargetMethods[i];
        }
        if (start == null || stop == null) throw new InvalidOperationException("TCP listener interface changed.");
        startHook = new Hook(start, (Func<StartOriginal, TcpSocket, SocketConnectionAccepted, bool>)Start);
        stopHook = new Hook(stop, (Action<StopOriginal, TcpSocket>)Stop);
        Mod.Logger.Info("Container TCP listener lifecycle enabled.");
    }

    private bool Start(StartOriginal original, TcpSocket socket, SocketConnectionAccepted callback)
    {
        lock (gate) {
            if (listeners.ContainsKey(socket)) return true;
            var address = IPAddress.Any;
            if (Program.LaunchParameters.TryGetValue("-ip", out var value) &&
                !IPAddress.TryParse(value, out address)) address = IPAddress.Any;
            var listener = new TcpListener(address, Netplay.ListenPort);
            try {
                listener.Start();
                listeners.Add(socket, listener);
                new Thread(() => Accept(socket, listener, callback)) {
                    IsBackground = true, Name = "Container TCP Listen Thread"
                }.Start();
                return true;
            }
            catch (Exception error) {
                listeners.Remove(socket);
                listener.Stop();
                Mod.Logger.Warn("TCP listener could not start: " + error.Message);
                return false;
            }
        }
    }

    private void Stop(StopOriginal original, TcpSocket socket)
    {
        lock (gate) {
            if (listeners.Remove(socket, out var listener)) listener.Stop();
        }
    }

    private void Accept(TcpSocket socket, TcpListener listener, SocketConnectionAccepted callback)
    {
        try {
            while (!Netplay.Disconnect) {
                lock (gate) {
                    if (!listeners.TryGetValue(socket, out var current) || current != listener) break;
                    // Stop and accept share the gate. Pending avoids holding it
                    // during a blocking accept, including shutdown and slot exhaustion.
                    if (listener.Pending()) {
                        var client = listener.AcceptTcpClient();
                        // Preserve Terraria's admission, authentication and packet handling.
                        try { callback(new TcpSocket(client)); }
                        catch (Exception error) {
                            client.Close();
                            Mod.Logger.Warn("TCP connection callback failed: " + error.Message);
                        }
                    }
                }
                Thread.Sleep(10);
            }
        }
        catch (Exception error) {
            Mod.Logger.Warn("TCP accept loop stopped; listening will be retried: " + error.Message);
        }
        finally {
            lock (gate) {
                listener.Stop();
                if (listeners.TryGetValue(socket, out var current) && current == listener) {
                    listeners.Remove(socket);
                    if (!Netplay.Disconnect) Netplay.IsListening = false;
                }
            }
        }
    }

    public override void Unload()
    {
        lock (gate) {
            foreach (var listener in listeners.Values) listener.Stop();
            listeners.Clear();
        }
        stopHook?.Dispose();
        startHook?.Dispose();
    }
}
