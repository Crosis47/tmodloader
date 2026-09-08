#!/usr/bin/env bash

# shellcheck disable=SC2034,SC2178
# Bash namerefs intentionally populate arrays owned by their callers.

set -Eeuo pipefail

workshop_app_id="1281930"
data_dir="${TMOD_DATA_DIR:-/data}"
steam_root="$data_dir/steamMods"
workshop_root="$steam_root/steamapps/workshop"
content_root="$workshop_root/content/$workshop_app_id"
workshop_manifest="$workshop_root/appworkshop_${workshop_app_id}.acf"
enabled_path="$data_dir/tModLoader/Mods/enabled.json"
collection_cache_dir="$data_dir/tModLoader/Mods/collection-cache"
workshop_api_url="${TMOD_WORKSHOP_API_URL:-https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/}"
collection_api_url="${TMOD_WORKSHOP_COLLECTION_API_URL:-https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/}"
steamcmd_bin="${TMOD_STEAMCMD_BIN:-steamcmd}"
curl_bin="${TMOD_CURL_BIN:-curl}"
jq_bin="${TMOD_JQ_BIN:-jq}"

log() {
    printf '[SYSTEM] %s\n' "$*"
}

warn() {
    printf '[!!] %s\n' "$*" >&2
}

parse_workshop_ids() {
    local raw="$1"
    local variable_name="$2"
    local result_name="$3"
    local -n result_ref="$result_name"
    local -A seen=()
    local entry mod_id
    local -a entries

    result_ref=()
    IFS=',' read -r -a entries <<< "$raw"
    for entry in "${entries[@]}"; do
        mod_id="${entry//[[:space:]]/}"
        if ! [[ "$mod_id" =~ ^[0-9]+$ ]]; then
            warn "Ignoring invalid Workshop ID in $variable_name: $entry"
            continue
        fi
        if [[ -z "${seen[$mod_id]:-}" ]]; then
            result_ref+=("$mod_id")
            seen[$mod_id]=1
        fi
    done

    if ((${#result_ref[@]} == 0)); then
        warn "$variable_name did not contain any valid numeric Workshop IDs."
        return 1
    fi
}

load_cached_collection() {
    local collection_id="$1"
    local result_name="$2"
    local -n result_ref="$result_name"
    local cache_path="$collection_cache_dir/$collection_id.txt"
    local mod_id

    result_ref=()
    [[ -s "$cache_path" ]] || return 1
    while IFS= read -r mod_id; do
        [[ "$mod_id" =~ ^[0-9]+$ ]] || continue
        result_ref+=("$mod_id")
    done < "$cache_path"
    ((${#result_ref[@]} > 0)) || return 1
    warn "Steam collection $collection_id could not be refreshed; using ${#result_ref[@]} cached mod ID(s)."
}

write_collection_cache() {
    local collection_id="$1"
    local ids_name="$2"
    local -n ids_ref="$ids_name"
    local temporary_cache

    mkdir -p "$collection_cache_dir"
    temporary_cache="$(mktemp "$collection_cache_dir/$collection_id.tmp.XXXXXX")"
    printf '%s\n' "${ids_ref[@]}" > "$temporary_cache"
    mv -f "$temporary_cache" "$collection_cache_dir/$collection_id.txt"
}

fetch_collection_children() {
    local collection_id="$1"
    local ids_name="$2"
    local types_name="$3"
    local -n ids_ref="$ids_name"
    local -n types_ref="$types_name"
    local response child_id child_type

    ids_ref=()
    types_ref=()
    if ! response="$({
        "$curl_bin" \
            --fail \
            --silent \
            --show-error \
            --connect-timeout 10 \
            --max-time 30 \
            --request POST \
            --data-urlencode 'collectioncount=1' \
            --data-urlencode "publishedfileids[0]=$collection_id" \
            "$collection_api_url"
    })"; then
        return 1
    fi
    "$jq_bin" -e '
        .response.collectiondetails[0]
        | (.result == 1) and (.children | type == "array")
    ' >/dev/null <<< "$response" || return 1

    while IFS=$'\t' read -r child_id child_type; do
        [[ "$child_id" =~ ^[0-9]+$ ]] || continue
        ids_ref+=("$child_id")
        types_ref+=("$child_type")
    done < <(
        "$jq_bin" -r '
            .response.collectiondetails[0].children[]
            | [(.publishedfileid | tostring), (.filetype | tostring)]
            | @tsv
        ' <<< "$response"
    )
}

filter_tmodloader_items() {
    local ids_name="$1"
    local result_name="$2"
    local -n ids_ref="$ids_name"
    local -n result_ref="$result_name"
    local batch_start batch_end index response remote_id result consumer_app_id title
    local -a curl_args

    result_ref=()
    for ((batch_start=0; batch_start<${#ids_ref[@]}; batch_start+=100)); do
        batch_end=$((batch_start + 100))
        if ((batch_end > ${#ids_ref[@]})); then
            batch_end=${#ids_ref[@]}
        fi
        curl_args=(
            --fail
            --silent
            --show-error
            --connect-timeout 10
            --max-time 30
            --request POST
            --data-urlencode "itemcount=$((batch_end - batch_start))"
        )
        for ((index=batch_start; index<batch_end; index++)); do
            curl_args+=(--data-urlencode "publishedfileids[$((index - batch_start))]=${ids_ref[$index]}")
        done

        response="$("$curl_bin" "${curl_args[@]}" "$workshop_api_url")" || return 1
        "$jq_bin" -e '.response.publishedfiledetails | type == "array"' >/dev/null <<< "$response" || return 1
        while IFS=$'\t' read -r remote_id result consumer_app_id title; do
            if [[ "$result" == "1" && "$consumer_app_id" == "$workshop_app_id" ]]; then
                result_ref+=("$remote_id")
            else
                warn "Excluding collection item $remote_id (${title:-unknown}); it is not a public tModLoader Workshop item."
            fi
        done < <(
            "$jq_bin" -r '
                .response.publishedfiledetails[]
                | [
                    (.publishedfileid | tostring),
                    (.result | tostring),
                    (.consumer_app_id // .consumer_appid // 0 | tostring),
                    (.title // "" | tostring)
                ]
                | @tsv
            ' <<< "$response"
        )
    done
}

expand_collection() {
    local root_collection_id="$1"
    local result_name="$2"
    local -n result_ref="$result_name"
    local maximum_items="${TMOD_COLLECTION_MAX_ITEMS:-1000}"
    local queue_index=0 collection_id child_index child_id
    local -a collection_queue=("$root_collection_id")
    local -a child_ids=() child_types=() raw_items=() filtered_items=()
    local -A seen_collections=() seen_items=()

    while ((queue_index < ${#collection_queue[@]})); do
        collection_id="${collection_queue[$queue_index]}"
        queue_index=$((queue_index + 1))
        [[ -z "${seen_collections[$collection_id]:-}" ]] || continue
        seen_collections[$collection_id]=1
        if ((${#seen_collections[@]} > maximum_items)); then
            warn "Collection $root_collection_id exceeded TMOD_COLLECTION_MAX_ITEMS=$maximum_items."
            load_cached_collection "$root_collection_id" "$result_name"
            return
        fi

        if ! fetch_collection_children "$collection_id" child_ids child_types; then
            warn "Could not expand Steam collection $collection_id."
            load_cached_collection "$root_collection_id" "$result_name"
            return
        fi
        for ((child_index=0; child_index<${#child_ids[@]}; child_index++)); do
            child_id="${child_ids[$child_index]}"
            if [[ "${child_types[$child_index]}" == "2" ]]; then
                collection_queue+=("$child_id")
            elif [[ -z "${seen_items[$child_id]:-}" ]]; then
                raw_items+=("$child_id")
                seen_items[$child_id]=1
                if ((${#raw_items[@]} > maximum_items)); then
                    warn "Collection $root_collection_id exceeded TMOD_COLLECTION_MAX_ITEMS=$maximum_items."
                    load_cached_collection "$root_collection_id" "$result_name"
                    return
                fi
            fi
        done
    done

    if ((${#raw_items[@]} == 0)) || ! filter_tmodloader_items raw_items filtered_items || ((${#filtered_items[@]} == 0)); then
        warn "Collection $root_collection_id did not resolve to any verifiable tModLoader mods."
        load_cached_collection "$root_collection_id" "$result_name"
        return
    fi

    result_ref=("${filtered_items[@]}")
    write_collection_cache "$root_collection_id" "$result_name"
    log "Expanded collection $root_collection_id to ${#result_ref[@]} tModLoader mod(s)."
}

parse_workshop_spec() {
    local raw="$1"
    local variable_name="$2"
    local result_name="$3"
    local -n result_ref="$result_name"
    local entry token collection_id mod_id
    local -a entries collection_items
    local -A seen=()

    result_ref=()
    IFS=',' read -r -a entries <<< "$raw"
    for entry in "${entries[@]}"; do
        token="${entry//[[:space:]]/}"
        if [[ "$token" =~ ^[0-9]+$ ]]; then
            collection_items=("$token")
        elif [[ "$token" =~ ^collection:([0-9]+)$ ]]; then
            collection_id="${BASH_REMATCH[1]}"
            collection_items=()
            expand_collection "$collection_id" collection_items
        else
            warn "Ignoring invalid entry in $variable_name: $entry"
            continue
        fi

        for mod_id in "${collection_items[@]}"; do
            if [[ -z "${seen[$mod_id]:-}" ]]; then
                result_ref+=("$mod_id")
                seen[$mod_id]=1
            fi
        done
    done

    if ((${#result_ref[@]} == 0)); then
        warn "$variable_name did not resolve to any valid Workshop IDs."
        return 1
    fi
}

local_manifest_field() {
    local mod_id="$1"
    local field="$2"

    [[ -f "$workshop_manifest" ]] || return 0
    awk -v target="$mod_id" -v requested_field="$field" '
        $1 == "\"WorkshopItemsInstalled\"" { in_installed = 1; next }
        in_installed && $1 == "\"WorkshopItemDetails\"" { exit }
        in_installed && $1 == "\"" target "\"" { in_item = 1; next }
        in_item && $1 == "\"" requested_field "\"" {
            value = $2
            gsub(/\"/, "", value)
            print value
            exit
        }
        in_item && $1 ~ /^\"[0-9]+\"$/ { in_item = 0 }
    ' "$workshop_manifest"
}

latest_tmod_for_id() {
    local mod_id="$1"
    local latest_record

    latest_record="$(find "$content_root/$mod_id" -type f -name '*.tmod' -printf '%T@ %p\n' 2>/dev/null | sort -nr | sed -n '1p')"
    [[ -n "$latest_record" ]] || return 1
    printf '%s\n' "${latest_record#* }"
}

fetch_remote_details() {
    local ids_name="$1"
    local content_name="$2"
    local updated_name="$3"
    local -n ids_ref="$ids_name"
    local -n content_ref="$content_name"
    local -n updated_ref="$updated_name"
    local batch_start batch_end index response
    local remote_id result content_manifest time_updated
    local all_batches_succeeded=true
    local -a curl_args

    content_ref=()
    updated_ref=()

    for ((batch_start=0; batch_start<${#ids_ref[@]}; batch_start+=100)); do
        batch_end=$((batch_start + 100))
        if ((batch_end > ${#ids_ref[@]})); then
            batch_end=${#ids_ref[@]}
        fi

        curl_args=(
            --fail
            --silent
            --show-error
            --connect-timeout 10
            --max-time 30
            --request POST
            --data-urlencode "itemcount=$((batch_end - batch_start))"
        )
        for ((index=batch_start; index<batch_end; index++)); do
            curl_args+=(--data-urlencode "publishedfileids[$((index - batch_start))]=${ids_ref[$index]}")
        done

        if ! response="$("$curl_bin" "${curl_args[@]}" "$workshop_api_url")"; then
            warn "Could not query Steam Workshop metadata; SteamCMD will check every requested mod."
            all_batches_succeeded=false
            continue
        fi
        if ! "$jq_bin" -e '.response.publishedfiledetails | type == "array"' >/dev/null <<< "$response"; then
            warn "Steam Workshop returned an unexpected response; SteamCMD will check every requested mod."
            all_batches_succeeded=false
            continue
        fi

        while IFS=$'\t' read -r remote_id result content_manifest time_updated; do
            if [[ "$result" == "1" ]]; then
                # shellcheck disable=SC2034 # Namerefs populate caller-owned maps.
                content_ref[$remote_id]="$content_manifest"
                # shellcheck disable=SC2034 # Namerefs populate caller-owned maps.
                updated_ref[$remote_id]="$time_updated"
            else
                warn "Steam Workshop did not return public metadata for mod $remote_id (result $result)."
            fi
        done < <(
            "$jq_bin" -r '
                .response.publishedfiledetails[]
                | [
                    (.publishedfileid | tostring),
                    (.result | tostring),
                    (.hcontent_file // "" | tostring),
                    (.time_updated // 0 | tostring)
                ]
                | @tsv
            ' <<< "$response"
        )
    done

    [[ "$all_batches_succeeded" == "true" ]]
}

download_required_mods() {
    local ids_name="$1"
    local -n ids_ref="$ids_name"
    local mod_id local_content_manifest local_updated remote_content_manifest remote_updated
    local latest_tmod api_succeeded=false download_succeeded=false
    local offline_policy="${TMOD_MOD_OFFLINE_POLICY:-use-cache}"
    local attempt
    local -A remote_content=()
    local -A remote_times=()
    local -a download_candidates=()
    local -a steamcmd_args

    if fetch_remote_details "$ids_name" remote_content remote_times; then
        api_succeeded=true
    fi

    for mod_id in "${ids_ref[@]}"; do
        latest_tmod="$(latest_tmod_for_id "$mod_id" || true)"
        local_content_manifest="$(local_manifest_field "$mod_id" manifest)"
        local_updated="$(local_manifest_field "$mod_id" timeupdated)"
        remote_content_manifest="${remote_content[$mod_id]:-}"
        remote_updated="${remote_times[$mod_id]:-}"

        if [[ -z "$latest_tmod" ]]; then
            log "Mod $mod_id is missing and will be downloaded."
            download_candidates+=("$mod_id")
        elif [[ -n "$local_content_manifest" && -n "$remote_content_manifest" ]]; then
            if [[ "$local_content_manifest" == "$remote_content_manifest" ]]; then
                log "Mod $mod_id is already current (content manifest $local_content_manifest)."
            else
                log "Mod $mod_id has a newer Workshop version and will be updated."
                download_candidates+=("$mod_id")
            fi
        elif [[ "$local_updated" =~ ^[0-9]+$ && "$remote_updated" =~ ^[0-9]+$ && "$local_updated" -ge "$remote_updated" ]]; then
            log "Mod $mod_id is already current (updated $local_updated)."
        elif [[ "$offline_policy" == "use-cache" ]]; then
            warn "Could not verify mod $mod_id with Steam; continuing with its cached .tmod file."
        else
            if [[ "$api_succeeded" == "true" ]]; then
                log "Mod $mod_id could not be version-matched and will be checked by SteamCMD."
            fi
            download_candidates+=("$mod_id")
        fi
    done

    if ((${#download_candidates[@]} == 0)); then
        log "All requested mods are already current; skipping SteamCMD."
        return 0
    fi

    if ! [[ "${TMOD_DOWNLOAD_RETRIES:-3}" =~ ^[1-9][0-9]*$ ]]; then
        warn "TMOD_DOWNLOAD_RETRIES must be a positive integer."
        return 1
    fi
    if ! [[ "${TMOD_DOWNLOAD_RETRY_DELAY:-10}" =~ ^[0-9]+$ ]]; then
        warn "TMOD_DOWNLOAD_RETRY_DELAY must be a non-negative integer."
        return 1
    fi

    steamcmd_args=(+force_install_dir "$steam_root" +login anonymous)
    for mod_id in "${download_candidates[@]}"; do
        steamcmd_args+=(+workshop_download_item "$workshop_app_id" "$mod_id")
    done

    for ((attempt=1; attempt<=${TMOD_DOWNLOAD_RETRIES:-3}; attempt++)); do
        if "$steamcmd_bin" "${steamcmd_args[@]}" +quit; then
            download_succeeded=true
            break
        fi
        if ((attempt < ${TMOD_DOWNLOAD_RETRIES:-3})); then
            warn "SteamCMD attempt $attempt failed; retrying in ${TMOD_DOWNLOAD_RETRY_DELAY:-10} seconds."
            sleep "${TMOD_DOWNLOAD_RETRY_DELAY:-10}"
        fi
    done

    if [[ "$download_succeeded" != "true" ]]; then
        if [[ "$offline_policy" == "use-cache" ]]; then
            for mod_id in "${download_candidates[@]}"; do
                if ! latest_tmod_for_id "$mod_id" >/dev/null; then
                    warn "FATAL: SteamCMD failed and mod $mod_id is not available in the local cache."
                    return 1
                fi
            done
            warn "SteamCMD failed, but every requested mod is cached; starting with the cached versions."
            return 0
        fi
        warn "FATAL: SteamCMD failed after ${TMOD_DOWNLOAD_RETRIES:-3} attempts."
        return 1
    fi

    for mod_id in "${download_candidates[@]}"; do
        if ! latest_tmod_for_id "$mod_id" >/dev/null; then
            warn "FATAL: SteamCMD completed, but mod $mod_id has no .tmod file in the Workshop cache."
            return 1
        fi

        remote_content_manifest="${remote_content[$mod_id]:-}"
        local_content_manifest="$(local_manifest_field "$mod_id" manifest)"
        if [[ -n "$remote_content_manifest" && -n "$local_content_manifest" && "$remote_content_manifest" != "$local_content_manifest" ]]; then
            if [[ "$offline_policy" == "use-cache" ]]; then
                warn "Mod $mod_id did not reach Steam manifest $remote_content_manifest; using cached manifest $local_content_manifest."
            else
                warn "FATAL: Mod $mod_id is still on content manifest $local_content_manifest; Steam reports $remote_content_manifest."
                return 1
            fi
        fi
    done

    log "Finished downloading and updating mods."
}

write_enabled_mods() {
    local ids_name="$1"
    local -n ids_ref="$ids_name"
    local mod_id latest_tmod mod_name temporary_enabled
    local -A seen_names=()
    local -a enabled_mods=()

    for mod_id in "${ids_ref[@]}"; do
        latest_tmod="$(latest_tmod_for_id "$mod_id" || true)"
        if [[ -z "$latest_tmod" ]]; then
            warn "FATAL: Cannot enable mod $mod_id because no .tmod file was found."
            return 1
        fi

        mod_name="$(basename "$latest_tmod" .tmod)"
        if [[ -z "${seen_names[$mod_name]:-}" ]]; then
            enabled_mods+=("$mod_name")
            seen_names[$mod_name]=1
        fi
        log "Enabled $mod_name ($mod_id)."
    done

    mkdir -p "$(dirname "$enabled_path")"
    temporary_enabled="$(mktemp "${enabled_path}.tmp.XXXXXX")"
    if ! "$jq_bin" --null-input --args '$ARGS.positional' -- "${enabled_mods[@]}" > "$temporary_enabled"; then
        rm -f "$temporary_enabled"
        return 1
    fi
    mv -f "$temporary_enabled" "$enabled_path"
    log "Wrote ${#enabled_mods[@]} mod(s) to $enabled_path."
}

main() {
    local managed_spec="${TMOD_MODS:-}"
    local download_spec enable_spec download_label enable_label
    # shellcheck disable=SC2034 # Populated by parse_workshop_ids through a nameref.
    local -a download_ids=()
    # shellcheck disable=SC2034 # Populated by parse_workshop_ids through a nameref.
    local -a enable_ids=()

    case "${TMOD_MOD_OFFLINE_POLICY:-use-cache}" in
        use-cache|strict) ;;
        *)
            warn "TMOD_MOD_OFFLINE_POLICY must be 'use-cache' or 'strict'."
            return 1
            ;;
    esac
    if ! [[ "${TMOD_COLLECTION_MAX_ITEMS:-1000}" =~ ^[1-9][0-9]*$ ]]; then
        warn "TMOD_COLLECTION_MAX_ITEMS must be a positive integer."
        return 1
    fi

    if [[ -n "$managed_spec" ]]; then
        parse_workshop_spec "$managed_spec" TMOD_MODS download_ids
        enable_ids=("${download_ids[@]}")
        download_required_mods download_ids
        write_enabled_mods enable_ids
        return 0
    else
        download_spec="${TMOD_AUTODOWNLOAD:-}"
        enable_spec="${TMOD_ENABLEDMODS:-}"
        download_label="TMOD_AUTODOWNLOAD"
        enable_label="TMOD_ENABLEDMODS"
        if [[ -n "$download_spec" || -n "$enable_spec" ]]; then
            warn "TMOD_AUTODOWNLOAD and TMOD_ENABLEDMODS are deprecated; combine the IDs in TMOD_MODS."
        fi
    fi

    if [[ -z "$download_spec" && -z "$enable_spec" ]]; then
        log "TMOD_MODS is empty; keeping the existing enabled.json and Workshop cache unchanged."
        return 0
    fi

    if [[ -n "$download_spec" ]]; then
        parse_workshop_ids "$download_spec" "$download_label" download_ids
        download_required_mods download_ids
    fi

    if [[ -n "$enable_spec" ]]; then
        parse_workshop_ids "$enable_spec" "$enable_label" enable_ids
        write_enabled_mods enable_ids
    fi
}

main "$@"
