#!/usr/bin/python3
"""
kwanata_help_window.py — floating help popup for KWanata.

Spawned as a subprocess by HelpWindowManager in kwanata.py when a
POPUP_HELP or OPEN_HELP:<keys> push message arrives from Kanata and
resolves to an existing help file.

Uses wlr-layer-shell (zwlr_layer_shell_v1) to create an OVERLAY surface:
  - Always on top of every regular window (compositor layer, not a hint)
  - No keyboard focus stolen (KeyboardMode.NONE, enforced by protocol)
  - Anchored to the top-right corner of the screen

Renders the file with basic Markdown support:
  # H1  ## H2  ### H3 — coloured headers (Catppuccin Mocha palette)
  **bold**  *italic*  `inline code`
  - list items    ---  horizontal rule

A trailing "(...)" group on a line (e.g. the launched commands in
"combo -- description (commands)"), marked by kanata_gen_help.py with a
leading \x1f, is treated as secondary detail: shown small and dimmed with
--verbose, hidden otherwise.

Requires gtk-layer-shell:
  Arch / CachyOS:  sudo pacman -S gtk-layer-shell

Usage (standalone test):
  python3 kwanata_help_window.py <filepath> [--verbose]
"""

import re
import sys

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango

# ── Catppuccin Mocha palette ──────────────────────────────────────────────────

_MOCHA_BASE = "#1e1e2e"
_MOCHA_SURFACE0 = "#313244"
_MOCHA_TEXT = "#cdd6f4"
_MOCHA_BLUE = "#89b4fa"  # H1
_MOCHA_MAUVE = "#cba6f7"  # H2
_MOCHA_TEAL = "#94e2d5"  # H3
_MOCHA_GREEN = "#a6e3a1"  # inline code fg
_MOCHA_LAVENDER = "#c203fc"  # border
_MOCHA_OVERLAY0 = "#6c7086"  # HR / subtext

_HEADER_STYLE = {
    1: (_MOCHA_BLUE, "large"),
    2: (_MOCHA_MAUVE, "medium"),
    3: (_MOCHA_TEAL, "small"),
}

_HR_LINE = "─────────────────────────────────"

# Pango's relative <span size="..."> factors, used to weight width estimates
# for text rendered at a non-default size (headers, dimmed details).
_PANGO_SIZE_FACTOR = {"small": 0.8333, "medium": 1.0, "large": 1.2}

# ── Markdown → Pango markup ───────────────────────────────────────────────────


def _esc(s: str) -> str:
    return GLib.markup_escape_text(s)


_BACKTICK_PLACEHOLDER = ""  # Private-Use-Area sentinel; never occurs in real text
_TAG_SPAN_RE = re.compile(r"<(b|i)>.*?</\1>")


def _protect_crossing_code_spans(escaped: str) -> str:
    """Neutralize backtick pairs that straddle an already-substituted <b>/<i>
    tag (one delimiter inside, its partner outside).

    Such a pair makes the later `` `code` `` substitution wrap a closing
    </b>/</i> tag inside a new <span>, producing improperly nested Pango
    markup. Since the whole help file is inserted with a single
    insert_markup() call, one such line silently blanks the entire window
    instead of just that line. Literal stray backticks (e.g. describing a
    "`" keybinding) are common in these files, so treat non-nesting pairs
    as plain characters instead of a code span.
    """
    tag_spans = [m.span() for m in _TAG_SPAN_RE.finditer(escaped)]

    def _container(pos):
        for start, end in tag_spans:
            if start < pos < end:
                return (start, end)
        return None

    positions = [i for i, ch in enumerate(escaped) if ch == "`"]
    if len(positions) < 2:
        return escaped

    chars = list(escaped)
    for i in range(0, len(positions) - 1, 2):
        a, b = positions[i], positions[i + 1]
        if _container(a) != _container(b):
            chars[a] = _BACKTICK_PLACEHOLDER
            chars[b] = _BACKTICK_PLACEHOLDER
    return "".join(chars)


