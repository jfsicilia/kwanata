# KWanata

A KDE Plasma companion for the [Kanata](https://github.com/jtroo/kanata) keyboard remapper. KWanata provides two features:

- **Focus-to-Kanata bridge** -- Automatically switches Kanata layers and activates virtual keys based on the currently focused application.
- **Run-or-raise manager** -- Launches apps or raises their windows via keyboard shortcuts triggered through Kanata push messages.

## How it works

```
KWin --> kwin_window_notifier.js (injected at runtime) --DBus--> kwanata.py --TCP--> Kanata
```

On startup, `kwanata.py` dynamically injects a JavaScript file into KWin via the KWin Scripting DBus API and opens a persistent TCP connection to Kanata. From there it handles two flows:

### Focus-to-Kanata

1. The injected KWin script listens for `windowActivated` and `captionChanged` signals and sends window properties (pid, name, class, caption) over DBus.
2. KWanata matches the window info against `[[app]]` rules in `config.toml` (first match wins) and sends the corresponding layer/virtual-key commands to Kanata.

### Run-or-raise

1. Kanata sends a `push-msg "APP:<name>"` command over TCP when a keyboard shortcut is pressed (See kanata `push-msg` function).
2. KWanata looks up the name in the `[[run_or_raise]]` rules in `config.toml`.
3. If a matching window is found (by class/caption), it is raised. If the app is already focused and there are multiple matching windows, it cycles through them.
4. If no matching window is found, the app is launched via the configured command.

## Requirements

- KDE Plasma 5 or 6 (KWin)
- [Kanata](https://github.com/jtroo/kanata) running with TCP server enabled (default port `-p 10101`)
- Python 3.11+ (uses `tomllib`)
- System packages (not pip):

```bash
# Fedora
sudo dnf install python3-gobject python3-dbus
```

```bash
# Ubuntu
sudo apt install python3-gi python3-dbus
```

## Quick start

1. Start Kanata with the TCP server enabled:

   ```bash
   kanata -p 10101
   ```

2. Run KWanata:

   ```bash
   python3 kwanata.py --port 10101 -c config.toml
   ```

   Use `-v` for debug logging.

3. Switch between windows -- Kanata layers and virtual keys will change according to your `[[app]]` rules.

4. Press keyboard shortcuts bound to Kanata `(push-msg "APP:<name>")` action -- KWanata will raise or launch the corresponding app from your `[[run_or_raise]]` rules.

5. Press `Ctrl+C` to stop. The injected KWin script is automatically unloaded on shutdown.

## Configuration

All rules are defined in `config.toml`.

### Focus-to-Kanata rules (`[[app]]`)

An ordered list of `[[app]]` entries. First match wins.

```toml
[[app]]
name = "chrome"                    # regex matched against window resource name
virtual_keys = ["vk_chrome"]

[[app]]
name = "foot"
caption = "^tmux.*(N|n)vim$"       # regex matched against window title
virtual_keys = ["vk_nvim", "vk_tmux"]

[[app]]
name = "foot"
caption = "^Zellij"
virtual_keys = ["vk_zellij"]

[[app]]
name = "foot|konsole"
virtual_keys = ["vk_foot"]
```

Each rule can specify:

| Field          | Type     | Description                                  |
| -------------- | -------- | -------------------------------------------- |
| `name`         | regex    | Window resource name (e.g. `chrome`, `foot`) |
| `class`        | regex    | Window resource class                        |
| `caption`      | regex    | Window title / caption                       |
| `layer`        | string   | Kanata layer to activate                     |
| `virtual_keys` | string[] | Kanata virtual keys to press                 |

All fields are optional. Omitted fields match everything (wildcard). At least one of `layer` or `virtual_keys` should be specified for a rule to have an effect.

### Run-or-raise rules (`[[run_or_raise]]`)

Each entry maps a name (used in Kanata's `(push-msg "APP:<name>")`) to a window-matching rule and a launch command.

```toml
[[run_or_raise]]
name = "chrome"
class = "google-chrome"
command = "google-chrome-stable"
process = "chrome"

[[run_or_raise]]
name = "terminal"
class = "foot"
caption = "^((?!(nvim|claude code)).)*$"
command = "foot"

[[run_or_raise]]
name = "nvim"
caption = "(Nvim|nvim — Konsole)$"
command = "nvim"
process = "nvim$"
```

Each rule can specify:

| Field     | Type   | Description                                                         |
| --------- | ------ | ------------------------------------------------------------------- |
| `name`    | string | **Required.** Identifier used in the Kanata `push-msg`              |
| `class`   | regex  | Window resource class to match when raising                         |
| `caption` | regex  | Window title to match when raising                                  |
| `command` | string | Shell command to launch the app (defaults to `name`)                |
| `process` | regex  | Process name to check if the app is running (defaults to `command`) |

At least `class` or `caption` should be defined so KWanata can find the window to raise.

### Live reload

Kanata can trigger a config reload by sending `push-msg "RELOAD:"`. KWanata will re-read `config.toml` and apply the new rules without restarting.

## CLI options

```
usage: kwanata.py [-h] [--host HOST] [--port PORT]
                  [-l DEFAULT_LAYER] [-c CONFIG]
                  [--kwin-script KWIN_SCRIPT]
                  [--kwin-raise-script KWIN_RAISE_SCRIPT] [-v]

  --host HOST             Kanata host (default: 127.0.0.1)
  --port PORT             Kanata port (default: 10101)
  -l, --default_layer     Fallback layer when no rule matches (default: default_layer)
  -c, --config            Path to TOML rules file (default: config.toml)
  --kwin-script           Path to KWin window notifier JS file (default: kwin_window_notifier.js)
  --kwin-raise-script     Path to KWin raise JS template (default: kwin_app_raiser.js)
  -v, --verbose           Enable debug logging
```

## Running as a systemd service

A unit file is provided at `kwanata.service`. Edit the paths to match your installation, then:

```bash
# Copy or symlink the unit file
cp kwanata.service ~/.config/systemd/user/kwanata.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable kwanata.service
systemctl --user start kwanata.service

# Check logs
journalctl --user -u kwanata.service -f
```

The service is configured to start after `kanata.service` and stop when Kanata stops (`PartOf=kanata.service`).

## Debugging

```bash
# Monitor DBus messages to KWanata
dbus-monitor "destination=com.pyroflexia.KWanata"

# Tail KWin script logs
journalctl --user -u plasma-kwin_wayland.service -f -n 100

# Query window info interactively
qdbus6 org.kde.KWin /KWin org.kde.KWin.queryWindowInfo
```

## Project structure

```
kwanata.py                  # Python DBus service (main entry point)
kwin_window_notifier.js     # KWin script: forwards focus/caption events over DBus
kwin_app_raiser.js          # KWin script template: raises/cycles windows for run-or-raise
config.toml                 # App-matching and run-or-raise rules
kwanata.service             # systemd user unit file
```

## License

MIT

## Inspiration and acknowledgment

This tool could not be possible without these other tools:

- [kanata](https://github.com/jtroo/kanata)
- [FocusNotifier](https://github.com/c-massie/FocusNotifier)
- [hyprkan](https://github.com/haithium/hyprkan)
- [jumpkwapp](https://github.com/jasalt/jumpkwapp)
- [ww-run-or-raise](https://github.com/academo/ww-run-raise)
- [kdotools](https://github.com/tvidal-net/kdotool)
