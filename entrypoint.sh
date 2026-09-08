#!/bin/bash

pipe="/tmp/tmod.pipe"
generatedConfigPath="/terraria-server/serverconfig.txt"
customConfigPath="/terraria-server/customconfig.txt"
configPath="$generatedConfigPath"

echo -e "[SYSTEM] Shutdown Message set to: $TMOD_SHUTDOWN_MESSAGE"
echo -e "[SYSTEM] Save Interval set to: $TMOD_AUTOSAVE_INTERVAL minutes"

# Check Config
if [[ "$TMOD_USECONFIGFILE" == "Yes" ]]; then
    if [ -f "$customConfigPath" ]; then
        configPath="$customConfigPath"
        echo -e "[!!] The tModLoader server was set to load with a config file. It will be used instead of the environment variables."
    else
        echo -e "[!!] FATAL: The tModLoader server was set to launch with a config file, but $customConfigPath was not found."
        sleep 5s
        exit 1
    fi
else
  ./prepare-config.sh
fi

# Trapped Shutdown, to cleanly shutdown
function shutdown () {
  trap - TERM INT
  inject "say $TMOD_SHUTDOWN_MESSAGE" || true
  sleep 3s
  inject "exit" || true

  while tmux has-session -t tmodloader 2>/dev/null; do
    sleep 0.5
  done

  rm -f "$pipe"
  exit 0
}

# Download missing/outdated Workshop items and enable the requested mods.
./manage-mods.sh

# Startup command
server="/terraria-server/LaunchUtils/ScriptCaller.sh -server -tmlsavedirectory \"/data/tModLoader\" -steamworkshopfolder \"/data/steamMods/steamapps/workshop\" -config \"$configPath\""

# Trap the shutdown
trap shutdown TERM INT
echo -e "tModLoader is launching with the following command:"
echo "$server"

# Check if the pipe exists already and remove it.
if [ -e "$pipe" ]; then
  rm -f "$pipe"
fi

# Create the tmux and pipe, so we can inject commands from 'docker exec [container id] inject [command]' on the host
sleep 5s
mkfifo "$pipe"
tmux new-session -d -s tmodloader "$server | tee \"$pipe\""

# Call the autosaver
/terraria-server/autosave.sh &

# Infinitely print the contents of the pipe, so the container still logs the Terraria Server.
cat "$pipe" &
wait "$!"
