#!/usr/bin/env bash

set -Eeuo pipefail

config_path="${TMOD_CONFIG_PATH:-/terraria-server/serverconfig.txt}"
data_dir="${TMOD_DATA_DIR:-/data}"
world_dir="$data_dir/tModLoader/Worlds"

fail() {
    printf '[!!] FATAL: %s\n' "$*" >&2
    exit 1
}

reject_line_breaks() {
    local variable_name="$1"
    local value="$2"

    if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
        fail "$variable_name cannot contain line breaks."
    fi
}

require_integer_range() {
    local variable_name="$1"
    local value="$2"
    local minimum="$3"
    local maximum="$4"

    [[ "$value" =~ ^[0-9]+$ ]] || fail "$variable_name must be an integer from $minimum through $maximum."
    ((10#$value >= minimum && 10#$value <= maximum)) || \
        fail "$variable_name must be an integer from $minimum through $maximum."
}

require_permission() {
    require_integer_range "$1" "$2" 0 2
}

append_config() {
    printf '%s=%s\n' "$1" "$2" >> "$config_path"
}

reject_line_breaks TMOD_MOTD "$TMOD_MOTD"
reject_line_breaks TMOD_PASS "$TMOD_PASS"
reject_line_breaks TMOD_WORLDNAME "$TMOD_WORLDNAME"
reject_line_breaks TMOD_WORLDSEED "$TMOD_WORLDSEED"

[[ -n "$TMOD_WORLDNAME" ]] || fail "TMOD_WORLDNAME cannot be empty."
[[ "$TMOD_WORLDNAME" != */* && "$TMOD_WORLDNAME" != *\\* && "$TMOD_WORLDNAME" != "." && "$TMOD_WORLDNAME" != ".." ]] || \
    fail "TMOD_WORLDNAME cannot contain path separators or be '.' or '..'."
[[ "$TMOD_LANGUAGE" =~ ^[A-Za-z]{2,3}(-[A-Za-z0-9]+)*$ ]] || \
    fail "TMOD_LANGUAGE must be a language code such as en-US."

require_integer_range TMOD_MAXPLAYERS "$TMOD_MAXPLAYERS" 1 255
require_integer_range TMOD_WORLDSIZE "$TMOD_WORLDSIZE" 1 3
require_integer_range TMOD_DIFFICULTY "$TMOD_DIFFICULTY" 0 3
require_integer_range TMOD_SECURE "$TMOD_SECURE" 0 1
require_integer_range TMOD_NPCSTREAM "$TMOD_NPCSTREAM" 0 1000
require_integer_range TMOD_UPNP "$TMOD_UPNP" 0 1
require_integer_range TMOD_PRIORITY "$TMOD_PRIORITY" 0 5
require_integer_range TMOD_PORT "$TMOD_PORT" 1 65535

require_permission TMOD_JOURNEY_SETFROZEN "$TMOD_JOURNEY_SETFROZEN"
require_permission TMOD_JOURNEY_SETDAWN "$TMOD_JOURNEY_SETDAWN"
require_permission TMOD_JOURNEY_SETNOON "$TMOD_JOURNEY_SETNOON"
require_permission TMOD_JOURNEY_SETDUSK "$TMOD_JOURNEY_SETDUSK"
require_permission TMOD_JOURNEY_SETMIDNIGHT "$TMOD_JOURNEY_SETMIDNIGHT"
require_permission TMOD_JOURNEY_GODMODE "$TMOD_JOURNEY_GODMODE"
require_permission TMOD_JOURNEY_WIND_STRENGTH "$TMOD_JOURNEY_WIND_STRENGTH"
require_permission TMOD_JOURNEY_RAIN_STRENGTH "$TMOD_JOURNEY_RAIN_STRENGTH"
require_permission TMOD_JOURNEY_TIME_SPEED "$TMOD_JOURNEY_TIME_SPEED"
require_permission TMOD_JOURNEY_RAIN_FROZEN "$TMOD_JOURNEY_RAIN_FROZEN"
require_permission TMOD_JOURNEY_WIND_FROZEN "$TMOD_JOURNEY_WIND_FROZEN"
require_permission TMOD_JOURNEY_PLACEMENT_RANGE "$TMOD_JOURNEY_PLACEMENT_RANGE"
require_permission TMOD_JOURNEY_SET_DIFFICULTY "$TMOD_JOURNEY_SET_DIFFICULTY"
require_permission TMOD_JOURNEY_BIOME_SPREAD "$TMOD_JOURNEY_BIOME_SPREAD"
require_permission TMOD_JOURNEY_SPAWN_RATE "$TMOD_JOURNEY_SPAWN_RATE"

mkdir -p "$(dirname "$config_path")" "$world_dir"
: > "$config_path"
chmod 600 "$config_path"

printf '[CONFIG] Generating %s\n' "$config_path"
printf '[CONFIG] World: %s; size: %s; difficulty: %s; max players: %s; port: %s\n' \
    "$TMOD_WORLDNAME" "$TMOD_WORLDSIZE" "$TMOD_DIFFICULTY" "$TMOD_MAXPLAYERS" "$TMOD_PORT"
if [[ "$TMOD_PASS" == "N/A" ]]; then
    printf '[CONFIG] Server password: disabled\n'
else
    printf '[CONFIG] Server password: configured (value redacted)\n'
fi

world_path="$world_dir/$TMOD_WORLDNAME.wld"
append_config world "$world_path"
append_config worldpath "$world_dir/"
if [[ ! -e "$world_path" ]]; then
    printf '[!!] WARNING: World %s was not found at %s; tModLoader will create it. This is expected on first launch.\n' \
        "$TMOD_WORLDNAME" "$world_path"
    append_config worldname "$TMOD_WORLDNAME"
    append_config autocreate "$TMOD_WORLDSIZE"
fi

if [[ "$TMOD_PASS" != "N/A" ]]; then
    append_config password "$TMOD_PASS"
fi

append_config motd "$TMOD_MOTD"
append_config maxplayers "$TMOD_MAXPLAYERS"
append_config seed "$TMOD_WORLDSEED"
append_config difficulty "$TMOD_DIFFICULTY"
append_config secure "$TMOD_SECURE"
append_config language "$TMOD_LANGUAGE"
append_config npcstream "$TMOD_NPCSTREAM"
append_config upnp "$TMOD_UPNP"
append_config priority "$TMOD_PRIORITY"
append_config port "$TMOD_PORT"

append_config journeypermission_time_setfrozen "$TMOD_JOURNEY_SETFROZEN"
append_config journeypermission_time_setdawn "$TMOD_JOURNEY_SETDAWN"
append_config journeypermission_time_setnoon "$TMOD_JOURNEY_SETNOON"
append_config journeypermission_time_setdusk "$TMOD_JOURNEY_SETDUSK"
append_config journeypermission_time_setmidnight "$TMOD_JOURNEY_SETMIDNIGHT"
append_config journeypermission_godmode "$TMOD_JOURNEY_GODMODE"
append_config journeypermission_wind_setstrength "$TMOD_JOURNEY_WIND_STRENGTH"
append_config journeypermission_rain_setstrength "$TMOD_JOURNEY_RAIN_STRENGTH"
append_config journeypermission_time_setspeed "$TMOD_JOURNEY_TIME_SPEED"
append_config journeypermission_rain_setfrozen "$TMOD_JOURNEY_RAIN_FROZEN"
append_config journeypermission_wind_setfrozen "$TMOD_JOURNEY_WIND_FROZEN"
append_config journeypermission_increaseplacementrange "$TMOD_JOURNEY_PLACEMENT_RANGE"
append_config journeypermission_setdifficulty "$TMOD_JOURNEY_SET_DIFFICULTY"
append_config journeypermission_biomespread_setfrozen "$TMOD_JOURNEY_BIOME_SPREAD"
append_config journeypermission_setspawnrate "$TMOD_JOURNEY_SPAWN_RATE"

printf '[CONFIG] Finished writing validated server settings.\n'
