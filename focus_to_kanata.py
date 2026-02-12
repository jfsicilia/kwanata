#!/usr/bin/python3
"""
DBus service that bridges KWin window focus events to Kanata.

Receives window info (pid, name, class, caption) from the KWin script
(main.js) via DBus, matches it against rules in config.toml, and sends
layer/virtual-key commands to Kanata over a persistent TCP connection.
"""

import argparse
import json
import logging
import os
import re
import socket
import sys
from typing import Any, Dict, NoReturn, Optional, Tuple, Union

import tomllib
from gi.repository import GLib
from pydbus import SessionBus

# Command line defaults.
DEFAULT_CONFIG_FILE = "config.toml"
DEFAULT_KANATA_HOST = "127.0.0.1"
DEFAULT_KANATA_PORT = 10101
DEFAULT_KANATA_LAYER = "default_layer"

# DBus constants for the dynamically-injected KWin script.
DBUS_INTERFACE = "com.pyroflexia.KWanata"
DBUS_PATH = "/com/pyroflexia/KWanata"

# Default path to the KWin script for dynamic injection.
DEFAULT_KWIN_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "kwin_script.js"
)

# The dbus message that will be received has several lines with the format:
#    field1: value
#    field2: value
#    ...
# (see FIELD_XXXX constants for the possible fields)
DBUS_MSG_FIELD_RE = re.compile(r"^\s*(\w+):\s*(.*)$")

# Used as default for omitted rule fields — matches anything, acting as a wildcard.
MATCH_ALL_RE = re.compile(r".*")

# Toml file sections and fields. Also used for dbus messages, except for FIELD_VK
# that appears in the toml as the result of a name/class/caption match.
SECTION_APP = "app"
FIELD_NAME = "name"
FIELD_CLASS = "class"
FIELD_CAPTION = "caption"
FIELD_VK = "virtual_keys"
FIELD_LAYER = "layer"

# Possible values for kanata's virtual key actions.
KANATA_VIRTUAL_KEY_ACTIONS = {"Press", "Release", "Tap", "Toggle"}

log = logging.getLogger()


# ----------------------------
# utils
# ----------------------------
class utils:
    @staticmethod
    def fatal(message: str, *args: object) -> NoReturn:
        """Log an error message and exit the program."""
        log.error(message, *args)
        sys.exit(1)

    @staticmethod
    def is_blank(s: str) -> bool:
        """Check if a string is empty/whitespace only."""
        return not s.strip()

    @staticmethod
    def validate_port(port: Union[int, str]) -> tuple[str, int]:
        """Validate a port number or an IP:PORT combination and return (host, port)."""
        port_str = str(port)
        if utils._is_valid_port(port_str):
            return (DEFAULT_KANATA_HOST, int(port_str))  # default host localhost
        if utils._is_valid_ip_port(port_str):
            host, port_part = port_str.split(":")
            return (host, int(port_part))

        utils.fatal(
            "Invalid port '%s': Please specify either a port number (e.g., 10000) or "
            "an IP address with port (e.g., 127.0.0.1:10000).",
            port,
        )

    @staticmethod
    def _is_valid_port(port: Union[int, str]) -> bool:
        if isinstance(port, int):
            return 0 < port <= 65535
        if isinstance(port, str) and port.isdigit():
            val = int(port)
            return 0 < val <= 65535
        return False

    @staticmethod
    def _is_valid_ip_port(value: str) -> bool:
        pattern = r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})"
        match = re.fullmatch(pattern, value)
        if not match:
            return False

        ip, port_str = match.groups()
        port = int(port_str)

        if not utils._is_valid_port(port):
            return False

        if ip == "localhost":
            return True

        octets = ip.split(".")
        return all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)

    @staticmethod
    def validate_fake_key(
        fake_key: tuple[str, str], rule_no: Optional[int]
    ) -> tuple[str, str]:
        """Validates if it's a valid virtual key / action."""
        name, action = fake_key
        if utils.is_blank(name):
            utils.fatal("Fake key name must not be blank")

        action = action.capitalize()
        if action not in KANATA_VIRTUAL_KEY_ACTIONS:
            actions = ", ".join(KANATA_VIRTUAL_KEY_ACTIONS)
            if rule_no:
                msg = f"Invalid config: rule #{rule_no} '{action}' must be one of: {actions}"
            else:
                msg = f"Invalid action '{action}'. Must be one of: {actions}"
            utils.fatal(msg)

        return name, action

    @staticmethod
    def parse_dbus_msg(text: str) -> dict[str, str]:
        """
        It returns a dictionary with this keys: pid, name, class, caption
        """
        result = {}

        for line in text.splitlines():
            m = DBUS_MSG_FIELD_RE.match(line)
            if not m:
                continue
            k, v = m.groups()
            result[k.strip()] = v.strip()

        return result


