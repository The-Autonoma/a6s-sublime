"""
UI helpers for the A6s Sublime plugin.

All view/window mutations MUST go through sublime.set_timeout to stay on the
main thread. These helpers centralize that discipline.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

try:  # pragma: no cover
    import sublime  # type: ignore
    _HAS_SUBLIME = True
except Exception:  # pragma: no cover
    sublime = None  # type: ignore
    _HAS_SUBLIME = False


STATUS_KEY = "a6s"
OUTPUT_PANEL_NAME = "a6s_output"


def _on_main(fn: Callable[[], None]) -> None:
    if _HAS_SUBLIME:
        sublime.set_timeout(fn, 0)  # type: ignore
    else:
        fn()


def set_connection_status(window: Any, connected: bool, detail: str = "") -> None:
    """Update status bar with connection state."""
    icon = "connected" if connected else "offline"
    text = "A6s: {}".format(icon)
    if detail:
        text += " - " + detail
    def _apply() -> None:
        if window is None:
            return
        for view in window.views():
            view.set_status(STATUS_KEY, text)
    _on_main(_apply)


def set_phase_status(window: Any, phase: str, status: str, progress: int) -> None:
    """Update status bar with current RIGOR phase."""
    text = "A6s: [{}] {} ({}%)".format(phase, status, progress)
    def _apply() -> None:
        if window is None:
            return
        for view in window.views():
            view.set_status(STATUS_KEY, text)
    _on_main(_apply)


def clear_status(window: Any) -> None:
    def _apply() -> None:
        if window is None:
            return
        for view in window.views():
            view.erase_status(STATUS_KEY)
    _on_main(_apply)


def _ensure_panel(window: Any) -> Any:
    panel = window.find_output_panel(OUTPUT_PANEL_NAME)
    if panel is None:
        panel = window.create_output_panel(OUTPUT_PANEL_NAME)
    return panel


def write_output(window: Any, text: str, show: bool = True) -> None:
    """Append text to the A6s output panel."""
    if not text.endswith("\n"):
        text = text + "\n"
    def _apply() -> None:
        if window is None:
            return
        panel = _ensure_panel(window)
        panel.set_read_only(False)
        panel.run_command("append", {"characters": text, "force": True, "scroll_to_end": True})
        panel.set_read_only(True)
        if show:
            window.run_command("show_panel", {"panel": "output." + OUTPUT_PANEL_NAME})
    _on_main(_apply)


def clear_output(window: Any) -> None:
    def _apply() -> None:
        if window is None:
            return
        panel = _ensure_panel(window)
        panel.set_read_only(False)
        panel.run_command("select_all")
        panel.run_command("right_delete")
        panel.set_read_only(True)
    _on_main(_apply)


def show_error(message: str) -> None:
    def _apply() -> None:
        if _HAS_SUBLIME:
            sublime.error_message(message)  # type: ignore
    _on_main(_apply)


def show_message(message: str) -> None:
    def _apply() -> None:
        if _HAS_SUBLIME:
            sublime.message_dialog(message)  # type: ignore
    _on_main(_apply)


def show_agent_picker(
    window: Any,
    agents: List[Dict[str, Any]],
    on_select: Callable[[Optional[Dict[str, Any]]], None],
) -> None:
    items = [[a.get("name", a.get("id", "?")), a.get("description", "")] for a in agents]
    def _cb(idx: int) -> None:
        if idx < 0:
            on_select(None)
        else:
            on_select(agents[idx])
    def _apply() -> None:
        if window is None:
            on_select(None)
            return
        window.show_quick_panel(items, _cb)
    _on_main(_apply)


def show_task_picker(
    window: Any,
    tasks: List[Dict[str, Any]],
    on_select: Callable[[Optional[Dict[str, Any]]], None],
) -> None:
    items = [
        [t.get("task", "")[:80], "{} - {} ({}%)".format(
            t.get("agentType", "?"), t.get("status", "?"), t.get("progress", 0)
        )]
        for t in tasks
    ]
    def _cb(idx: int) -> None:
        on_select(None if idx < 0 else tasks[idx])
    def _apply() -> None:
        if window is None:
            on_select(None)
            return
        window.show_quick_panel(items, _cb)
    _on_main(_apply)


def show_input(
    window: Any,
    caption: str,
    initial: str,
    on_done: Callable[[str], None],
) -> None:
    def _apply() -> None:
        if window is None:
            return
        window.show_input_panel(caption, initial, on_done, None, None)
    _on_main(_apply)


def format_review_issues(issues: List[Dict[str, Any]]) -> str:
    """Render review issues as plain text block."""
    if not issues:
        return "No issues found.\n"
    out = []
    for issue in issues:
        line = issue.get("line")
        prefix = "[{}]".format(issue.get("severity", "info").upper())
        if line is not None:
            prefix += " line {}".format(line)
        out.append("{}: {}".format(prefix, issue.get("message", "")))
        if issue.get("suggestion"):
            out.append("  suggestion: {}".format(issue["suggestion"]))
    return "\n".join(out) + "\n"


def format_artifacts_preview(preview: Dict[str, Any]) -> str:
    files = preview.get("files", [])
    if not files:
        return "No files would be changed.\n"
    lines = []
    for f in files:
        lines.append("{}: {}".format(f.get("action", "?"), f.get("path", "?")))
        if f.get("diff"):
            lines.append(f["diff"])
    return "\n".join(lines) + "\n"
