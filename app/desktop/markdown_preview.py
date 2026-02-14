"""Renders Markdown content as native Gtk widgets for preview."""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402


def _escape(text: str) -> str:
    """Escape text for Pango markup."""
    return GLib.markup_escape_text(text)


def _inline_markup(raw: str) -> str:
    """Convert inline Markdown to Pango markup.

    Handles: code spans, bold, italic, strikethrough, links.
    """
    result: list[str] = []
    # Split on code spans first so markdown inside backticks is not processed.
    parts = re.split(r"(`[^`]+`)", raw)
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            code = _escape(part[1:-1])
            result.append(
                f'<span font_family="monospace" background="#deddda"> {code} </span>'
            )
        else:
            s = _escape(part)
            # Bold **text**
            s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
            # Italic *text*
            s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
            # Strikethrough ~~text~~
            s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
            # Links [text](url) – render as coloured text
            s = re.sub(
                r"\[(.+?)\]\((.+?)\)",
                r'<span foreground="#1a73e8"><u>\1</u></span>',
                s,
            )
            result.append(s)
    return "".join(result)


def _is_block_start(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.startswith("#"):
        return True
    if s.startswith("```"):
        return True
    if re.match(r"^[-*]\s", s) or re.match(r"^\d+\.\s", s):
        return True
    if s.startswith(">"):
        return True
    if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
        return True
    return False


class MarkdownPreview(Gtk.ScrolledWindow):
    """Scrollable markdown preview built from native Gtk widgets."""

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._box.set_margin_top(24)
        self._box.set_margin_bottom(24)
        self._box.set_margin_start(24)
        self._box.set_margin_end(24)

        clamp = Adw.Clamp()
        clamp.set_child(self._box)
        clamp.set_maximum_size(800)
        self.set_child(clamp)

    # ── public API ──────────────────────────────────────────────

    def render(self, markdown: str) -> None:  # noqa: C901
        self._clear()
        lines = markdown.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # Fenced code block
            if line.strip().startswith("```"):
                code_lines: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                if i < len(lines):
                    i += 1  # skip closing fence
                self._add_code_block("\n".join(code_lines))
                continue

            # Heading
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                self._add_heading(m.group(2), len(m.group(1)))
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line.strip()):
                self._add_separator()
                i += 1
                continue

            # Checkbox
            m = re.match(r"^(\s*)-\s+\[([ xX])\]\s*(.*)", line)
            if m:
                self._add_checkbox(
                    m.group(3), m.group(2).lower() == "x", len(m.group(1))
                )
                i += 1
                continue

            # Unordered list
            m = re.match(r"^(\s*)[-*]\s+(.*)", line)
            if m:
                self._add_list_item(m.group(2), len(m.group(1)))
                i += 1
                continue

            # Ordered list
            m = re.match(r"^(\s*)\d+\.\s+(.*)", line)
            if m:
                self._add_list_item(m.group(2), len(m.group(1)), ordered=True)
                i += 1
                continue

            # Blockquote (collect consecutive > lines)
            if line.strip().startswith(">"):
                quote_lines: list[str] = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quote_lines.append(re.sub(r"^>\s?", "", lines[i]))
                    i += 1
                self._add_blockquote("\n".join(quote_lines))
                continue

            # Empty line
            if not line.strip():
                i += 1
                continue

            # Paragraph – accumulate lines until a block marker or blank line
            para_lines: list[str] = []
            while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
                para_lines.append(lines[i])
                i += 1
            if para_lines:
                self._add_paragraph(" ".join(para_lines))
                continue

            # Fallback – skip unknown line
            i += 1

    # ── private helpers ─────────────────────────────────────────

    def _clear(self) -> None:
        child = self._box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._box.remove(child)
            child = nxt

    def _add_heading(self, text: str, level: int) -> None:
        label = Gtk.Label()
        try:
            label.set_markup(_inline_markup(text))
        except GLib.Error:
            label.set_text(text)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_margin_top(16 if level <= 2 else 10)
        label.set_margin_bottom(4)
        css = {1: "title-1", 2: "title-2", 3: "title-3"}.get(level, "title-4")
        label.add_css_class(css)
        self._box.append(label)

    def _add_paragraph(self, text: str) -> None:
        label = Gtk.Label()
        try:
            label.set_markup(_inline_markup(text))
        except GLib.Error:
            label.set_text(text)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        label.set_selectable(True)
        self._box.append(label)

    def _add_code_block(self, code: str) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.add_css_class("card")
        outer.set_margin_top(6)
        outer.set_margin_bottom(6)

        label = Gtk.Label(label=code)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_selectable(True)
        label.add_css_class("monospace")
        label.set_margin_top(10)
        label.set_margin_bottom(10)
        label.set_margin_start(14)
        label.set_margin_end(14)

        outer.append(label)
        self._box.append(outer)

    def _add_checkbox(self, text: str, checked: bool, indent: int = 0) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(indent * 20)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        check = Gtk.CheckButton()
        check.set_active(checked)
        check.set_sensitive(False)

        label = Gtk.Label()
        markup = _inline_markup(text)
        if checked:
            markup = f'<s><span foreground="#888888">{markup}</span></s>'
        try:
            label.set_markup(markup)
        except GLib.Error:
            label.set_text(text)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_hexpand(True)

        row.append(check)
        row.append(label)
        self._box.append(row)

    def _add_list_item(self, text: str, indent: int = 0, ordered: bool = False) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(indent * 20 + 8)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        bullet = Gtk.Label(label="•")
        bullet.set_valign(Gtk.Align.START)

        label = Gtk.Label()
        try:
            label.set_markup(_inline_markup(text))
        except GLib.Error:
            label.set_text(text)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_hexpand(True)

        row.append(bullet)
        row.append(label)
        self._box.append(row)

    def _add_blockquote(self, text: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.set_margin_top(4)
        row.set_margin_bottom(4)

        border = Gtk.Box()
        border.set_size_request(3, -1)
        border.add_css_class("blockquote-border")

        label = Gtk.Label()
        try:
            label.set_markup(f"<i>{_inline_markup(text)}</i>")
        except GLib.Error:
            label.set_text(text)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_margin_start(12)
        label.set_hexpand(True)
        label.set_selectable(True)

        row.append(border)
        row.append(label)
        self._box.append(row)

    def _add_separator(self) -> None:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        self._box.append(sep)
