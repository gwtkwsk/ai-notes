"""Preferences window for Disco Notes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, GLib  # noqa: E402

if TYPE_CHECKING:
    from app.config import Config


class PreferencesWindow(Adw.PreferencesWindow):
    """Application preferences dialog."""

    def __init__(
        self,
        parent: Gtk.Window,
        config: Config,
        on_save: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._on_save_cb = on_save

        # Store initial values to detect changes
        self._initial_values = {
            "base_url": config.ollama_base_url,
            "embed_model": config.embed_model,
            "llm_model": config.llm_model,
            "top_k": config.top_k,
        }

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_search_enabled(False)

        # ── RAG / Ollama page ──
        rag_page = Adw.PreferencesPage()
        rag_page.set_title("RAG")
        rag_page.set_icon_name("document-properties-symbolic")

        # Group: Ollama Connection
        ollama_group = Adw.PreferencesGroup()
        ollama_group.set_title("Ollama Connection")
        ollama_group.set_description(
            "Configure the local Ollama server for embeddings and LLM queries."
        )

        self._base_url_row = Adw.EntryRow()
        self._base_url_row.set_title("Base URL")
        self._base_url_row.set_text(self._config.ollama_base_url)
        ollama_group.add(self._base_url_row)

        # Test connection button
        test_row = Adw.ActionRow()
        test_row.set_title("Connection Status")
        self._status_label = Gtk.Label(label="Not tested")
        self._status_label.add_css_class("dimmed")
        test_row.add_suffix(self._status_label)

        self._test_button = Gtk.Button(label="Test Connection")
        self._test_button.add_css_class("pill")
        self._test_button.set_valign(Gtk.Align.CENTER)
        self._test_button.connect("clicked", self._on_test_connection)
        test_row.add_suffix(self._test_button)
        ollama_group.add(test_row)

        # Group: Models
        models_group = Adw.PreferencesGroup()
        models_group.set_title("Models")

        self._embed_model_row = Adw.EntryRow()
        self._embed_model_row.set_title("Embedding Model")
        self._embed_model_row.set_text(self._config.embed_model)
        models_group.add(self._embed_model_row)

        self._llm_model_row = Adw.EntryRow()
        self._llm_model_row.set_title("LLM Model")
        self._llm_model_row.set_text(self._config.llm_model)
        models_group.add(self._llm_model_row)

        self._top_k_row = Adw.SpinRow.new_with_range(1, 20, 1)
        self._top_k_row.set_title("Top K Results")
        self._top_k_row.set_value(float(self._config.top_k))
        models_group.add(self._top_k_row)

        rag_page.add(ollama_group)
        rag_page.add(models_group)
        self.add(rag_page)

        # ── About page ──
        about_page = Adw.PreferencesPage()
        about_page.set_title("About")
        about_page.set_icon_name("help-about-symbolic")

        about_group = Adw.PreferencesGroup()
        about_label = Gtk.Label(
            label="Disco Notes\nA note-taking app with RAG capabilities."
        )
        about_label.set_margin_top(20)
        about_label.set_margin_bottom(20)
        about_label.add_css_class("title-2")
        about_label.set_justify(Gtk.Justification.CENTER)
        about_group.add(about_label)

        about_page.add(about_group)
        self.add(about_page)

        # Connect close signal to save
        self.connect("close-request", self._on_close)

    def _on_test_connection(self, _button: Gtk.Button) -> None:
        """Test connection to Ollama server."""
        self._test_button.set_sensitive(False)
        self._status_label.set_label("Testing...")
        self._status_label.remove_css_class("success")
        self._status_label.remove_css_class("error")
        self._status_label.add_css_class("dimmed")

        def test_in_thread() -> None:
            from app.rag.ollama_client import OllamaClient

            base_url = self._base_url_row.get_text()
            client = OllamaClient(base_url, "", "")
            success, message = client.check_connection()

            def update_ui() -> bool:
                self._test_button.set_sensitive(True)
                self._status_label.set_label(message)
                self._status_label.remove_css_class("dimmed")
                if success:
                    self._status_label.add_css_class("success")
                else:
                    self._status_label.add_css_class("error")
                return False

            GLib.idle_add(update_ui)

        thread = threading.Thread(target=test_in_thread, daemon=True)
        thread.start()

    def _on_close(self, _window: Adw.PreferencesWindow) -> bool:
        """Save preferences on close."""
        # Get new values
        new_base_url = self._base_url_row.get_text()
        new_embed_model = self._embed_model_row.get_text()
        new_llm_model = self._llm_model_row.get_text()
        new_top_k = int(self._top_k_row.get_value())

        # Check if anything changed
        changed = (
            new_base_url != self._initial_values["base_url"]
            or new_embed_model != self._initial_values["embed_model"]
            or new_llm_model != self._initial_values["llm_model"]
            or new_top_k != self._initial_values["top_k"]
        )

        # Save to config
        self._config.set_ollama_base_url(new_base_url)
        self._config.set_embed_model(new_embed_model)
        self._config.set_llm_model(new_llm_model)
        self._config.set_top_k(new_top_k)
        self._config.save()

        # Only call callback if something changed
        if changed and self._on_save_cb is not None:
            self._on_save_cb()

        return False