def _inline(escaped: str) -> str:
    """Apply inline Markdown to an already Pango-escaped string."""
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"\*([^*\n]+?)\*", r"<i>\1</i>", escaped)
    escaped = _protect_crossing_code_spans(escaped)
    escaped = re.sub(
        r"`([^`\n]+?)`",
        rf'<span font_family="monospace" foreground="{_MOCHA_GREEN}"'
        rf' background="{_MOCHA_SURFACE0}"> \1 </span>',
        escaped,
    )
    escaped = escaped.replace(_BACKTICK_PLACEHOLDER, "`")
    return escaped


# kanata_gen_help.py (kanata-utils) marks the label/detail boundary with this
# byte rather than letting us guess it by counting parens: a detail can itself
# contain literal "(" / ")" (e.g. a macro that types S-9/S-0, which render as
# those very characters), which breaks any paren-balance heuristic. Keep this
# in sync with that script's own _DETAIL_MARKER if it ever changes.
_DETAIL_MARKER = "\x1f"


def _split_trailing_parens(raw: str) -> tuple[str, str] | None:
    """Split off a trailing "(...)" detail group marked by _DETAIL_MARKER.
    Returns (main, paren) or None if the line has no such marker."""
    line = raw.rstrip()
    if _DETAIL_MARKER not in line:
        return None
    main, _, paren = line.partition(_DETAIL_MARKER)
    main = main.rstrip()
    if not main or not paren.startswith("(") or not paren.endswith(")"):
        return None
    return main, paren


def _line_with_dim_trailing_parens(raw: str, show_details: bool) -> str:
    """Render a line, handling a trailing "(...)" group (e.g. the launched
    commands in "combo -- description (commands)") since it's secondary info:
    shown in a smaller, dimmer font when show_details is True, hidden
    entirely otherwise.
    """
    split = _split_trailing_parens(raw)
    if split is None:
        return _inline(_esc(raw))
    main, paren = split
    if not show_details:
        return _inline(_esc(main))
    return (
        _inline(_esc(main))
        + f' <span size="small" foreground="{_MOCHA_OVERLAY0}">'
        + _inline(_esc(paren))
        + "</span>"
    )


def markdown_to_pango(text: str, show_details: bool = False) -> str:
    out = []
    for raw in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", raw)
        if m:
            level = len(m.group(1))
            color, size = _HEADER_STYLE[level]
            body = _inline(_esc(m.group(2).rstrip()))
            if level == 1 and out:
                out.append("")
            out.append(
                f'<span size="{size}" weight="bold" foreground="{color}">{body}</span>'
            )
            continue

        if re.match(r"^[-*_]{3,}\s*$", raw):
            out.append(f'<span foreground="{_MOCHA_OVERLAY0}">{_HR_LINE}</span>')
            continue

        lm = re.match(r"^(\s*)[-*]\s(.*)", raw)
        if lm:
            indent, rest = lm.groups()
            out.append(indent + "• " + _line_with_dim_trailing_parens(rest, show_details))
            continue

        out.append(_line_with_dim_trailing_parens(raw, show_details))

    return "\n".join(out)


# ── Size estimation ───────────────────────────────────────────────────────────

# Empirical metrics for 10pt monospace at 96 DPI.
_CHAR_W = 8  # pixels per character
_LINE_H = 20  # pixels per line (font + leading)
_H_PAD = 26  # top + bottom margin + border (10+10+3+3)
_W_PAD = 30  # left + right margin + border (12+12+3+3)
_MIN_W = 300


