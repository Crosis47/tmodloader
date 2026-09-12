"""Human-facing labels and help for every editable administration setting."""
GROUPS = [
    ('server', 'Server configuration', 'Player access, welcome message, and networking behavior.'),
    ('world', 'World configuration', 'Choose a world or configure creation of a new one. Creation settings do not modify an existing world.'),
    ('backup', 'Backup configuration', 'Cold backups disconnect players while the game is saved, archived, and restarted. Autosave is not a backup.'),
    ('mods', 'Mods & Workshop', 'Choose mods and control downloads. You can also stage selections in the Workshop browser.'),
    ('runtime', 'Runtime & logs', 'Autosave, shutdown behavior, and the amount of console output.'),
    ('journey', 'Journey permissions', 'These permissions apply to Journey worlds; they control who may change each Journey power.'),
]

FIELDS = {}


def field(key, group, label, help_text):
    FIELDS['TMOD_' + key] = {'group': group, 'label': label, 'help': help_text}


field('MOTD', 'server', 'Welcome message', 'Message displayed to players when they join the server.')
field('MAXPLAYERS', 'server', 'Maximum players', 'Maximum simultaneous players allowed, from 1 to 255.')
field('LANGUAGE', 'server', 'Server language', 'Language code for server messages, such as en-US.')
field('SECURE', 'server', 'Additional cheat protection', '0 disables Terraria’s additional cheat checks; 1 enables them. This is not authentication or a firewall.')
field('NPCSTREAM', 'server', 'NPC streaming range', 'Controls NPC streaming to clients, from 0 to 1000. Leave the default unless tuning network behavior.')
field('UPNP', 'server', 'UPnP port mapping', '0 disables automatic router port mapping; 1 requests it. Docker port publishing and firewall rules still need host configuration.')
field('WORLDNAME', 'world', 'World name', 'Selects the world file by name. A different name may create a new world if no matching file exists. Do not include path separators.')
field('WORLDSIZE', 'world', 'New world size', 'Used only when creating a world: 1 small, 2 medium, 3 large.')
field('WORLDEVIL', 'world', 'New world evil', 'Random, Corruption, or Crimson. To change evil in the WebUI, choose an unused world name, stage the settings, and apply changes. Apply saves and stops the game, disconnects players, creates the new world, and restarts. Existing worlds are never converted; a matching name loads that world. Custom evil requires a name of at most 26 characters and seed of at most 39 characters. Special seeds and mods may generate both evils or alter generation.')
field('WORLDSEED', 'world', 'New world seed', 'Seed used when generating a new world. Changing it does not regenerate the current world.')
field('DIFFICULTY', 'world', 'New world difficulty', 'Used when creating a world: 0 Classic, 1 Expert, 2 Master, 3 Journey.')
field('BACKUP_INTERVAL', 'backup', 'Backup interval (minutes)', '0 disables scheduled backups. 1440 runs approximately every 24 hours. The interval resets on container start or after a manual backup.')
field('BACKUP_KEEP', 'backup', 'Backups to retain', 'Number of verified backup bundles to keep for this data directory. Cleanup runs only after a successful backup and restart; recovery originals are not pruned.')
field('BACKUP_MIN_FREE_MB', 'backup', 'Minimum free space (MiB)', 'Refuse a backup before stopping the game when /backups has less free space than this threshold. 1024 means 1 GiB. This is not an archive-size estimate; 0 disables the threshold.')
field('MODS', 'mods', 'Selected Workshop entries', 'Comma-separated Workshop mod IDs or collection:ID entries. Removing an entry disables it on managed startup but keeps cached downloads.')
field('MOD_OFFLINE_POLICY', 'mods', 'Steam offline policy', 'use-cache allows startup with available cached mods when Steam cannot be reached. strict fails if required update/download checks fail.')
field('DOWNLOAD_RETRIES', 'mods', 'Download attempts', 'Maximum attempts for transient Steam Workshop download failures, from 1 to 20.')
field('DOWNLOAD_RETRY_DELAY', 'mods', 'Retry delay (seconds)', 'Time to wait between failed download attempts, from 0 to 600 seconds.')
field('COLLECTION_MAX_ITEMS', 'mods', 'Collection expansion limit', 'Maximum items allowed while expanding Workshop collections, from 1 to 1000. Limits unexpectedly large collections.')
field('AUTOSAVE_INTERVAL', 'runtime', 'Autosave interval (minutes)', 'Send a save command at this interval. 0 disables scheduled autosaves. Saves update the world in place; they do not create backup archives.')
field('SHUTDOWN_MESSAGE', 'runtime', 'Shutdown announcement', 'Chat message sent to players when Docker requests a graceful container shutdown.')
field('SHUTDOWN_TIMEOUT', 'runtime', 'Graceful shutdown timeout (seconds)', 'How long to wait after requesting a save-and-exit before forced termination. Keep Docker’s stop_grace_period longer than this value plus shutdown overhead.')
field('LOG_LEVEL', 'runtime', 'Console verbosity', 'quiet reduces routine output; normal shows standard output; debug shows detailed output. Complete raw output remains in the persistent console log.')
field('CRASH_LOG_LINES', 'runtime', 'Crash replay lines', 'Number of raw console lines replayed when the game fails. 0 disables crash replay; debug already shows raw output.')
field('PRIORITY', 'runtime', 'Process priority', 'Server scheduling priority, from 0 (realtime) to 5 (idle). Lower values request higher priority; container permissions may limit this. Prefer the default unless diagnosing performance.')

for key, label in [
    ('SETFROZEN', 'Freeze time'), ('SETDAWN', 'Set time to dawn'),
    ('SETNOON', 'Set time to noon'), ('SETDUSK', 'Set time to dusk'),
    ('SETMIDNIGHT', 'Set time to midnight'), ('GODMODE', 'God mode'),
    ('WIND_STRENGTH', 'Wind strength'), ('RAIN_STRENGTH', 'Rain strength'),
    ('TIME_SPEED', 'Time speed'), ('RAIN_FROZEN', 'Freeze rain'),
    ('WIND_FROZEN', 'Freeze wind'), ('PLACEMENT_RANGE', 'Extended placement range'),
    ('SET_DIFFICULTY', 'Adjust difficulty'), ('BIOME_SPREAD', 'Biome spread'),
    ('SPAWN_RATE', 'Enemy spawn rate'),
]:
    field('JOURNEY_' + key, 'journey', label,
          f'Who can control {label.lower()} in a Journey world: 0 locked, 1 host only, 2 everyone.')
