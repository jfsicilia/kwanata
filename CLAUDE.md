# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KWanata is a bridge between KDE Plasma's window focus events and the [Kanata](https://github.com/jtroo/kanata) keyboard remapper. It switches Kanata layers and activates virtual keys based on the currently focused application.

## Architecture

The system has two components connected via DBus:

```
KWin → main.js (KWin Script) --DBus--> focus_to_kanata.py --TCP--> Kanata
```

1. **`contents/code/main.js`** — KWin script (JavaScript) that listens for `windowActivated` and `captionChanged` signals. Sends window properties (pid, resourceName, resourceClass, caption) over DBus to the Python service. Supports both KDE 5 (`clientActivated`) and KDE 6 (`windowActivated`).

2. **`server/focus_to_kanata.py`** — Python DBus service that receives window info, matches it against rules in `config.toml`, and sends layer/virtual-key commands to Kanata via a persistent TCP connection (default port 10101).

3. **`server/config.toml`** — Ordered list of `[[app]]` rules. First match wins. Each rule can specify regex patterns for `name`, `class`, `caption` (omitted fields match everything), plus a `layer` and/or `virtual_keys` array to activate.

The DBus interface is `juan.sicilia.KWanata` with two methods: `notifyFocusChanged` and `notifyCaptionChanged`.

## Running

```bash
# Run the Python service (requires Kanata running with -p 10101)
python3 server/focus_to_kanata.py --port 10101 -c server/config.toml

# With debug logging
python3 server/focus_to_kanata.py --port 10101 -c server/config.toml -v

# As a systemd user service
systemctl --user start kwanata.service
```

## System Dependencies

Python 3.11+ required (uses `tomllib`). System packages (not pip):

- **Fedora:** `python3-gobject`, `python3-dbus`
- **Ubuntu:** `python3-gi`, `python3-dbus`

These provide `gi.repository.GLib` and `pydbus`.

## Key Classes in `focus_to_kanata.py`

- **`KanataClient`** — TCP client that sends JSON commands to Kanata (`ChangeLayer`, `ActOnFakeKey`, `RequestCurrentLayerName`, etc.)
- **`AppMatcher`** — Loads `config.toml`, pre-compiles regex patterns, returns `(layer, virtual_keys)` for first matching rule
- **`KWanataService`** — DBus service; tracks last layer/virtual-keys to avoid redundant Kanata commands
- **`utils`** — Static helpers for port validation, DBus message parsing, fake key validation

## Debugging

```bash
# Tail KWin script logs (print/console.log output)
journalctl --user -u plasma-kwin_wayland.service -f -n 100

# Monitor DBus messages to KWanata
dbus-monitor "destination=juan.sicilia.KWanata"

# Query window info interactively
qdbus6 org.kde.KWin /KWin org.kde.KWin.queryWindowInfo
```

## No Test Suite

There are no automated tests. Verification is manual via DBus monitoring and journal logs.