def _strip_inline_markup(s: str) -> str:
    """Strip Markdown inline markers, keeping their content, so width
    estimation reflects rendered text rather than the Markdown source."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"\*([^*\n]+?)\*", r"\1", s)
    s = re.sub(r"`([^`\n]+?)`", r" \1 ", s)  # inline code renders with padding spaces
    return s


def _line_width_units(raw: str, show_details: bool) -> float:
    """Estimate a line's rendered width in base-font character units,
    accounting for header sizing and whether trailing "(...)" details
    (hidden unless show_details) are shown."""
    m = re.match(r"^(#{1,3})\s+(.*)", raw)
    if m:
        level = len(m.group(1))
        _, size = _HEADER_STYLE[level]
        body = _strip_inline_markup(m.group(2).rstrip())
        return len(body) * _PANGO_SIZE_FACTOR[size]

    if re.match(r"^[-*_]{3,}\s*$", raw):
        return len(_HR_LINE)

    lm = re.match(r"^(\s*)[-*]\s(.*)", raw)
    if lm:
        indent, rest = lm.groups()
        raw = indent + "• " + rest

    split = _split_trailing_parens(raw)
    if split is None:
        return len(_strip_inline_markup(raw))
    main, paren = split
    width = len(_strip_inline_markup(main))
    if show_details:
        width += 1 + len(_strip_inline_markup(paren)) * _PANGO_SIZE_FACTOR["small"]
    return width


def _content_size(content: str, sw: int, sh: int, show_details: bool = False) -> tuple[int, int]:
    lines = content.splitlines() or [""]
    text_h = len(lines) * _LINE_H + _H_PAD
    max_width_units = max(_line_width_units(l, show_details) for l in lines)
    text_w = int(max_width_units * _CHAR_W) + _W_PAD
    return max(_MIN_W, min(text_w, sw - 120)), min(text_h, sh - 120)


# ── Window ────────────────────────────────────────────────────────────────────

CSS = (
    b"window { background: transparent; }\n"
    b".kwanata-frame {\n"
    b"    background-color: " + _MOCHA_BASE.encode() + b";\n"
    b"    border: 3px solid " + _MOCHA_LAVENDER.encode() + b";\n"
    b"    border-radius: 8px;\n"
    b"}\n"
    b"textview, textview > text {\n"
    b"    background-color: " + _MOCHA_BASE.encode() + b";\n"
    b"    color: " + _MOCHA_TEXT.encode() + b";\n"
    b"    font-family: monospace;\n"
    b"    font-size: 10pt;\n"
    b"}\n"
)


def _on_draw(widget, cr):
    cr.set_source_rgba(0, 0, 0, 0)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.paint()
    return False


def _screen_size() -> tuple[int, int]:
    monitor = Gdk.Display.get_default().get_primary_monitor()
    if monitor:
        g = monitor.get_geometry()
        return g.width, g.height
    return 1920, 1080


def show_help(filepath: str, show_details: bool = False) -> None:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        sys.exit(f"Cannot read {filepath}: {e}")

    pango_text = markdown_to_pango(content, show_details)
    try:
        Pango.parse_markup(pango_text, -1, "\x00")
    except GLib.Error as e:
        # insert_markup() itself only logs a g_warning and silently leaves
        # the buffer empty on invalid markup, so validate up front and fall
        # back to the raw (unformatted) text rather than show a blank window.
        sys.stderr.write(
            f"kwanata_help_window: invalid markup in {filepath}, "
            f"falling back to plain text: {e}\n"
        )
        pango_text = GLib.markup_escape_text(content)

    sw, sh = _screen_size()
    win_w, win_h = _content_size(content, sw, sh, show_details)

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    win = Gtk.Window()

    rgba = win.get_screen().get_rgba_visual()
    if rgba:
        win.set_visual(rgba)
    win.set_app_paintable(True)
    win.connect("draw", _on_draw)
    win.connect("destroy", Gtk.main_quit)

    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_namespace(win, "kwanata-help")
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.TOP, True)
    GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT, True)
    GtkLayerShell.set_margin(win, GtkLayerShell.Edge.TOP, 50)
    GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT, 50)

    frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    frame.get_style_context().add_class("kwanata-frame")

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_size_request(win_w, win_h)

    textview = Gtk.TextView()
    textview.set_editable(False)
    textview.set_cursor_visible(False)
    textview.set_wrap_mode(Gtk.WrapMode.NONE)
    textview.set_left_margin(12)
    textview.set_right_margin(12)
    textview.set_top_margin(10)
    textview.set_bottom_margin(10)

    buf = textview.get_buffer()
    buf.insert_markup(buf.get_start_iter(), pango_text, len(pango_text.encode("utf-8")))

    scrolled.add(textview)
    frame.pack_start(scrolled, True, True, 0)
    win.add(frame)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <filepath> [--verbose]")
    show_help(sys.argv[1], show_details="--verbose" in sys.argv[2:])
