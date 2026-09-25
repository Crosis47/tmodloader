"""Human-facing labels and help for every editable administration setting."""
GROUPS = [
    ('server', 'Server configuration', 'Player access, welcome message, and networking behavior.'),
    ('world', 'World configuration', 'Choose a world or configure creation of a new one. Creation settings do not modify an existing world.'),
    ('backup', 'Backup scheduling & retention', 'Choose when to create backup archives and how many to keep. Cold backups save the world, disconnect players, and restart the game after verification.'),
    ('autosave', 'Autosave', 'Save the live world without disconnecting players. Default: every 10 minutes. Autosaves update the world in place; backup archives use the separate schedule above.'),
    ('restart', 'Scheduled restarts', 'Warn players, save the world, and restart the game. Players disconnect; the dashboard stays available. Saved drafts are not applied and updates are not checked.'),
    ('mods', 'Mods & Workshop', 'Choose mods and control downloads. You can also stage selections in the Workshop browser.'),
    ('runtime', 'Runtime & logs', 'Shutdown behavior and the amount of console output.'),
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
field('BACKUP_MODE', 'backup', 'Backup schedule', 'Choose disabled, minutes, every X days, daily, weekly, or monthly. Interval mode preserves the existing backup interval. Cold backups disconnect players, save, archive, and restart the game.')
field('BACKUP_DAYS', 'backup', 'Back up every X days', 'Used in days mode. Each day is 24 hours. The timer resets on container startup, configuration apply, and after any backup attempt.')
field('BACKUP_WEEKDAY', 'backup', 'Backup weekday', 'Used for weekly backups at the selected backup time and timezone.')
field('BACKUP_MONTHDAY', 'backup', 'Backup day of month', 'Used for monthly backups. Choose 1 through 31; shorter months use their last day.')
field('BACKUP_TIME', 'backup', 'Backup time', 'Daily, weekly, and monthly backups use this 24-hour HH:MM time. Busy or unhealthy servers defer the backup.')
field('BACKUP_TIMEZONE', 'backup', 'Backup timezone', 'Use UTC or an IANA timezone such as America/New_York. Missing daylight-saving times shift forward; repeated times use their first occurrence.')
field('BACKUP_KEEP', 'backup', 'Backups to retain', 'Number of verified backup bundles to keep for this data directory. Cleanup runs only after a successful backup and restart; recovery originals are not pruned.')
field('BACKUP_MIN_FREE_MB', 'backup', 'Minimum free space (MiB)', 'Refuse a backup before stopping the game when /backups has less free space than this threshold. 1024 means 1 GiB. This is not an archive-size estimate; 0 disables the threshold.')
field('MODS', 'mods', 'Selected Workshop entries', 'Comma-separated Workshop mod IDs or collection:ID entries. Removing an entry disables it on managed startup but keeps cached downloads.')
field('MOD_OFFLINE_POLICY', 'mods', 'Steam offline policy', 'use-cache allows startup with available cached mods when Steam cannot be reached. strict fails if required update/download checks fail.')
field('DOWNLOAD_RETRIES', 'mods', 'Download attempts', 'Maximum attempts for transient Steam Workshop download failures, from 1 to 20.')
field('DOWNLOAD_RETRY_DELAY', 'mods', 'Retry delay (seconds)', 'Time to wait between failed download attempts, from 0 to 600 seconds.')
field('COLLECTION_MAX_ITEMS', 'mods', 'Collection expansion limit', 'Maximum items allowed while expanding Workshop collections, from 1 to 1000. Limits unexpectedly large collections.')
field('AUTOSAVE_INTERVAL', 'autosave', 'Autosave interval (minutes)', 'Save the live world every N minutes (default: 10). 0 disables scheduled autosaves. Saves update the world in place without disconnecting players; they do not create backup archives. Save the draft, then Apply & Restart to activate a changed interval. The timer resets when the game starts.')
field('SHUTDOWN_MESSAGE', 'runtime', 'Shutdown announcement', 'Chat message sent to players when Docker requests a graceful container shutdown.')
field('RESTART_MODE', 'restart', 'Restart schedule', 'Choose disabled (default), minutes, every X days, daily, weekly, or monthly. Save the draft and apply to activate changes. Busy or unhealthy servers defer the restart until ready.')
field('RESTART_INTERVAL', 'restart', 'Restart interval (minutes)', 'Used in interval mode only. 0 disables interval restarts; 1440 is approximately every 24 hours. The timer resets whenever the game starts, including after backups or applying settings.')
field('RESTART_DAYS', 'restart', 'Restart every X days', 'Used in every-X-days mode. Enter 1 through 3650; each day is exactly 24 hours. The timer resets whenever the game starts, including after backups or applying settings. It does not use the calendar time or timezone.')
field('RESTART_WEEKDAY', 'restart', 'Restart weekday', 'Used in weekly mode. Choose the weekday on which the restart warning begins, at the selected time in the selected timezone.')
field('RESTART_MONTHDAY', 'restart', 'Restart day of month', 'Used in monthly mode. Choose 1 through 31. If a month has fewer days, use its last day: 31 becomes February 28 or 29, for example.')
field('RESTART_TIME', 'restart', 'Restart time', 'Used for daily, weekly, and monthly schedules. Enter HH:MM in 24-hour format, such as 04:00, in the restart timezone below. The warning starts at this time; the game stops after the warning delay.')
field('RESTART_TIMEZONE', 'restart', 'Restart timezone', 'Used for daily, weekly, and monthly schedules. Use UTC or an IANA timezone such as America/New_York. A skipped daylight-saving time shifts forward by the clock-change gap; a repeated time runs at its first occurrence only.')
field('RESTART_DELAY', 'restart', 'Restart warning delay (seconds)', 'Wait after the scheduled restart announcement before saving and stopping the game. Default: 60; 0 restarts immediately. This delay is separate from the Docker shutdown warning delay.')
field('RESTART_MESSAGE', 'restart', 'Restart chat announcement', 'Chat message sent when a scheduled restart becomes due, before the warning delay. Leave empty to omit the announcement. Players will still disconnect when the game restarts.')
field('RESTART_COUNTDOWN', 'restart', 'Restart countdown warnings (seconds)', 'Comma-separated remaining times, such as 300,60,10. Warnings longer than the restart delay are skipped. Leave empty to disable countdown chat messages; the initial announcement is controlled separately.')
field('LOG_RETENTION_DAYS', 'runtime', 'Console history retention (days)', 'Remove archived console logs older than this many days. Default: 30; 0 disables age-based cleanup. The current and previous console logs and tModLoader own logs are kept.')
field('LOG_HISTORY_MAX_MB', 'runtime', 'Console history size limit (MiB)', 'Remove oldest archived console logs until history fits this budget. Default: 512; 0 disables the size limit. Current and previous console logs are separate from this budget.')
field('LOG_ROTATE_MB', 'runtime', 'Console log rotation size (MiB)', 'Rotate the current console log at this size so one long server session cannot grow it indefinitely. Default: 64. Cleanup runs at startup, rotation, and periodically while output is received.')
field('AUTOSAVE_MESSAGE', 'autosave', 'Autosave chat announcement', 'Chat message sent before each scheduled save. Leave empty to save silently. The autosave interval controls the schedule; 0 disables scheduled saves. Save the draft and apply to activate changes.')
field('SHUTDOWN_DELAY', 'runtime', 'Shutdown warning delay (seconds)', 'Wait after the shutdown announcement before requesting save-and-exit when Docker stops the container. Default: 3; 0 skips the delay. Keep Docker stop_grace_period longer than this delay plus the graceful shutdown timeout and shutdown overhead. Dashboard restarts and backups use their own stop flow.')
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
