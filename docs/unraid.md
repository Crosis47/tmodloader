# Unraid deployment

The template was tested by the maintainer on Unraid 7.3.2 in a TrueNAS SCALE 25.10.7 VM. Community Applications submission is still pending; this is not yet a catalog listing.

## Template and first run

The template is `templates/tmodloader-crosis47.xml`. For a manual test, copy it to
`/boot/config/plugins/dockerMan/templates-user/my-tmodloader-crosis47.xml` on the
test Unraid host, then select it in Docker > Add Container. Review the generated
container configuration before starting.

1. Use dedicated empty data and backup folders. The defaults are under
   `/mnt/user/appdata/tmodloader-crosis47/`. Do not reuse another container's data.
2. Choose available host ports. Container ports stay at 7777 and 8080; changing
   the host mapping does not require changing the internal listener variables.
3. Leave optional game settings at their defaults when using the dashboard.
   Set the player password in the dashboard after setup; it is separate from
   the administrator credential. The template defaults to no player password.
4. Start the container and read its logs for the one-time setup code.
5. Open WebUI, enter the code, and create the administrator credential. The game
   waits for this step; first-run runtime installation needs internet access.
6. Manage worlds, mods, passwords, and schedules in the dashboard. Saved dashboard
   values override matching environment defaults after the first save.

Startup repairs dedicated volume ownership to UID/GID 1000:1000, then runs the
services without root privileges. Do not add PUID/PGID variables or override the
container user; this image does not implement the usual Unraid 99:100 convention.
Set Settings > Docker > Docker Stop Timeout to 120 seconds. The template also requests a 120-second container stop timeout. This allows the server to save and exit; increase both if a larger mod pack needs more time.

Use HTTP only on a trusted LAN. For a hostname set TMOD_WEB_ORIGIN to the exact
browser origin. For an HTTPS reverse proxy also configure TMOD_WEB_TRUSTED_PROXY
and the headers documented in the project wiki. Do not directly publish the HTTP
dashboard to the internet.

## Controls in the Unraid form

The main form contains only the required ports, storage paths and Enable
Dashboard. All optional controls are under Show more settings, with their
existing defaults preserved.

Template order places all settings that cannot be adjusted in the dashboard
before Enable Dashboard: ports and storage, settings ownership/custom config,
dashboard access and secret files, then runtime installation and updates.
Dashboard-managed controls follow it, grouped by server access, world generation,
Workshop mods, autosave, backups, scheduled restarts, runtime/logging and Journey
permissions. Unraid controls how advanced fields are displayed when Show more
settings is expanded.

With Enable Dashboard set to 1 and Manage game settings with left at web, there
is no need to configure the game settings below the toggle. Leave their defaults
and manage them in the dashboard. The template exposes 76 environment controls.

The overview includes labeled wiki URLs for setup, settings ownership,
networking, storage/updates, worlds, mods, backups, schedules, defaults and
troubleshooting. Each individual setting also includes a Wiki URL pointing to
its relevant documentation section. In the tested Unraid form, plain-text URLs
in Overview are clickable, but URLs in individual setting descriptions are not;
copy those URLs into a browser. Keep URLs as plain text; explicit link markup
was stripped during testing.

Literal newlines, XML newline entities, and the twice-escaped HTML break found
in published ich777 templates did not produce visible line breaks in the tested
Unraid form. Field descriptions separate the inline Wiki URL with two vertical bars (`||`) and
four nonbreaking spaces on each side (`&#160;` entities in the XML). The spacing
and double-bar separator were confirmed by the maintainer in Unraid.
This does not force the URL onto a separate line.

**Manage game settings with** selects `web` (default) or `env`:

- `web`: Unraid game values seed settings not yet saved in the dashboard.
  Existing dashboard values continue to win when the container is recreated.
- `env`: Unraid fields control game settings; dashboard configuration editing
  is disabled. Populate the intended world, mods and password before switching.