# ----------------------------
# KWinScriptInjector
# ----------------------------
class KWinScriptInjector:
    """Injects a KWin script at runtime via the KWin Scripting DBus API.

    Uses org.kde.KWin /Scripting to loadScript/unloadScript, avoiding the
    need for manual kpackagetool6 installation.
    """

    KWIN_BUS = "org.kde.KWin"
    SCRIPTING_PATH = "/Scripting"

    def __init__(self, bus):
        self._bus = bus
        self._script_path = None

    def inject(self, filepath):
        """Load and run a KWin script file. Returns True on success."""
        abs_path = os.path.abspath(filepath)
        if not os.path.isfile(abs_path):
            log.warning("KWin script not found: %s — skipping injection", abs_path)
            return False

        try:
            scripting = self._bus.get(self.KWIN_BUS, self.SCRIPTING_PATH)
        except Exception as e:
            log.warning("Cannot reach KWin Scripting DBus: %s — skipping injection", e)
            return False

        script_id = scripting.loadScript(abs_path)

        if script_id == -1:
            log.info("KWin script '%s' already loaded, reloading...", abs_path)
            scripting.unloadScript(abs_path)
            script_id = scripting.loadScript(abs_path)

        if script_id == -1:
            log.error("Failed to load KWin script from %s", abs_path)
            return False

        script_obj = self._bus.get(self.KWIN_BUS, f"/Scripting/Script{script_id}")
        script_obj.run()
        self._script_path = abs_path
        log.info("Injected KWin script (ID: %d) from %s", script_id, abs_path)
        return True

    def remove(self):
        """Unload the injected KWin script."""
        if not self._script_path:
            return False
        try:
            scripting = self._bus.get(self.KWIN_BUS, self.SCRIPTING_PATH)
            result = scripting.unloadScript(self._script_path)
            log.info("Unloaded KWin script '%s': %s", self._script_path, result)
            self._script_path = None
            return result
        except Exception as e:
            log.warning("Failed to unload KWin script: %s", e)
            return False


