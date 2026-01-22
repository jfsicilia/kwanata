#!/usr/bin/python3

import argparse
import json
import logging
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

# DBus communication constants used by KWanata KWin Script.
KWANATA_DBUS_INTERFACE = "juan.sicilia.KWanata"
KWANATA_DBUS_PATH = "/juan/sicilia/KWanata"
# The dbus message that will be received has several lines with the format:
#    field1: value
#    field2: value
#    ...
# (see FIELD_XXXX constants for the possible fields)
DBUS_MSG_FIELD_RE = re.compile(r"^\s*(\w+):\s*(.*)$")

MATCH_ALL_RE = re.compile(r".*")

# Toml file sections and fields. Also used for dbus messages, except for FIELD_VK
# that appears in the toml as the result of a name/class/caption match.
SECTION_APP = "app"
FIELD_NAME = "name"
FIELD_CLASS = "class"
FIELD_CAPTION = "caption"
FIELD_VK = "virtual_key"

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
        log.debug("Connecting to %s:%s", *self.addr)
        try:
            self._client.connect(self.addr)
            self._client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._client.settimeout(0.5)
            self._connected = True

            # Send a dummy command to avoid the server doesn't error if the client
            # closes without sending anything
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
        Sends cmd to kanata.
        """
        if not self._connected:
            self._connect()
        logging.debug("Sending command: %s", cmd)
        msg = json.dumps(cmd) + "\n"

        self._flush_buffer()  # Discard old responses
        self._client.sendall(msg.encode("utf-8"))
        self._client.settimeout(0.05)

        try:
            while "\n" not in self._buffer:
                chunk = self._client.recv(1024)
                if not chunk:
                    break
                self._buffer += chunk.decode("utf-8")
        except socket.timeout:
            return None

        lines = self._buffer.split("\n")
        self._buffer = lines[-1]  # Save incomplete part

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


# ----------------------------
# KWanata D-Bus service
# ----------------------------
class KWanataService:
    """
    <node>
      <interface name="juan.sicilia.KWanata">
        <method name="notifyCaptionChanged">
          <arg type="s" name="dbus_msg" direction="in"/>
        </method>
        <method name="notifyFocusChanged">
          <arg type="s" name="dbus_msg" direction="in"/>
        </method>
      </interface>
    </node>
    """

    def __init__(self, kanata_client, app_matcher: AppMatcher):
        self._kanata_client = kanata_client
        self._last_virtual_key = ""
        self._app_matcher = app_matcher

    def _notifyKanata(self, dbus_msg):
        info = utils.parse_dbus_msg(dbus_msg)

        virtual_key = self._app_matcher.find_match(
            info[FIELD_NAME], info[FIELD_CLASS], info[FIELD_CAPTION]
        )

        # If app is not managed, clear previous virtual key and return.
        if not virtual_key:
            if self._last_virtual_key:
                self._kanata_client.act_on_fake_key((self._last_virtual_key, "Release"))
            self._last_virtual_key = ""
            return

        # If current vitual_key is the same as the last one, nothing must be done.
        if self._last_virtual_key == virtual_key:
            return

        # New app in focus!
        if self._last_virtual_key:
            self._kanata_client.act_on_fake_key((self._last_virtual_key, "Release"))
        self._kanata_client.act_on_fake_key((virtual_key, "Press"))
        self._last_virtual_key = virtual_key

    def notifyCaptionChanged(self, dbus_msg):
        log.debug("Caption changed..." + dbus_msg)
        self._notifyKanata(dbus_msg)

    def notifyFocusChanged(self, dbus_msg):
        log.debug("Focus changed..." + dbus_msg)
        self._notifyKanata(dbus_msg)


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
                        FIELD_VK: entry[FIELD_VK],
                    }
                    self._apps_rules.append(rule)
                    log.debug(f"Loaded rule: {rule}")
            log.info(f"Loaded {len(self._apps_rules)} rules from {filepath}")
        except Exception as e:
            log.info(f"Failed to load config file: {filepath} {e}. Running dry.")

    def find_match(self, win_name, win_class, win_caption):
        """Return the first virtual_key that matches the window properties."""
        for app_rule in self._apps_rules:
            # If the rule field is None, it acts as a wildcard (always True)
            match_name = app_rule[FIELD_NAME].search(win_name)
            match_class = app_rule[FIELD_CLASS].search(win_class)
            match_caption = app_rule[FIELD_CAPTION].search(win_caption)

            if match_name and match_class and match_caption:
                return app_rule[FIELD_VK]
        return None


# ----------------------------
# Main loop
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Servicio D-Bus para KWanata")

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
        "-c",
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to TOML rules file (default: {DEFAULT_CONFIG_FILE})",
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

    bus.publish(
        KWANATA_DBUS_INTERFACE, (KWANATA_DBUS_PATH, KWanataService(kanata, app_matcher))
    )

    log.info(
        f"KWanata service listening D-Bus and forwarding to Kanata on {args.host}:{args.port}"
    )

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        log.info("Service finished by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