- Disabling the dashboard always uses environment-managed game settings.

Dropdowns expose supported numeric values where the game expects them. World
size: 1 small, 2 medium, 3 large. Difficulty: 0 Classic, 1 Expert, 2 Master,
3 Journey. Journey permissions: 0 locked, 1 host, 2 everyone.

Host port mappings remain the port controls; internal listeners stay at 7777 and
8080. TMOD_HEALTH_START_PERIOD is a Compose substitution, not a container setting;
use Docker Extra Parameters `--health-start-period` if an override is necessary.
The image already supplies a 60-second health-check start period.

Optional *_FILE entries require separately added read-only file mappings; setting
an environment path does not mount a host file. Custom server configuration also
requires a file mapping to `/terraria-server/customconfig.txt` and env mode or a
disabled dashboard. Leave these options empty/off unless deliberately configured.
Masked password/token fields conceal input visually; Docker and saved Unraid
configuration still contain their values.

The expanded controls passed local default/structure checks, and the maintainer
confirmed the final form layout and separators in Unraid. The runtime checks
below used the smaller template; expanded env-mode operation remains untested.

## Validation

On 2026-10-08, the maintainer confirmed these checks passed on Unraid 7.3.2,
virtualized on TrueNAS SCALE 25.10.7 with 4 vCPUs, 8 GiB RAM, a dedicated
64 GiB virtual disk, and a PNY USB boot device with trial activation:

- Template import and initial container installation.
- Dashboard administrator setup and game startup.
- Restart through Unraid, retained administrator access, world and settings.
- Connection from a tModLoader client.
- Manual backup creation, archive verification, restoration and client reconnection.

These are user-reported interactive results. Screenshots confirmed the Unraid
version, trial activation, device assignment and template field rendering.
The exact pulled image digest, installed game version, shutdown timing and volume
ownership output were not captured. Local XML parsing and deployment-field
checks passed separately.

Additional coverage remains for non-default host ports, Workshop mod downloads,
image update/recreation persistence, and reverse-proxy access. Do not interpret
the restart check as proof of container replacement or an image upgrade.

### Reproducing the test VM

Use an isolated guest with the resources above and disposable worlds. Create a
single-device cache pool on the virtual data disk, format it, and start the pool
before enabling Docker. The test used a 20 GB Docker vDisk and the default
`/mnt/user/system/docker/docker.img` and `/mnt/user/appdata/` paths.

Pass through a dedicated USB device with a unique hardware identifier for Unraid
boot and licensing. Unraid does not support TPM licensing inside a VM. Use a
valid trial or separate license. Keep VM autostart off during testing.

TrueNAS 25.10 browser consoles use a password-protected SPICE display; VNC does
not support browser access. If UEFI initially enters its shell, `connect -r`
and `map -r` can rescan devices; launch `fs0:\EFI\boot\bootx64.efi` only if FS0
is the Unraid USB filesystem. Automatic boot after a full VM restart still needs
to be checked separately.

## Community Applications submission

The root `ca_profile.xml` describes this project's repository. The existing
`LICENSE.md` contains the MIT license; confirm the portal recognizes that filename
(the official starter uses `LICENSE`). The template reuses the same hosted PNG
icon as the TrueNAS submission:
https://media.sys.truenas.net/apps/tmodloader/icons/icon.png
Canonical raw URLs point to master and become available only after merging.

Publish the template, then run
Validate and Scan in the submission portal and resolve its findings before review.
Portal validation and catalog submission remain pending.

References:
- https://ca.unraid.net/submit/help/builders
- https://ca.unraid.net/submit/help/xml-field-reference
- https://docs.unraid.net/unraid-os/using-unraid-to/create-virtual-machines/unraid-as-a-vm/
- https://docs.unraid.net/unraid-os/troubleshooting/tpm-licensing-faq/
- https://forums.unraid.net/topic/199431-unraid-install-onto-microsoft-hyper-v/