# ----------------------------
# KanataClient
# ----------------------------
class KanataClient:
    """TCP client for communicating with kanata."""

    def __init__(self, addr: Tuple[str, int]):
        self.addr = addr
        self._client: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._buffer = ""
        self._connected = False

    def _connect(self):
        """Connect to Kanata's TCP server. Lazy-called on first send()."""
        log.debug("Connecting to %s:%s", *self.addr)
        try:
            self._client.connect(self.addr)
            # Disable Nagle's algorithm for low-latency command delivery.
            self._client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._client.settimeout(0.5)
            self._connected = True

            # Kanata errors if a client connects and disconnects without sending
            # anything, so issue a harmless query to satisfy that requirement.
            self.get_current_layer_name()

        except socket.error as e:
            ip, port = self.addr
            utils.fatal(
                "Kanata connection error: %s — make sure kanata is running with the -p option "
                "(e.g. `-p %s` or `-p %s:%s`).",
                e,
                port,
                ip,
                port,
            )

    def close(self):
        """Close the client socket connection gracefully."""
        if self._client:
            log.warning("Closing client socket to %s", self.addr)
            try:
                self._client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # Socket may already be closed or unconnected
            self._client.close()

    def _flush_buffer(self):
        """
        Flushes any stale complete messages from the socket buffer before
        sending a new command.
        """
        self._client.settimeout(0.01)
        try:
            while True:
                chunk = self._client.recv(1024)
                if not chunk:
                    break
                self._buffer += chunk.decode("utf-8")
        except socket.timeout:
            pass

        if "\n" in self._buffer:
            parts = self._buffer.split("\n")
            self._buffer = parts[-1]  # Keep only last incomplete piece

    def send(self, cmd: dict) -> Optional[str]:
        """
        Send a JSON command to Kanata and return the first complete response line.

        Kanata uses a newline-delimited JSON protocol: each message (request or
        response) is a single JSON object followed by '\n'. Asynchronous events
        (e.g. layer changes from other sources) may arrive between our request
        and its response, so _flush_buffer() drains stale data first.
        """
        if not self._connected:
            self._connect()
        logging.debug("Sending command: %s", cmd)
        msg = json.dumps(cmd) + "\n"

        self._flush_buffer()  # Discard old responses
        self._client.sendall(msg.encode("utf-8"))
        self._client.settimeout(0.05)

        # Read until we get a complete line (ending in '\n').
        try:
            while "\n" not in self._buffer:
                chunk = self._client.recv(1024)
                if not chunk:
                    break
                self._buffer += chunk.decode("utf-8")
        except socket.timeout:
            return None

        lines = self._buffer.split("\n")
        self._buffer = lines[-1]  # Save incomplete part for next call

        for line in lines[:-1]:
            if line.strip():
                logging.debug("Received response line: %s", line.strip())
                return line.strip()

        return None

    def get_current_layer_name(self) -> str:
        data = self._parse_json_response(self.send({"RequestCurrentLayerName": {}}))
        return data.get("CurrentLayerName", {}).get("name")

    def get_current_layer_info(self) -> Optional[Dict[str, str]]:
        data = self._parse_json_response(self.send({"RequestCurrentLayerInfo": {}}))
        return data.get("CurrentLayerInfo")

    def get_layer_names(self) -> list[str]:
        data = self._parse_json_response(self.send({"RequestLayerNames": {}}))
        return data.get("LayerNames", {}).get("names")

    def change_layer(self, layer: str) -> bool:
        if layer == self.get_current_layer_name():
            log.debug("Layer '%s' is already active.", layer)
            return False
        self._parse_json_response(self.send({"ChangeLayer": {"new": layer}}))
        log.info("Switched to layer '%s'", layer)
        return True

    def act_on_fake_key(self, fake_key: tuple[str, str]) -> None:
        name, action = utils.validate_fake_key(fake_key, rule_no=None)
        self._parse_json_response(
            self.send({"ActOnFakeKey": {"name": name, "action": action}})
        )

    def set_mouse(self, pos: tuple[int, int]) -> None:
        """
        Sends a SetMouse command to Kanata.

        ⚠️ This command is not supported on Linux as of Kanata v1.8.1.
        This method exists as a placeholder for future support.
        """
        x, y = pos
        self._parse_json_response(self.send({"SetMouse": {"x": x, "y": y}}))

    def _parse_json_response(self, response: Optional[str]) -> Dict[str, Any]:
        if response:
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                return {}
        return {}


