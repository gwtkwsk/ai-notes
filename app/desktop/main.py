from __future__ import annotations

import re
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import threading
from typing import Optional

import gi

from app.config import Config
from app.data.repository import Repository
from app.desktop.markdown_preview import MarkdownPreview
from app.desktop.preferences import PreferencesWindow
from app.rag.service import RagService

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

_CSS = """\
.pill {
    border: 1px solid alpha(currentColor, 0.25);
    border-radius: 100px;
    padding: 2px 8px;
    font-size: 0.85em;
}
.blockquote-border {
    background-color: alpha(currentColor, 0.35);
}
.formatting-toolbar {
}
"""


def _default_db_path() -> str:
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    )
    app_dir = data_home / "disco-notes"
    app_dir.mkdir(parents=True, exist_ok=True)
    return str(app_dir / "notes.db")


# --- Main window ---


class NotesWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        app: Adw.Application,
        repo: Repository,
        config: Config,
        rag_service: Optional[RagService] = None,
    ) -> None:
        super().__init__(application=app)
        self._repo = repo
        self._config = config
        self._rag_service = rag_service

        # state
        self._current_note_id: Optional[int] = None
        self._selected_tag_id: Optional[int] = None
        self._without_labels_filter = False
        self._selected_filter_name = "All Notes"
        self._syncing_sidebar = False
        self._reindex_running = False
        self._header_packed: list[Gtk.Widget] = []

        self.set_title("Disco Notes")
        self.set_default_size(1200, 780)
        self._load_css()

        # Toast overlay wraps everything
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # Main container: sidebar | content
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._toast_overlay.set_child(main_box)

        # --- Sidebar ---
        sidebar_tv = Adw.ToolbarView()
        sidebar_hb = Adw.HeaderBar()
        sidebar_hb.set_show_end_title_buttons(False)
        sidebar_hb.set_title_widget(
            Adw.WindowTitle(title="Labels", subtitle="")
        )
        
        # Hamburger menu
        hamburger = Gtk.MenuButton(icon_name="open-menu-symbolic")
        hamburger.set_tooltip_text("Menu")
        
        menu = Gio.Menu()
        menu.append("Re-index Notes", "win.reindex")
        menu.append("Preferences", "win.preferences")
        menu.append("Keyboard Shortcuts", "win.show-help-overlay")
        hamburger.set_menu_model(menu)
        
        reindex_action = Gio.SimpleAction.new("reindex", None)
        reindex_action.connect("activate", lambda *_: self._start_reindex())
        self.add_action(reindex_action)
        
        pref_action = Gio.SimpleAction.new("preferences", None)
        pref_action.connect("activate", self._on_preferences_clicked)
        self.add_action(pref_action)
        
        sidebar_hb.pack_end(hamburger)
        sidebar_tv.add_top_bar(sidebar_hb)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        sidebar_scroll.set_size_request(280, -1)

        self._labels_list = Gtk.ListBox()
        self._labels_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._labels_list.add_css_class("navigation-sidebar")
        self._labels_list.connect(
            "row-selected", self._on_label_selected
        )
        sidebar_scroll.set_child(self._labels_list)
        sidebar_tv.set_content(sidebar_scroll)
        
        # Sidebar container with separator
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar_box.append(sidebar_tv)
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.append(separator)
        main_box.append(sidebar_box)

        # --- Content area ---
        content_tv = Adw.ToolbarView()
        self._content_header = Adw.HeaderBar()
        self._content_header.set_show_start_title_buttons(False)

        self._window_title = Adw.WindowTitle(
            title="All Notes", subtitle=""
        )
        self._content_header.set_title_widget(self._window_title)
        content_tv.add_top_bar(self._content_header)

        # Reusable buttons (shown/hidden per mode)
        self._new_button = Gtk.Button(icon_name="list-add-symbolic")
        self._new_button.set_tooltip_text("New Note")
        self._new_button.connect("clicked", self._on_new_clicked)

        self._search_button = Gtk.Button(
            icon_name="system-search-symbolic"
        )
        self._search_button.set_tooltip_text("Search (RAG)")
        self._search_button.connect("clicked", self._on_open_ask_clicked)

        self._back_button = Gtk.Button(icon_name="go-previous-symbolic")
        self._back_button.set_tooltip_text("Back")
        self._back_button.connect("clicked", self._on_back_clicked)

        # Toggle group for preview/edit (linked group)
        self._view_toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._view_toggle_box.add_css_class("linked")
        
        self._preview_toggle = Gtk.ToggleButton()
        self._preview_toggle.set_icon_name("view-reveal-symbolic")
        self._preview_toggle.set_tooltip_text("Preview")
        self._preview_toggle.connect("toggled", self._on_preview_toggled)
        self._view_toggle_box.append(self._preview_toggle)
        
        self._edit_toggle = Gtk.ToggleButton()
        self._edit_toggle.set_icon_name("document-edit-symbolic")
        self._edit_toggle.set_tooltip_text("Edit")
        self._edit_toggle.set_group(self._preview_toggle)
        self._edit_toggle.connect("toggled", self._on_edit_toggled)
        self._view_toggle_box.append(self._edit_toggle)

        # Action buttons group (linked)
        self._actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._actions_box.add_css_class("linked")
        
        self._save_button = Gtk.Button(icon_name="document-save-symbolic")
        self._save_button.set_tooltip_text("Save")
        self._save_button.connect("clicked", self._on_save_clicked)
        self._actions_box.append(self._save_button)
        
        self._favourite_button = Gtk.Button(icon_name="starred-symbolic")
        self._favourite_button.set_tooltip_text("Add to Favourites")
        self._favourite_button.connect("clicked", self._on_toggle_favourite)
        self._actions_box.append(self._favourite_button)
        
        self._delete_button = Gtk.Button(icon_name="user-trash-symbolic")
        self._delete_button.set_tooltip_text("Delete Note")
        self._delete_button.connect("clicked", self._on_delete_clicked)
        self._actions_box.append(self._delete_button)

        # Actions removed - now using direct button connections

        # --- Content stack: list | preview | editor ---
        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(
            Gtk.StackTransitionType.SLIDE_LEFT_RIGHT
        )

        # -- List --
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        self._notes_sections_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=22
        )
        self._notes_sections_box.set_margin_top(24)
        self._notes_sections_box.set_margin_bottom(24)
        self._notes_sections_box.set_margin_start(24)
        self._notes_sections_box.set_margin_end(24)
        list_clamp = Adw.Clamp()
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrapper.append(self._notes_sections_box)
        list_clamp.set_child(wrapper)
        list_clamp.set_maximum_size(920)
        list_scroll.set_child(list_clamp)
        self._content_stack.add_named(list_scroll, "list")

        # -- Preview --
        self._md_preview = MarkdownPreview()
        self._content_stack.add_named(self._md_preview, "preview")

        # -- Editor --
        editor_outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0
        )
        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        editor_scroll.set_vexpand(True)

        editor_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8
        )
        editor_box.set_margin_top(16)
        editor_box.set_margin_bottom(16)
        editor_box.set_margin_start(16)
        editor_box.set_margin_end(16)

        self._title_entry = Gtk.Entry()
        self._title_entry.set_placeholder_text("Title")
        self._title_entry.add_css_class("title-2")
        editor_box.append(self._title_entry)

        # Tags toolbar with linked controls
        self._tags_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._tags_toolbar.add_css_class("linked")
        
        self._tags_add_entry = Gtk.Entry()
        self._tags_add_entry.set_placeholder_text("Add label...")
        self._tags_add_entry.connect("activate", self._on_add_tag)
        self._tags_toolbar.append(self._tags_add_entry)
        
        editor_box.append(self._tags_toolbar)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        text_scroll.set_vexpand(True)
        text_scroll.set_hexpand(True)

        self._content_view = Gtk.TextView()
        self._content_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._content_view.set_monospace(True)
        self._content_view.set_top_margin(8)
        self._content_view.set_bottom_margin(8)
        self._content_view.set_left_margin(8)
        self._content_view.set_right_margin(8)
        text_scroll.set_child(self._content_view)
        editor_box.append(text_scroll)

        editor_clamp = Adw.Clamp()
        editor_clamp.set_child(editor_box)
        editor_clamp.set_maximum_size(980)
        editor_scroll.set_child(editor_clamp)

        editor_outer.append(editor_scroll)
        editor_outer.append(self._build_formatting_toolbar())
        self._content_stack.add_named(editor_outer, "editor")

        content_tv.set_content(self._content_stack)
        content_tv.set_hexpand(True)
        main_box.append(content_tv)

        # --- Initial load ---
        self._reload_sidebar()
        self._reload_notes_list()
        self._set_mode("list")

    # -- CSS --

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    # -- Mode switching --

    def _set_mode(self, mode: str) -> None:
        """Switch visible content between list / preview / editor."""
        self._content_stack.set_visible_child_name(mode)

        # Remove previously packed header buttons
        for btn in self._header_packed:
            self._content_header.remove(btn)
        self._header_packed.clear()

        def _ps(w: Gtk.Widget) -> None:
            self._content_header.pack_start(w)
            self._header_packed.append(w)

        def _pe(w: Gtk.Widget) -> None:
            self._content_header.pack_end(w)
            self._header_packed.append(w)

        if mode == "list":
            _ps(self._new_button)
            _pe(self._search_button)
            self._window_title.set_title(self._selected_filter_name)
            self._window_title.set_subtitle("")

        elif mode == "preview":
            _ps(self._back_button)
            _pe(self._actions_box)
            _pe(self._view_toggle_box)
            self._preview_toggle.set_active(True)
            self._save_button.set_visible(False)
            note = (
                self._repo.get_note(self._current_note_id)
                if self._current_note_id
                else None
            )
            self._window_title.set_title(
                (note.get("title") or "Note") if note else "Note"
            )
            self._window_title.set_subtitle("")
            self._refresh_fav_button()

        elif mode == "editor":
            _ps(self._back_button)
            _pe(self._actions_box)
            _pe(self._view_toggle_box)
            self._edit_toggle.set_active(True)
            self._save_button.set_visible(True)
            self._window_title.set_title(
                self._title_entry.get_text().strip() or "New Note"
            )
            self._window_title.set_subtitle("")
            self._refresh_fav_button()

    def _refresh_fav_button(self) -> None:
        is_fav = False
        if self._current_note_id:
            note = self._repo.get_note(self._current_note_id)
            is_fav = bool(note and note.get("is_favourite"))
        
        if is_fav:
            self._favourite_button.set_icon_name("starred-symbolic")
            self._favourite_button.set_tooltip_text("Remove from Favourites")
        else:
            self._favourite_button.set_icon_name("non-starred-symbolic")
            self._favourite_button.set_tooltip_text("Add to Favourites")

    # -- Navigation --

    def _on_back_clicked(self, _btn: Gtk.Button) -> None:
        if self._content_stack.get_visible_child_name() == "editor":
            self._auto_save()
        self._reload_sidebar()
        self._reload_notes_list()
        self._set_mode("list")

    def _on_edit_toggled(self, btn: Gtk.ToggleButton) -> None:
        if not btn.get_active():
            return
        if self._current_note_id is None:
            return
        self._load_note_into_editor(self._current_note_id)
        self._set_mode("editor")

    def _on_preview_toggled(self, btn: Gtk.ToggleButton) -> None:
        if not btn.get_active():
            return
        self._auto_save()
        if self._current_note_id is not None:
            note = self._repo.get_note(self._current_note_id)
            if note:
                self._md_preview.render(note.get("content", ""))
        self._set_mode("preview")

    def _on_save_clicked(self, _btn: Gtk.Button) -> None:
        """Manually save the current note."""
        self._auto_save()

    def _on_new_clicked(self, _btn: Gtk.Button) -> None:
        self._current_note_id = None
        self._title_entry.set_text("")
        self._tags_add_entry.set_text("")
        self._clear_tag_chips()
        self._content_view.get_buffer().set_text("")
        self._set_mode("editor")

    # -- Note row activation (list -> preview) --

    def _on_note_row_activated(
        self, _lb: Gtk.ListBox, row: Gtk.ListBoxRow
    ) -> None:
        note_id = getattr(row, "note_id", None)
        if note_id is None:
            return
        self._current_note_id = int(note_id)
        note = self._repo.get_note(self._current_note_id)
        if note is None:
            self._toast("Note not found")
            return
        self._md_preview.render(note.get("content", ""))
        self._set_mode("preview")

    # -- Sidebar --

    def _reload_sidebar(self) -> None:
        self._syncing_sidebar = True

        child = self._labels_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._labels_list.remove(child)
            child = nxt

        all_count = len(self._repo.list_notes())
        uncat_count = len(self._repo.list_notes(without_labels=True))

        entries: list[tuple[str, str, Optional[int], int, Optional[str]]] = [
            ("All Notes", "all", None, all_count, "view-grid-symbolic"),
            ("Unlabelled", "without", None, uncat_count, "folder-templates-symbolic"),
        ]
        for tag in self._repo.list_tags():
            tid = int(tag["id"])
            cnt = len(self._repo.list_notes([tid]))
            entries.append((tag["name"], "tag", tid, cnt, None))

        row_to_select: Optional[Gtk.ListBoxRow] = None
        for label, ftype, tid, cnt, icon_name in entries:
            row = Gtk.ListBoxRow()
            row.filter_type = ftype    # type: ignore[attr-defined]
            row.tag_id = tid           # type: ignore[attr-defined]
            row.filter_title = label   # type: ignore[attr-defined]

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(10)
            box.set_margin_end(10)

            if icon_name:
                icon = Gtk.Image.new_from_icon_name(icon_name)
                box.append(icon)
                
            name_lbl = Gtk.Label(label=label)
            name_lbl.set_xalign(0)
            name_lbl.set_hexpand(True)
            name_lbl.set_ellipsize(Pango.EllipsizeMode.END)

            count_lbl = Gtk.Label(label=str(cnt))
            count_lbl.add_css_class("dimmed")

            box.append(name_lbl)
            box.append(count_lbl)
            row.set_child(box)
            
            # Add right-click menu for tags
            if ftype == "tag":
                gesture = Gtk.GestureClick.new()
                gesture.set_button(3)  # Right mouse button
                gesture.connect("pressed", self._on_tag_right_click, tid, label)
                row.add_controller(gesture)
            
            self._labels_list.append(row)

            if ftype == "all" and not self._without_labels_filter and self._selected_tag_id is None:
                row_to_select = row
            elif ftype == "without" and self._without_labels_filter:
                row_to_select = row
            elif ftype == "tag" and tid is not None and self._selected_tag_id == tid:
                row_to_select = row

        if row_to_select is not None:
            self._labels_list.select_row(row_to_select)

        self._syncing_sidebar = False

    def _on_tag_right_click(
        self,
        _gesture: Gtk.GestureClick,
        _n_press: int,
        x: float,
        y: float,
        tag_id: int,
        tag_name: str,
    ) -> None:
        """Show context menu for tag."""
        popover = Gtk.PopoverMenu()
        
        menu = Gio.Menu()
        menu.append("Rename Tag", f"win.rename-tag-{tag_id}")
        menu.append("Delete Tag", f"win.delete-tag-{tag_id}")
        popover.set_menu_model(menu)
        
        # Create actions for this specific tag
        rename_action = Gio.SimpleAction.new(f"rename-tag-{tag_id}", None)
        rename_action.connect("activate", lambda *_: self._on_rename_tag_clicked(tag_id, tag_name))
        self.add_action(rename_action)
        
        delete_action = Gio.SimpleAction.new(f"delete-tag-{tag_id}", None)
        delete_action.connect("activate", lambda *_: self._on_delete_tag_clicked(tag_id, tag_name))
        self.add_action(delete_action)
        
        # Position popover at click location
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.set_parent(_gesture.get_widget())
        popover.popup()

    def _on_rename_tag_clicked(self, tag_id: int, tag_name: str) -> None:
        """Show dialog to rename tag."""
        dialog = Adw.MessageDialog.new(self)
        dialog.set_heading(f"Rename tag \"{tag_name}\"")
        dialog.set_body("Enter a new name for this tag:")
        
        # Create entry for new name
        entry = Gtk.Entry()
        entry.set_text(tag_name)
        entry.set_margin_top(12)
        entry.set_margin_bottom(12)
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        
        # Add entry to dialog's extra child
        dialog.set_extra_child(entry)
        
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        
        dialog.connect("response", lambda d, r: self._on_confirm_rename_tag(r, tag_id, entry.get_text()))
        
        # Select all text for easy replacement
        entry.grab_focus()
        entry.select_region(0, -1)
        
        dialog.present()

    def _on_confirm_rename_tag(self, response: str, tag_id: int, new_name: str) -> None:
        """Handle tag rename confirmation."""
        if response == "rename":
            self._rename_tag(tag_id, new_name)

    def _rename_tag(self, tag_id: int, new_name: str) -> None:
        """Actually rename the tag."""
        new_name = new_name.strip()
        if not new_name:
            self._toast("Tag name cannot be empty")
            return
        
        try:
            self._repo.rename_tag(tag_id, new_name)
            self._toast(f"Renamed tag to \"{new_name}\"")
            
            # Update selected filter name if this tag is currently selected
            if self._selected_tag_id == tag_id:
                self._selected_filter_name = new_name
                self._set_mode(self._content_stack.get_visible_child_name())
            
            self._reload_sidebar()
        except ValueError as exc:
            self._toast(str(exc))
        except Exception as exc:
            self._toast(f"Error renaming tag: {exc}")

    def _on_delete_tag_clicked(self, tag_id: int, tag_name: str) -> None:
        """Delete a tag with confirmation."""
        usage_count = self._repo.get_tag_usage_count(tag_id)
        
        if usage_count > 0:
            # Show confirmation dialog
            dialog = Adw.MessageDialog.new(self)
            dialog.set_heading(f"Delete tag \"{tag_name}\"?")
            dialog.set_body(
                f"This tag is used by {usage_count} note(s). "
                "Deleting it will remove the tag from all notes."
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("delete", "Delete")
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", lambda d, r: self._on_confirm_delete_tag(r, tag_id, tag_name))
            dialog.present()
        else:
            # Delete without confirmation if not used
            self._delete_tag(tag_id, tag_name)

    def _on_confirm_delete_tag(self, response: str, tag_id: int, tag_name: str) -> None:
        """Handle tag deletion confirmation."""
        if response == "delete":
            self._delete_tag(tag_id, tag_name)

    def _delete_tag(self, tag_id: int, tag_name: str) -> None:
        """Actually delete the tag."""
        try:
            self._repo.delete_tag(tag_id)
            self._toast(f"Deleted tag \"{tag_name}\"")
            
            # If this was the selected tag, switch to "All Notes"
            if self._selected_tag_id == tag_id:
                self._selected_tag_id = None
                self._without_labels_filter = False
                self._selected_filter_name = "All Notes"
                self._reload_notes_list()
            
            self._reload_sidebar()
        except Exception as exc:
            self._toast(f"Error deleting tag: {exc}")

    def _on_label_selected(
        self, _lb: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]
    ) -> None:
        if self._syncing_sidebar:
            return

        if row is None:
            self._selected_tag_id = None
            self._without_labels_filter = False
            self._selected_filter_name = "All Notes"
        else:
            ftype = getattr(row, "filter_type", "all")
            if ftype == "all":
                self._selected_tag_id = None
                self._without_labels_filter = False
                self._selected_filter_name = "All Notes"
            elif ftype == "without":
                self._selected_tag_id = None
                self._without_labels_filter = True
                self._selected_filter_name = "Unlabelled"
            else:
                self._selected_tag_id = getattr(row, "tag_id", None)
                self._without_labels_filter = False
                self._selected_filter_name = getattr(row, "filter_title", "")

        self._reload_notes_list()
        self._set_mode("list")

    # -- Notes list --

    def _reload_notes_list(self, select_note_id: Optional[int] = None) -> None:
        self._clear_box(self._notes_sections_box)

        tag_ids = [self._selected_tag_id] if self._selected_tag_id else None
        notes = self._repo.list_notes(tag_ids, without_labels=self._without_labels_filter)

        favourites = [n for n in notes if n.get("is_favourite")]
        others = [n for n in notes if not n.get("is_favourite")]

        grouped: dict[str, list[dict]] = {"Today": [], "Yesterday": [], "Older": []}
        for n in others:
            key = self._section_for_date(
                self._parse_row_date(str(n.get("updated_at", "")))
            )
            grouped[key].append(n)

        if favourites:
            self._add_section("Favourites \u2605", favourites, select_note_id)
        for sec in ("Today", "Yesterday", "Older"):
            if grouped[sec]:
                self._add_section(sec, grouped[sec], select_note_id)

    def _add_section(
        self, title: str, notes: list[dict], select_note_id: Optional[int] = None
    ) -> None:
        lbl = Gtk.Label(label=title)
        lbl.set_xalign(0)
        lbl.add_css_class("heading")
        self._notes_sections_box.append(lbl)

        lb = Gtk.ListBox()
        lb.add_css_class("boxed-list")
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb.connect("row-activated", self._on_note_row_activated)

        for note in notes:
            row = self._build_note_row(note)
            lb.append(row)
            if select_note_id is not None and int(note["id"]) == select_note_id:
                self._on_note_row_activated(lb, row)

        self._notes_sections_box.append(lb)

    def _build_note_row(self, note: dict) -> Gtk.ListBoxRow:
        nid = int(note["id"])
        title = (note.get("title") or "").strip() or "Untitled"
        content = note.get("content", "")

        row = Gtk.ListBoxRow()
        row.set_activatable(True)
        row.set_selectable(False)
        row.note_id = nid  # type: ignore[attr-defined]

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(14)
        outer.set_margin_end(14)

        title_lbl = Gtk.Label(label=title)
        title_lbl.set_xalign(0)
        title_lbl.set_hexpand(True)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.set_single_line_mode(True)
        title_lbl.add_css_class("heading")
        outer.append(title_lbl)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        excerpt = self._content_preview(content)
        excerpt_lbl = Gtk.Label(label=excerpt)
        excerpt_lbl.set_xalign(0)
        excerpt_lbl.set_hexpand(True)
        excerpt_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        excerpt_lbl.set_single_line_mode(True)
        excerpt_lbl.add_css_class("dimmed")
        bottom.append(excerpt_lbl)

        tags = self._repo.get_note_tags(nid)
        if tags:
            pill_text = " / ".join(t["name"] for t in tags[:2])
            pill = Gtk.Label(label=pill_text)
            pill.add_css_class("pill")
            pill.set_valign(Gtk.Align.CENTER)
            bottom.append(pill)

        outer.append(bottom)
        row.set_child(outer)
        return row

    @staticmethod
    def _content_preview(content: str, max_len: int = 100) -> str:
        items: list[str] = []
        for raw_line in content.split("\n"):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^-\s+\[([ xX])\]\s*(.*)", line)
            if m:
                mark = "\u2611" if m.group(1).lower() == "x" else "\u2610"
                items.append(f"{mark} {m.group(2)}")
                continue
            m = re.match(r"^[-*]\s+(.*)", line)
            if m:
                items.append(f"\u2022 {m.group(1)}")
                continue
            items.append(line)
        text = "   ".join(items)
        if len(text) > max_len:
            return text[: max_len - 1].rstrip() + "\u2026"
        return text

    # -- Editor helpers --

    def _load_note_into_editor(self, note_id: int) -> None:
        note = self._repo.get_note(note_id)
        if note is None:
            self._toast("Note not found")
            return
        self._current_note_id = note_id
        self._title_entry.set_text(note.get("title", "") or "")
        self._content_view.get_buffer().set_text(note.get("content", "") or "")
        tags = self._repo.get_note_tags(note_id)
        self._clear_tag_chips()
        for tag in tags:
            self._add_tag_chip(tag["name"])

    def _auto_save(self) -> None:
        title = self._title_entry.get_text().strip()
        buf = self._content_view.get_buffer()
        content = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        tag_names = self._get_current_tags()

        if not title and not content.strip():
            return

        title = title or "New Note"

        if self._current_note_id is None:
            nid = self._repo.create_note(title, content)
            self._repo.set_note_tags(nid, tag_names)
            self._current_note_id = nid
            self._toast("Note created")
        else:
            self._repo.update_note(self._current_note_id, title, content)
            self._repo.set_note_tags(self._current_note_id, tag_names)
            self._toast("Saved")

        self._start_reindex()

    # -- Tag chips management --

    def _add_tag_chip(self, tag_name: str) -> None:
        """Add a tag button to the toolbar."""
        if not tag_name.strip():
            return
        
        # Check if tag already exists
        for tag in self._get_current_tags():
            if tag.lower() == tag_name.lower():
                return
        
        # Create button with AdwButtonContent
        tag_btn = Gtk.Button()
        tag_btn.set_has_frame(True)
        
        btn_content = Adw.ButtonContent()
        btn_content.set_label(tag_name)
        btn_content.set_icon_name("edit-delete-symbolic")
        tag_btn.set_child(btn_content)
        
        tag_btn.connect("clicked", lambda _: self._remove_tag_chip(tag_btn))
        
        self._tags_toolbar.append(tag_btn)
    
    def _remove_tag_chip(self, tag_widget: Gtk.Widget) -> None:
        """Remove a tag button from the toolbar."""
        self._tags_toolbar.remove(tag_widget)
    
    def _clear_tag_chips(self) -> None:
        """Remove all tag buttons."""
        child = self._tags_toolbar.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            # Skip the entry field (first child)
            if child != self._tags_add_entry:
                self._tags_toolbar.remove(child)
            child = next_child
    
    def _get_current_tags(self) -> list[str]:
        """Get list of current tag names from buttons."""
        tags = []
        child = self._tags_toolbar.get_first_child()
        while child is not None:
            # Skip the entry field
            if child != self._tags_add_entry and isinstance(child, Gtk.Button):
                btn_content = child.get_child()
                if isinstance(btn_content, Adw.ButtonContent):
                    tags.append(btn_content.get_label())
            child = child.get_next_sibling()
        return tags
    
    def _on_add_tag(self, entry: Gtk.Entry) -> None:
        """Add new tag from entry."""
        tag_name = entry.get_text().strip()
        if tag_name:
            self._add_tag_chip(tag_name)
            entry.set_text("")

    # -- Actions --

    def _on_toggle_favourite(self, _btn: Gtk.Button) -> None:
        if self._current_note_id is None:
            return
        is_fav = self._repo.toggle_favourite(self._current_note_id)
        self._toast("Added to Favourites" if is_fav else "Removed from Favourites")
        self._refresh_fav_button()

    def _on_delete_clicked(self, _btn: Gtk.Button) -> None:
        if self._current_note_id is None:
            self._toast("No note selected")
            return
        self._repo.delete_note(self._current_note_id)
        self._toast("Deleted")
        self._current_note_id = None
        self._reload_sidebar()
        self._reload_notes_list()
        self._set_mode("list")
        self._start_reindex()

    # -- Formatting toolbar --

    def _build_formatting_toolbar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.set_halign(Gtk.Align.CENTER)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)
        bar.add_css_class("toolbar")
        bar.add_css_class("formatting-toolbar")

        linked = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        linked.add_css_class("linked")
        bar.append(linked)

        items: list[tuple[Optional[str], Optional[str], str, object]] = [
            ("H", None, "Heading", self._fmt_heading),
            (None, "format-text-bold-symbolic", "Bold", self._fmt_bold),
            (None, "format-text-italic-symbolic", "Italic", self._fmt_italic),
            (None, "format-text-strikethrough-symbolic", "Strikethrough", self._fmt_strike),
            ("\u2022", None, "Bullet list", self._fmt_bullet),
            ("1.", None, "Numbered list", self._fmt_ordered),
            ("\u2611", None, "Checkbox", self._fmt_checkbox),
            ("\U0001f517", None, "Link", self._fmt_link),
            ("\u2015", None, "Horizontal rule", self._fmt_hrule),
            ("\u275d", None, "Blockquote", self._fmt_quote),
            ("<>", None, "Code", self._fmt_code),
            ("\u229e", None, "Table", self._fmt_table),
        ]

        def _connect_callback(button, callback):
            button.connect("clicked", lambda _: callback())

        for label, icon, tooltip, cb in items:
            btn = (
                Gtk.Button(icon_name=icon)
                if icon
                else Gtk.Button(label=label)
            )
            btn.set_tooltip_text(tooltip)
            _connect_callback(btn, cb)
            linked.append(btn)

        return bar

    # formatting helpers

    def _fmt_wrap(self, prefix: str, suffix: str) -> None:
        buf = self._content_view.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            text = buf.get_text(start, end, True)
            buf.begin_user_action()
            buf.delete(start, end)
            buf.insert_at_cursor(f"{prefix}{text}{suffix}")
            buf.end_user_action()
        else:
            buf.insert_at_cursor(f"{prefix}{suffix}")

    def _fmt_prefix(self, prefix: str) -> None:
        buf = self._content_view.get_buffer()
        it = buf.get_iter_at_mark(buf.get_insert())
        it.set_line_offset(0)
        buf.insert(it, prefix)

    def _fmt_heading(self) -> None:
        self._fmt_prefix("# ")

    def _fmt_bold(self) -> None:
        self._fmt_wrap("**", "**")

    def _fmt_italic(self) -> None:
        self._fmt_wrap("*", "*")

    def _fmt_strike(self) -> None:
        self._fmt_wrap("~~", "~~")

    def _fmt_bullet(self) -> None:
        self._fmt_prefix("- ")

    def _fmt_ordered(self) -> None:
        self._fmt_prefix("1. ")

    def _fmt_checkbox(self) -> None:
        self._fmt_prefix("- [ ] ")

    def _fmt_link(self) -> None:
        self._fmt_wrap("[", "](url)")

    def _fmt_hrule(self) -> None:
        self._content_view.get_buffer().insert_at_cursor("\n---\n")

    def _fmt_quote(self) -> None:
        self._fmt_prefix("> ")

    def _fmt_code(self) -> None:
        buf = self._content_view.get_buffer()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            text = buf.get_text(start, end, True)
            if "\n" in text:
                buf.begin_user_action()
                buf.delete(start, end)
                buf.insert_at_cursor(f"```\n{text}\n```")
                buf.end_user_action()
                return
        self._fmt_wrap("`", "`")

    def _fmt_table(self) -> None:
        self._content_view.get_buffer().insert_at_cursor(
            "\n| Column 1 | Column 2 |\n"
            "|----------|----------|\n"
            "| Cell     | Cell     |\n"
        )

    # -- Utilities --

    def _toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast.new(message))

    @staticmethod
    def _parse_row_date(raw: str) -> Optional[date]:
        raw = raw.strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace(" ", "T")).date()
        except ValueError:
            return None

    @staticmethod
    def _section_for_date(d: Optional[date]) -> str:
        if d is None:
            return "Older"
        today = date.today()
        if d == today:
            return "Today"
        if d == today - timedelta(days=1):
            return "Yesterday"
        return "Older"

    def _clear_box(self, box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    # -- Preferences --

    def _on_preferences_clicked(self, _action: Gio.SimpleAction, _param: None) -> None:
        dlg = PreferencesWindow(self, self._config, on_save=self._on_config_saved)
        dlg.present()

    def _on_config_saved(self) -> None:
        """Called when preferences are saved. Recreate RAG service with new config."""
        try:
            if self._rag_service is not None:
                self._rag_service.close()
            self._rag_service = RagService(self._repo, self._config)
            GLib.idle_add(lambda: (self._toast("Preferences saved"), False))
        except Exception as exc:
            GLib.idle_add(lambda: (self._toast(f"Error reloading RAG service: {exc}"), False))

    # -- RAG --

    def _on_open_ask_clicked(self, _btn: Gtk.Button) -> None:
        dlg = AskDialog(self, self._rag_service)
        dlg.present()

    def _start_reindex(self) -> None:
        if self._rag_service is None or self._reindex_running:
            return
        self._reindex_running = True
        threading.Thread(target=self._reindex_worker, daemon=True).start()

    def _reindex_worker(self) -> None:
        if self._rag_service is None:
            GLib.idle_add(self._on_reindex_done, "")
            return
        rag = self._rag_service.clone_for_thread()
        try:
            rag.build_index()
            GLib.idle_add(self._on_reindex_done, "")
        except Exception as exc:
            GLib.idle_add(self._on_reindex_done, str(exc))
        finally:
            rag.close()

    def _on_reindex_done(self, error: str) -> bool:
        self._reindex_running = False
        if error:
            self._toast(f"Re-index error: {error}")
        return False


# --- RAG dialog ---


class AskDialog(Adw.Window):
    """Modal dialog for RAG queries."""

    def __init__(
        self,
        parent: NotesWindow,
        rag_service: Optional[RagService],
    ) -> None:
        super().__init__()
        self._parent = parent
        self._rag = rag_service
        self._running = False
        self._cancel = threading.Event()
        self._pulse_id = None

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Ask your notes")
        self.set_default_size(640, 520)

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        tv.add_top_bar(header)
        
        # Progress bar with OSD style (attached to top, right below header)
        self._progress = Gtk.ProgressBar()
        self._progress.add_css_class("osd")
        self._progress.set_visible(False)
        tv.add_top_bar(self._progress)
        
        # Query toolbar with linked controls
        query_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        query_toolbar.add_css_class("toolbar")
        query_toolbar.set_margin_top(6)
        query_toolbar.set_margin_bottom(6)
        query_toolbar.set_margin_start(6)
        query_toolbar.set_margin_end(6)
        
        # Linked controls: Entry | Ask | Cancel
        linked_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        linked_box.add_css_class("linked")
        linked_box.set_hexpand(True)
        
        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text("Ask a question about your notes\u2026")
        self._entry.connect("activate", self._on_ask)
        self._entry.set_hexpand(True)
        linked_box.append(self._entry)
        
        self._ask_btn = Gtk.Button(label="Ask")
        self._ask_btn.add_css_class("suggested-action")
        self._ask_btn.connect("clicked", self._on_ask)
        linked_box.append(self._ask_btn)
        
        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.set_sensitive(False)
        self._cancel_btn.connect("clicked", self._on_cancel)
        linked_box.append(self._cancel_btn)
        
        query_toolbar.append(linked_box)
        tv.add_top_bar(query_toolbar)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        answer_scroll = Gtk.ScrolledWindow()
        answer_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        answer_scroll.set_vexpand(True)
        self._answer = Gtk.TextView()
        self._answer.set_editable(False)
        self._answer.set_cursor_visible(False)
        self._answer.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        answer_scroll.set_child(self._answer)
        box.append(answer_scroll)

        tv.set_content(box)
        self.set_content(tv)

    def _on_ask(self, *_a: object) -> None:
        if self._rag is None:
            return
        q = self._entry.get_text().strip()
        if not q or self._running:
            return
        self._answer.get_buffer().set_text("")
        self._progress.set_visible(True)
        self._progress.pulse()
        self._pulse_id = GLib.timeout_add(100, self._pulse_progress)
        self._running = True
        self._cancel.clear()
        self._ask_btn.set_sensitive(False)
        self._cancel_btn.set_sensitive(True)
        threading.Thread(target=self._worker, args=(q,), daemon=True).start()

    def _pulse_progress(self) -> bool:
        if self._running:
            self._progress.pulse()
            return True
        return False

    def _on_cancel(self, *_a: object) -> None:
        self._cancel.set()

    def _worker(self, question: str) -> None:
        assert self._rag is not None
        rag = self._rag.clone_for_thread()
        try:
            for chunk in rag.ask_stream(question, cancel_cb=self._cancel.is_set):
                GLib.idle_add(self._apply, chunk)
            GLib.idle_add(self._done)
        except Exception as exc:
            GLib.idle_add(self._err, str(exc))
        finally:
            rag.close()

    def _apply(self, c: dict) -> bool:
        # Stream both thinking and answer to the same buffer
        td = str(c.get("thinking_delta", ""))
        ad = str(c.get("answer_delta", ""))
        if td or ad:
            b = self._answer.get_buffer()
            if td:
                b.insert(b.get_end_iter(), td)
            if ad:
                b.insert(b.get_end_iter(), ad)
        if c.get("done"):
            self._progress.set_visible(False)
        return False

    def _done(self) -> bool:
        self._running = False
        self._progress.set_visible(False)
        if self._pulse_id is not None:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None
        self._ask_btn.set_sensitive(True)
        self._cancel_btn.set_sensitive(False)
        return False

    def _err(self, msg: str) -> bool:
        self._progress.set_visible(False)
        b = self._answer.get_buffer()
        b.set_text(f"Error: {msg}")
        self._done()
        return False


# --- Application ---


class DesktopApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="org.disco.DiscoNotes",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self._config: Optional[Config] = None
        self._repo: Optional[Repository] = None
        self._rag_service: Optional[RagService] = None
        self._window: Optional[NotesWindow] = None

    def do_activate(self) -> None:
        if self._window is None:
            self._config = Config()
            db_path = os.getenv("DISCO_NOTES_DB", _default_db_path())
            self._repo = Repository(db_path)
            self._rag_service = RagService(self._repo, self._config)
            self._window = NotesWindow(
                self, self._repo, self._config, self._rag_service
            )
        self._window.present()

    def do_shutdown(self) -> None:
        if self._repo is not None:
            self._repo.close()
            self._repo = None
        Gio.Application.do_shutdown(self)


def main() -> None:
    app = DesktopApplication()
    app.run(None)


if __name__ == "__main__":
    main()
