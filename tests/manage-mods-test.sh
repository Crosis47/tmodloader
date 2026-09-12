#!/usr/bin/env bash

set -Eeuo pipefail
export TMOD_WORKSHOP_BACKEND=steamcmd

script_under_test="${1:-/terraria-server/manage-mods.sh}"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

data_root="$test_root/data"
mock_bin="$test_root/bin"
manifest="$data_root/steamMods/steamapps/workshop/appworkshop_1281930.acf"
content_root="$data_root/steamMods/steamapps/workshop/content/1281930"
steamcmd_log="$test_root/steamcmd-args"

mkdir -p \
    "$mock_bin" \
    "$(dirname "$manifest")" \
    "$content_root/111/current" \
    "$content_root/222/old" \
    "$data_root/tModLoader/Mods"
touch "$content_root/111/current/CurrentMod.tmod"
touch "$content_root/222/old/OutdatedMod.tmod"

write_manifest() {
    local second_manifest="$1"
    local second_updated="$2"
    cat > "$manifest" <<EOF
"AppWorkshop"
{
    "WorkshopItemsInstalled"
    {
        "111"
        {
            "manifest" "current-111"
            "timeupdated" "200"
        }
        "222"
        {
            "manifest" "$second_manifest"
            "timeupdated" "$second_updated"
        }
    }
    "WorkshopItemDetails"
    {
    }
}
EOF
}

write_manifest "old-222" "100"

cat > "$mock_bin/curl" <<'EOF'
#!/usr/bin/env bash
if [[ "${TEST_CURL_FAIL:-false}" == "true" ]]; then
    exit 22
fi

if [[ "$*" == *GetCollectionDetails* ]]; then
    if [[ "$*" == *"publishedfileids[0]=333"* ]]; then
        cat <<'JSON'
{"response":{"collectiondetails":[{"result":1,"children":[
  {"publishedfileid":"111","filetype":0},
  {"publishedfileid":"444","filetype":2}
]}]}}
JSON
    elif [[ "$*" == *"publishedfileids[0]=444"* ]]; then
        cat <<'JSON'
{"response":{"collectiondetails":[{"result":1,"children":[
  {"publishedfileid":"222","filetype":0}
]}]}}
JSON
    else
        exit 22
    fi
    exit 0
fi

cat <<'JSON'
{
  "response": {
    "publishedfiledetails": [
      {"publishedfileid":"111","result":1,"consumer_app_id":1281930,"title":"Current Mod","hcontent_file":"current-111","time_updated":200},
      {"publishedfileid":"222","result":1,"consumer_app_id":1281930,"title":"Outdated Mod","hcontent_file":"current-222","time_updated":200}
    ]
  }
}
JSON
EOF

cat > "$mock_bin/steamcmd" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$TEST_STEAMCMD_LOG"
if [[ "${TEST_STEAMCMD_FAIL:-false}" == "true" ]]; then
    exit 1
fi
cat > "$TEST_WORKSHOP_MANIFEST" <<'ACF'
"AppWorkshop"
{
    "WorkshopItemsInstalled"
    {
        "111"
        {
            "manifest" "current-111"
            "timeupdated" "200"
        }
        "222"
        {
            "manifest" "current-222"
            "timeupdated" "200"
        }
    }
    "WorkshopItemDetails"
    {
    }
}
ACF
EOF

chmod 755 "$mock_bin/curl" "$mock_bin/steamcmd"
export TEST_STEAMCMD_LOG="$steamcmd_log"
export TEST_WORKSHOP_MANIFEST="$manifest"

run_manager() {
    local mod_spec="${1:-111, 222,111}"
    TMOD_MODS="$mod_spec" \
    TMOD_DATA_DIR="$data_root" \
    TMOD_CURL_BIN="$mock_bin/curl" \
    TMOD_STEAMCMD_BIN="$mock_bin/steamcmd" \
    TMOD_JQ_BIN="jq" \
    TMOD_WORKSHOP_COLLECTION_API_URL="https://example.invalid/GetCollectionDetails" \
    TMOD_DOWNLOAD_RETRIES="1" \
    bash "$script_under_test"
}

run_manager

grep -Fxq "222" "$steamcmd_log"
if grep -Fxq "111" "$steamcmd_log"; then
    echo "Current mod 111 was unexpectedly sent to Workshop downloader." >&2
    exit 1
fi
jq -e '. == ["CurrentMod", "OutdatedMod"]' "$data_root/tModLoader/Mods/enabled.json" >/dev/null

rm -f "$steamcmd_log"
run_manager
if [[ -e "$steamcmd_log" ]]; then
    echo "Workshop downloader was unexpectedly called when every mod was current." >&2
    exit 1
fi

run_manager "collection:333,111"
if [[ -e "$steamcmd_log" ]]; then
    echo "Workshop downloader was unexpectedly called for a current expanded collection." >&2
    exit 1
fi
jq -e '. == ["CurrentMod", "OutdatedMod"]' "$data_root/tModLoader/Mods/enabled.json" >/dev/null
grep -Fxq "111" "$data_root/tModLoader/Mods/collection-cache/333.txt"
grep -Fxq "222" "$data_root/tModLoader/Mods/collection-cache/333.txt"

export TEST_CURL_FAIL=true
run_manager "collection:333"
unset TEST_CURL_FAIL
if [[ -e "$steamcmd_log" ]]; then
    echo "Workshop downloader was unexpectedly called while complete cached collection data was available offline." >&2
    exit 1
fi

export TEST_CURL_FAIL=true
export TEST_STEAMCMD_FAIL=true
if TMOD_MOD_OFFLINE_POLICY=strict run_manager "collection:333"; then
    echo "Strict offline policy unexpectedly accepted a failed Steam check." >&2
    exit 1
fi
unset TEST_STEAMCMD_FAIL
unset TEST_CURL_FAIL

export TEST_CURL_FAIL=true
export TEST_STEAMCMD_FAIL=true
if run_manager "collection:333,999"; then
    echo "Offline startup unexpectedly accepted a requested mod missing from cache." >&2
    exit 1
fi
unset TEST_STEAMCMD_FAIL
unset TEST_CURL_FAIL

if TMOD_MODS="not-a-workshop-id" \
    TMOD_DATA_DIR="$data_root" \
    TMOD_CURL_BIN="$mock_bin/curl" \
    TMOD_STEAMCMD_BIN="$mock_bin/steamcmd" \
    TMOD_JQ_BIN="jq" \
    bash "$script_under_test"; then
    echo "An invalid TMOD_MODS value unexpectedly succeeded." >&2
    exit 1
fi

if TMOD_MODS="111" \
    TMOD_COLLECTION_MAX_ITEMS="0" \
    TMOD_DATA_DIR="$data_root" \
    TMOD_CURL_BIN="$mock_bin/curl" \
    TMOD_STEAMCMD_BIN="$mock_bin/steamcmd" \
    TMOD_JQ_BIN="jq" \
    bash "$script_under_test"; then
    echo "An invalid collection safety limit unexpectedly succeeded." >&2
    exit 1
fi

echo "manage-mods tests passed."
