"""
Minimal sublime / sublime_plugin stub for unit tests.

Install by calling install() BEFORE importing any plugin modules that may
touch sublime. The stub is intentionally tiny — we only model what the
plugin code actually calls.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Callable, List


class Region:
    def __init__(self, a: int, b: int) -> None:
        self.a = a
        self.b = b
    def empty(self) -> bool:
        return self.a == self.b


class _View:
    def __init__(self, text: str = "", filename: str = "x.py", syntax: str = "Packages/Python/Python.sublime-syntax") -> None:
        self._text = text
        self._filename = filename
        self._syntax = syntax
        self._status: dict = {}
        self._sel = [Region(0, len(text))] if text else [Region(0, 0)]
        self._window: Any = None
    def substr(self, region: Region) -> str:
        return self._text[region.a:region.b]
    def size(self) -> int:
        return len(self._text)
    def sel(self):
        return self._sel
    def file_name(self) -> str:
        return self._filename
    def settings(self):
        s = types.SimpleNamespace()
        s.get = lambda k: self._syntax if k == "syntax" else None
        return s
    def set_status(self, key: str, value: str) -> None:
        self._status[key] = value
    def erase_status(self, key: str) -> None:
        self._status.pop(key, None)
    def window(self):
        return self._window


class _Window:
    def __init__(self) -> None:
        self._views: List[_View] = []
        self._panels: dict = {}
        self.quick_panel_calls: list = []
        self.input_panel_calls: list = []
        self.commands_run: list = []
    def views(self):
        return self._views
    def add_view(self, v: _View) -> None:
        v._window = self
        self._views.append(v)
    def find_output_panel(self, name: str):
        return self._panels.get(name)
    def create_output_panel(self, name: str):
        p = _View()
        self._panels[name] = p
        p.set_read_only = lambda ro: None  # type: ignore
        p.run_command = lambda *a, **kw: None  # type: ignore
        return p
    def show_quick_panel(self, items, cb):
        self.quick_panel_calls.append((items, cb))
    def show_input_panel(self, caption, initial, on_done, on_change, on_cancel):
        self.input_panel_calls.append((caption, initial, on_done))
    def run_command(self, name, args=None):
        self.commands_run.append((name, args))


_ERRORS: List[str] = []
_MESSAGES: List[str] = []


def set_timeout(fn: Callable[[], None], _ms: int = 0) -> None:
    fn()


def set_timeout_async(fn: Callable[[], None], _ms: int = 0) -> None:
    fn()


def error_message(msg: str) -> None:
    _ERRORS.append(msg)


def message_dialog(msg: str) -> None:
    _MESSAGES.append(msg)


def ok_cancel_dialog(msg: str, ok: str = "OK") -> bool:
    return True


def active_window() -> _Window:
    return _ACTIVE_WINDOW


_ACTIVE_WINDOW = _Window()


def load_settings(name: str):
    class S(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)
        def set(self, k, v):
            self[k] = v
    return S({"daemon_port": 9876, "auto_connect": False, "telemetry_enabled": False})


def save_settings(_name: str) -> None:
    pass


def install() -> None:
    """Install stub modules into sys.modules. Call before plugin import."""
    mod = types.ModuleType("sublime")
    mod.Region = Region
    mod.set_timeout = set_timeout
    mod.set_timeout_async = set_timeout_async
    mod.error_message = error_message
    mod.message_dialog = message_dialog
    mod.ok_cancel_dialog = ok_cancel_dialog
    mod.active_window = active_window
    mod.load_settings = load_settings
    mod.save_settings = save_settings
    sys.modules["sublime"] = mod

    plug = types.ModuleType("sublime_plugin")
    class TextCommand(object):
        def __init__(self, view=None):
            self.view = view
    class WindowCommand(object):
        def __init__(self, window=None):
            self.window = window
    plug.TextCommand = TextCommand
    plug.WindowCommand = WindowCommand
    sys.modules["sublime_plugin"] = plug


def uninstall() -> None:
    sys.modules.pop("sublime", None)
    sys.modules.pop("sublime_plugin", None)


def reset() -> None:
    _ERRORS.clear()
    _MESSAGES.clear()


def errors() -> List[str]:
    return list(_ERRORS)


def messages() -> List[str]:
    return list(_MESSAGES)


def new_window() -> _Window:
    return _Window()
