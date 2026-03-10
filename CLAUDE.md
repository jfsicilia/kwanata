# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KWanata is a KDE Plasma companion for [Kanata](https://github.com/jtroo/kanata). It provides two features: (1) a focus-to-Kanata bridge that switches layers and virtual keys based on the focused app, and (2) a run-or-raise manager that launches or raises app windows via Kanata push messages.

## Architecture

```
KWin → kwin_window_notifier.js (injected at runtime) --DBus--> kwanata.py --TCP--> Kanata
```

1. **`kwin_window_notifier.js`** — KWin script (JavaScript) dynamically injected into KWin at runtime by `kwanata.py` via the KWin Scripting DBus API. Listens for `windowActivated` and `captionChanged` signals. Sends window properties (pid, resourceName, resourceClass, caption) over DBus to the Python service. Supports both KDE 5 (`clientActivated`) and KDE 6 (`windowActivated`).

2. **`kwin_app_raiser.js`** — KWin script template for run-or-raise. Read once at startup and cached in memory. On each invocation, `__CLASS__` and `__CAPTION__` placeholders are replaced and the script is injected as a temporary KWin script to raise/cycle matching windows. Reports success/failure back via DBus.

3. **`kwanata.py`** — Python DBus service that injects the window notifier script on startup, receives window info, matches it against `[[app]]` rules in `config.toml`, and sends layer/virtual-key commands to Kanata via a persistent TCP connection (default port 10101). Also handles run-or-raise via `[[run_or_raise]]` rules triggered by Kanata push messages. On shutdown it unloads the injected script from KWin.

4. **`config.toml`** — Contains `[[app]]` rules (focus-to-Kanata, first match wins) and `[[run_or_raise]]` rules (app launching/raising).

The DBus interface is `com.pyroflexia.KWanata` with methods: `notifyFocusChanged`, `notifyCaptionChanged`, `notifyRaiseResult`, and `debug`.

## Running

```bash
# Run the Python service (requires Kanata running with -p 10101)
python3 kwanata.py --port 10101 -c config.toml

# With debug logging
python3 kwanata.py --port 10101 -c config.toml -v

# As a systemd user service
systemctl --user start kwanata.service
```

## System Dependencies

Python 3.11+ required (uses `tomllib`). System packages (not pip):

- **Fedora:** `python3-gobject`, `python3-dbus`
- **Ubuntu:** `python3-gi`, `python3-dbus`

These provide `gi.repository.GLib` and `pydbus`.

## Key Classes in `kwanata.py`

- **`KWinScriptInjector`** — Injects/unloads `kwin_window_notifier.js` into KWin at runtime via the `org.kde.KWin /Scripting` DBus API
- **`KanataClient`** — TCP client that sends JSON commands to Kanata (`ChangeLayer`, `ActOnFakeKey`, `RequestCurrentLayerName`, etc.). Routes incoming push messages to `AppRunner` for run-or-raise
- **`AppMatcher`** — Loads `[[app]]` rules from `config.toml`, pre-compiles regex patterns, returns `(layer, virtual_keys)` for first matching rule
- **`AppRunner`** — Handles `[[run_or_raise]]` rules. Loads `kwin_app_raiser.js` template at startup, caches it with DBus constants resolved. On each trigger, substitutes `__CLASS__`/`__CAPTION__` and injects a temporary KWin script to raise or cycle windows; falls back to launching if no window found
- **`KWanataService`** — DBus service; tracks last layer/virtual-keys to avoid redundant Kanata commands; routes raise results to `AppRunner`
- **`utils`** — Static helpers for port validation, DBus message parsing, fake key validation

## Debugging

```bash
# Tail KWin script logs (print/console.log output)
journalctl --user -u plasma-kwin_wayland.service -f -n 100

# Monitor DBus messages to KWanata
dbus-monitor "destination=com.pyroflexia.KWanata"

# Query window info interactively
qdbus6 org.kde.KWin /KWin org.kde.KWin.queryWindowInfo
```

## No Test Suite

There are no automated tests. Verification is manual via DBus monitoring and journal logs.
