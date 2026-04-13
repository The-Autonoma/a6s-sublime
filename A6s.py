"""
Autonoma Sublime Text 4 plugin entry point.

Sublime loads the top-level Autonoma.py module once per plugin host. Keep
global state minimal and guard Sublime imports so the module can be imported
from unit tests outside Sublime.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

try:  # pragma: no cover
    import sublime  # type: ignore
    _HAS_SUBLIME = True
except Exception:  # pragma: no cover
    sublime = None  # type: ignore
    _HAS_SUBLIME = False

try:
    import a6s_client as _client_mod  # type: ignore
    import a6s_ui as ui  # type: ignore
except Exception:  # pragma: no cover
    from . import a6s_client as _client_mod  # type: ignore
    from . import a6s_ui as ui  # type: ignore


SETTINGS_FILE = "A6s.sublime-settings"
DEFAULT_PORT = 9876


class A6sPlugin:
    """Plugin singleton holding client + settings."""

    def __init__(self) -> None:
        self.client: Optional[_client_mod.A6sClient] = None
        self.settings: Any = _StaticSettings({}) if not _HAS_SUBLIME else None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def load(self) -> None:
        if _HAS_SUBLIME:
            self.settings = sublime.load_settings(SETTINGS_FILE)  # type: ignore
        port = int(self.settings.get("daemon_port", DEFAULT_PORT) or DEFAULT_PORT)
        self.client = _client_mod.A6sClient(host="localhost", port=port)
        self._wire_event_handlers()
        self._show_telemetry_prompt_if_needed()
        if self.settings.get("auto_connect", True):
            # connect in a background thread so plugin_loaded is non-blocking
            t = threading.Thread(target=self.connect, daemon=True)
            t.start()

    def unload(self) -> None:
        self.disconnect()

    def connect(self) -> bool:
        with self._lock:
            if self.client is None:
                return False
            if self.client.is_connected():
                return True
            try:
                self.client.connect()
                return True
            except _client_mod.WebSocketError:
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self.client is not None and self.client.is_connected():
                try:
                    self.client.disconnect()
                except Exception:
                    pass

    # -- event wiring ------------------------------------------------------

    def _wire_event_handlers(self) -> None:
        if self.client is None:
            return

        def on_phase(data: Any) -> None:
            if not _HAS_SUBLIME:
                return
            try:
                window = sublime.active_window()  # type: ignore
                ui.set_phase_status(
                    window,
                    data.get("phase", "?"),
                    data.get("status", "?"),
                    int(data.get("progress", 0)),
                )
            except Exception:
                pass

        def on_task(data: Any) -> None:
            if not _HAS_SUBLIME:
                return
            try:
                window = sublime.active_window()  # type: ignore
                ui.write_output(
                    window,
                    "[task {}] {} ({}%)".format(
                        data.get("taskId", "?"),
                        data.get("status", "?"),
                        data.get("progress", 0),
                    ),
                    show=False,
                )
            except Exception:
                pass

        def on_complete(data: Any) -> None:
            if not _HAS_SUBLIME:
                return
            try:
                window = sublime.active_window()  # type: ignore
                ui.write_output(
                    window,
                    "[execution {}] status={}".format(
                        data.get("executionId", "?"),
                        data.get("status", "?"),
                    ),
                )
            except Exception:
                pass

        def on_disconnect(_data: Any) -> None:
            if not _HAS_SUBLIME:
                return
            try:
                window = sublime.active_window()  # type: ignore
                ui.set_connection_status(window, False)
            except Exception:
                pass

        def on_connect(_data: Any) -> None:
            if not _HAS_SUBLIME:
                return
            try:
                window = sublime.active_window()  # type: ignore
                ui.set_connection_status(window, True)
            except Exception:
                pass

        self.client.on("phase.update", on_phase)
        self.client.on("task.update", on_task)
        self.client.on("execution.complete", on_complete)
        self.client.on("connected", on_connect)
        self.client.on("disconnected", on_disconnect)

    # -- telemetry prompt --------------------------------------------------

    def _show_telemetry_prompt_if_needed(self) -> None:
        if not _HAS_SUBLIME:
            return
        current = self.settings.get("telemetry_enabled", None)
        if current is not None:
            return
        def _prompt() -> None:
            answer = sublime.ok_cancel_dialog(  # type: ignore
                "A6s would like to send anonymous usage telemetry to help "
                "improve the extension. No code or filenames are transmitted.\n\n"
                "You can change this anytime in A6s settings.",
                "Enable",
            )
            self.settings.set("telemetry_enabled", bool(answer))
            sublime.save_settings(SETTINGS_FILE)  # type: ignore
        sublime.set_timeout(_prompt, 500)  # type: ignore


class _StaticSettings(dict):
    """Minimal sublime.load_settings stand-in for tests."""
    def __init__(self, base: Any) -> None:
        super().__init__(base or {})
    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return dict.get(self, key, default)
    def set(self, key: str, value: Any) -> None:
        self[key] = value


PLUGIN: Optional[A6sPlugin] = None


def plugin_loaded() -> None:  # pragma: no cover - invoked by Sublime only
    global PLUGIN
    PLUGIN = A6sPlugin()
    PLUGIN.load()


def plugin_unloaded() -> None:  # pragma: no cover
    global PLUGIN
    if PLUGIN is not None:
        PLUGIN.unload()
        PLUGIN = None