# ----------------
# AppMatcher class
# ----------------
class AppMatcher:
    """Matches apps rules with incoming dbus msg"""

    def __init__(self, filepath):
        self._apps_rules = []
        self.load_app_rules(filepath)

    def load_app_rules(self, filepath):
        """Load and pre-compile regex rules from a TOML file."""
        try:
            with open(filepath, "rb") as f:
                data = tomllib.load(f)
                for entry in data.get(SECTION_APP, []):
                    # Pre-compiling regex for better performance during matching
                    rule = {
                        FIELD_NAME: re.compile(entry[FIELD_NAME])
                        if FIELD_NAME in entry
                        else MATCH_ALL_RE,
                        FIELD_CLASS: re.compile(entry[FIELD_CLASS])
                        if FIELD_CLASS in entry
                        else MATCH_ALL_RE,
                        FIELD_CAPTION: re.compile(entry[FIELD_CAPTION])
                        if FIELD_CAPTION in entry
                        else MATCH_ALL_RE,
                        FIELD_VK: entry.get(FIELD_VK, []),
                        FIELD_LAYER: entry.get(FIELD_LAYER),
                    }
                    self._apps_rules.append(rule)
                    log.debug(f"Loaded rule: {rule}")
            log.info(f"Loaded {len(self._apps_rules)} rules from {filepath}")
        except Exception as e:
            log.info(f"Failed to load config file: {filepath} {e}. Running dry.")

    def find_match(
        self, win_name, win_class, win_caption
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return (layer, virtual_keys) for the first matching rule.

        Rules are checked in config.toml order — first match wins.
        All specified fields must match (AND logic); omitted fields default
        to MATCH_ALL_RE so they always pass.
        """
        for app_rule in self._apps_rules:
            match_name = app_rule[FIELD_NAME].search(win_name)
            match_class = app_rule[FIELD_CLASS].search(win_class)
            match_caption = app_rule[FIELD_CAPTION].search(win_caption)

            if match_name and match_class and match_caption:
                return (app_rule[FIELD_LAYER], app_rule[FIELD_VK])
        return (None, None)


# ----------------------------
# KWanata D-Bus service
# ----------------------------
class KWanataService:
    # DBus service that receives window events from the KWin script and
    # forwards the appropriate layer/virtual-key changes to Kanata.
    #
    # The docstring below is the DBus introspection XML required by pydbus
    # to expose the interface methods.
    """
    <node>
      <interface name="com.pyroflexia.KWanata">
        <method name="notifyCaptionChanged">
          <arg type="s" name="dbus_msg" direction="in"/>
        </method>
        <method name="notifyFocusChanged">
          <arg type="s" name="dbus_msg" direction="in"/>
        </method>
      </interface>
    </node>
    """

    def __init__(self, kanata_client, app_matcher: AppMatcher, default_layer: str):
        self._kanata_client = kanata_client
        self._last_virtual_keys = []
        self._default_layer = default_layer
        self._last_layer = None
        self._app_matcher = app_matcher

    def _notifyKanata(self, dbus_msg):
        """Match the window info against rules and update Kanata state.

        Tracks previous layer and virtual keys to avoid sending redundant
        commands (e.g. rapid focus events between windows of the same app).
        """
        info = utils.parse_dbus_msg(dbus_msg)

        layer, virtual_keys = self._app_matcher.find_match(
            info[FIELD_NAME], info[FIELD_CLASS], info[FIELD_CAPTION]
        )

        # Only switch layer if different from the last one sent.
        if layer != self._last_layer:
            self._kanata_client.change_layer(layer if layer else self._default_layer)
            self._last_layer = layer

        # Release old virtual keys before pressing new ones, so Kanata
        # sees a clean transition (no overlapping key states).
        if virtual_keys != self._last_virtual_keys:
            if self._last_virtual_keys:
                for vk in self._last_virtual_keys:
                    self._kanata_client.act_on_fake_key((vk, "Release"))
            if virtual_keys:
                for vk in virtual_keys:
                    self._kanata_client.act_on_fake_key((vk, "Press"))
            self._last_virtual_keys = virtual_keys

    def notifyCaptionChanged(self, dbus_msg):
        log.debug("Caption changed..." + dbus_msg)
        self._notifyKanata(dbus_msg)

    def notifyFocusChanged(self, dbus_msg):
        log.debug("Focus changed..." + dbus_msg)
        self._notifyKanata(dbus_msg)


# ----------------------------
# Main loop
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="D-Bus listener for KWanata service")

    parser.add_argument(
        "--host",
        default=DEFAULT_KANATA_HOST,
        help=f"Kanata's host (default: {DEFAULT_KANATA_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_KANATA_PORT,
        help=f"Kanata's port (default: {DEFAULT_KANATA_PORT})",
    )
    parser.add_argument(
        "-l",
        "--default_layer",
        default=DEFAULT_KANATA_LAYER,
        help=f"Kanata's default_layer (default: {DEFAULT_KANATA_LAYER})",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to TOML rules file (default: {DEFAULT_CONFIG_FILE})",
    )
    parser.add_argument(
        "--kwin-script",
        default=DEFAULT_KWIN_SCRIPT,
        help=f"Path to KWin JS file to inject (default: {DEFAULT_KWIN_SCRIPT})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Activates debug mode",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)
    log.setLevel(log_level)

    app_matcher = AppMatcher(args.config)

    bus = SessionBus()

    kanata = KanataClient(utils.validate_port(f"{args.host}:{args.port}"))

    service = KWanataService(kanata, app_matcher, args.default_layer)

    # Publish DBus service (will listen to events from the dynamically injected
    # KWin script).
    bus.publish(DBUS_INTERFACE, (DBUS_PATH, service))

    # Inject KWin script so window events start flowing over DBus.
    injector = KWinScriptInjector(bus)
    injector.inject(args.kwin_script)

    log.info(
        f"KWanata service listening D-Bus and forwarding to Kanata on {args.host}:{args.port}"
    )

    # GLib.MainLoop is required by pydbus to dispatch incoming DBus calls.
    loop = None
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        injector.remove()
        if loop:
            loop.quit()
        kanata.close()
        log.info("Service finished by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
