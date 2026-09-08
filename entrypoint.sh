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

# Download Mods
if test -z "${TMOD_AUTODOWNLOAD}" ; then
    echo -e "[SYSTEM] No mods to download. If you wish to download mods at runtime, please set the TMOD_AUTODOWNLOAD environment variable equal to a comma separated list of Mod Workshop IDs."
    echo -e "[SYSTEM] For more information, please see the Github README."
    sleep 5s
else
    echo -e "[SYSTEM] Downloading mods specified in TMOD_AUTODOWNLOAD. This may take a while depending on the number of mods..."

    if ! [[ "$TMOD_DOWNLOAD_RETRIES" =~ ^[1-9][0-9]*$ ]]; then
        echo -e "[!!] TMOD_DOWNLOAD_RETRIES must be a positive integer."
        exit 1
    fi
    if ! [[ "$TMOD_DOWNLOAD_RETRY_DELAY" =~ ^[0-9]+$ ]]; then
        echo -e "[!!] TMOD_DOWNLOAD_RETRY_DELAY must be a non-negative integer."
        exit 1
    fi

    steamcmd_args=(+force_install_dir /data/steamMods +login anonymous)
    valid_download_count=0
    IFS=',' read -r -a requested_downloads <<< "$TMOD_AUTODOWNLOAD"
    for requested_id in "${requested_downloads[@]}"; do
        mod_id="${requested_id//[[:space:]]/}"
        if ! [[ "$mod_id" =~ ^[0-9]+$ ]]; then
            echo -e "[!!] Ignoring invalid Workshop ID: $requested_id"
            continue
        fi
        steamcmd_args+=(+workshop_download_item 1281930 "$mod_id")
        ((valid_download_count+=1))
    done

    if ((valid_download_count == 0)); then
        echo -e "[!!] TMOD_AUTODOWNLOAD did not contain any valid numeric Workshop IDs."
        exit 1
    fi

    download_succeeded=false
    for ((attempt=1; attempt<=TMOD_DOWNLOAD_RETRIES; attempt++)); do
        if steamcmd "${steamcmd_args[@]}" +quit; then
            download_succeeded=true
            break
        fi

        if ((attempt < TMOD_DOWNLOAD_RETRIES)); then
            echo -e "[!!] SteamCMD attempt $attempt failed; retrying in $TMOD_DOWNLOAD_RETRY_DELAY seconds..."
            sleep "$TMOD_DOWNLOAD_RETRY_DELAY"
        fi
    done

    if [[ "$download_succeeded" != "true" ]]; then
        echo -e "[!!] FATAL: SteamCMD failed after $TMOD_DOWNLOAD_RETRIES attempts."
        exit 1
    fi

    echo -e "[SYSTEM] Finished downloading mods."
fi

# Enable Mods
if test -z "${TMOD_ENABLEDMODS}" ; then
    echo -e "[SYSTEM] The TMOD_ENABLEDMODS environment variable is not set. Defaulting to the mods specified in /data/tModLoader/Mods/enabled.json"
    echo -e "[SYSTEM] To change which mods are enabled, set the TMOD_ENABLEDMODS environment variable to a comma seperated list of mod Workshop IDs."
    echo -e "[SYSTEM] For more information, please see the Github README."
    sleep 5s
else
  enabledpath="/data/tModLoader/Mods/enabled.json"
  modpath="/data/steamMods/steamapps/workshop/content/1281930"
  enabled_mods=()

  echo -e "[SYSTEM] Enabling Mods specified in the TMOD_ENABLEDMODS Environment variable..."
  IFS=',' read -r -a requested_mods <<< "$TMOD_ENABLEDMODS"
  for requested_id in "${requested_mods[@]}"; do
    mod_id="${requested_id//[[:space:]]/}"
    echo -e "[SYSTEM] Enabling $mod_id..."

    if ! [[ "$mod_id" =~ ^[0-9]+$ ]]; then
      echo -e "[!!] Ignoring invalid Workshop ID: $requested_id"
      continue
    fi

    latest_tmod="$(find "$modpath/$mod_id" -type f -name '*.tmod' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
    if [[ -z "$latest_tmod" ]]; then
      echo -e "[!!] Mod ID $mod_id was not found. Has it been downloaded?"
      continue
    fi

    modname="$(basename "$latest_tmod" .tmod)"
    # For each mod name that we resolve, write the internal name of it to the enabled.json file.
    enabled_mods+=("$modname")
    echo -e "[SYSTEM] Enabled $modname ($mod_id)"
  done

  mkdir -p "$(dirname "$enabledpath")"
  {
    echo '['
    for ((index=0; index<${#enabled_mods[@]}; index++)); do
      escaped_modname="${enabled_mods[$index]//\\/\\\\}"
      escaped_modname="${escaped_modname//\"/\\\"}"
      separator=','
      if ((index == ${#enabled_mods[@]} - 1)); then
        separator=''
      fi
      printf '  "%s"%s\n' "$escaped_modname" "$separator"
    done
    echo ']'
  } > "$enabledpath"

  echo -e "\n[SYSTEM] Finished loading mods."
fi

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
