using System;
using System.Text.Json;
using Terraria;
using Terraria.ModLoader;

namespace ContainerCharacters;

public class ContainerCharacters : Mod { }

// Server-only: no client mod or graphics device is required.
public class CharacterTracking : ModSystem
{
    private readonly string[] sessions = new string[256];
    private static void Emit(object value) => Console.WriteLine("[CHARACTER] " + JsonSerializer.Serialize(new {
        key = Environment.GetEnvironmentVariable("TMOD_CHARACTER_EVENT_KEY"), data = value
    }));

    public override void OnWorldLoad()
    {
        Array.Clear(sessions);
        Emit(new { action = "ready" });
    }

    public override void PostUpdateEverything()
    {
        if (Main.netMode != 2) return;
        for (int slot = 0; slot < 255; slot++) {
            var player = Main.player[slot];
            var client = Netplay.Clients[slot];
            bool connected = player.active && client.IsAnnouncementCompleted && client.Socket?.IsConnected() == true;
            if (!connected) {
                if (sessions[slot] != null) Emit(new { action = "left", slot, session = sessions[slot] });
                sessions[slot] = null;
                continue;
            }
            if (sessions[slot] != null) continue;
            sessions[slot] = Guid.NewGuid().ToString("N");
            var remote = client.Socket?.GetRemoteAddress();
            Emit(new { action = "joined", slot, session = sessions[slot],
                name = player.name, address = remote?.ToString() ?? "" });
        }
    }
}
