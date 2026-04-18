"""
Sublime Text commands for the A6s plugin.

All long-running work (daemon RPC) is dispatched to a worker thread via
sublime.set_timeout_async to avoid blocking the UI. View mutations are
scheduled back onto the main thread through a6s_ui helpers.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

try:  # pragma: no cover
    import sublime  # type: ignore
    import sublime_plugin  # type: ignore
    _HAS_SUBLIME = True
    _TextCommand = sublime_plugin.TextCommand
    _WindowCommand = sublime_plugin.WindowCommand
except Exception:  # pragma: no cover - test stub path
    sublime = None  # type: ignore
    _HAS_SUBLIME = False
    class _TextCommand(object):  # type: ignore
        def __init__(self, view: Any = None) -> None:
            self.view = view
        def run(self, edit: Any) -> None: ...
    class _WindowCommand(object):  # type: ignore
        def __init__(self, window: Any = None) -> None:
            self.window = window
        def run(self) -> None: ...

try:
    from . import a6s_ui as ui  # type: ignore
except Exception:  # pragma: no cover - flat import path (ST or tests)
    import a6s_ui as ui  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

MAX_INPUT_CHARS = 10000


def validate_input(text: str) -> Optional[str]:
    """Return sanitized text or None if invalid (errors already surfaced)."""
    if text is None:
        ui.show_error("A6s: input is empty.")
        return None
    text = text.strip()
    if not text:
        ui.show_error("A6s: input is empty.")
        return None
    if len(text) > MAX_INPUT_CHARS:
        ui.show_error(
            "A6s: input exceeds {} character limit ({}).".format(
                MAX_INPUT_CHARS, len(text)
            )
        )
        return None
    return text


# ---------------------------------------------------------------------------
# Worker dispatch
# ---------------------------------------------------------------------------

def _run_async(fn: Callable[[], None]) -> None:
    if _HAS_SUBLIME:
        sublime.set_timeout_async(fn, 0)  # type: ignore
    else:
        t = threading.Thread(target=fn, daemon=True)
        t.start()


def _get_plugin() -> Any:
    """Return the current A6s plugin singleton from A6s module."""
    try:
        from . import A6s as plug  # type: ignore
    except Exception:
        try:
            import A6s as plug  # type: ignore
        except Exception:
            return None
    return getattr(plug, "PLUGIN", None)


def _require_client(window: Any) -> Any:
    plug = _get_plugin()
    if plug is None:
        ui.show_error("A6s plugin not loaded.")
        return None
    client = plug.client
    if client is None or not client.is_connected():
        ui.show_error(
            "A6s daemon is not connected. Run `a6s code --daemon` then "
            "use `A6s: Connect`."
        )
        return None
    return client


def _selection_text(view: Any) -> str:
    try:
        sels = view.sel()
        parts = []
        for region in sels:
            if region.empty():
                continue
            parts.append(view.substr(region))
        if parts:
            return "\n".join(parts)
        # fall back to entire buffer
        return view.substr(sublime.Region(0, view.size())) if _HAS_SUBLIME else ""
    except Exception:
        return ""


def _view_language(view: Any) -> str:
    try:
        syntax = view.settings().get("syntax") or ""
        base = syntax.rsplit("/", 1)[-1].replace(".sublime-syntax", "").lower()
        return base or "plaintext"
    except Exception:
        return "plaintext"


def _view_filename(view: Any) -> str:
    try:
        return view.file_name() or "untitled"
    except Exception:
        return "untitled"


# ---------------------------------------------------------------------------
# Connection commands
# ---------------------------------------------------------------------------

class A6sConnectCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        plug = _get_plugin()
        if plug is None:
            ui.show_error("A6s plugin not loaded.")
            return
        def work() -> None:
            ok = plug.connect()
            if ok:
                ui.set_connection_status(self.window, True)
                ui.write_output(self.window, "A6s: connected to daemon.")
            else:
                ui.set_connection_status(self.window, False)
                ui.show_message(
                    "A6s: could not connect to daemon on port {}.\n\n"
                    "Install and start the CLI daemon:\n"
                    "  brew install autonoma/tap/a6s\n"
                    "  a6s code --daemon\n".format(plug.settings.get("daemon_port", 9876))
                )
        _run_async(work)


class A6sDisconnectCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        plug = _get_plugin()
        if plug is None:
            return
        plug.disconnect()
        ui.set_connection_status(self.window, False)
        ui.write_output(self.window, "A6s: disconnected.")


# ---------------------------------------------------------------------------
# Agent commands
# ---------------------------------------------------------------------------

class A6sInvokeAgentCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def fetch() -> None:
            try:
                agents = client.list_agents()
            except Exception as exc:
                ui.show_error("A6s: failed to list agents: {}".format(exc))
                return
            if not agents:
                ui.show_error("A6s: no agents available.")
                return
            def on_agent(agent: Optional[Dict[str, Any]]) -> None:
                if agent is None:
                    return
                def on_task(task: str) -> None:
                    validated = validate_input(task)
                    if validated is None:
                        return
                    def invoke() -> None:
                        try:
                            exec_id = client.invoke_agent(agent.get("id", ""), validated)
                            ui.write_output(
                                self.window,
                                "A6s: invoked {} (execution {})".format(
                                    agent.get("name", "?"), exec_id
                                ),
                            )
                        except Exception as exc:
                            ui.show_error("A6s: invoke failed: {}".format(exc))
                    _run_async(invoke)
                ui.show_input(self.window, "Task for {}:".format(agent.get("name", "")), "", on_task)
            ui.show_agent_picker(self.window, agents, on_agent)
        _run_async(fetch)


# ---------------------------------------------------------------------------
# Selection-based code commands
# ---------------------------------------------------------------------------

class _SelectionCommand(_TextCommand):
    """Base class for commands that operate on the current selection."""

    def _run_with_selection(
        self,
        verb: str,
        call: Callable[[Any, str, str, str], Any],
        render: Callable[[Any, Any], None],
    ) -> None:
        window = self.view.window() if _HAS_SUBLIME else None
        client = _require_client(window)
        if client is None:
            return
        code = _selection_text(self.view)
        validated = validate_input(code)
        if validated is None:
            return
        language = _view_language(self.view)
        file_path = _view_filename(self.view)
        def work() -> None:
            try:
                result = call(client, validated, language, file_path)
            except Exception as exc:
                ui.show_error("A6s: {} failed: {}".format(verb, exc))
                return
            render(window, result)
        _run_async(work)


class A6sExplainCommand(_SelectionCommand):
    def run(self, edit: Any) -> None:  # type: ignore[override]
        self._run_with_selection(
            "explain",
            lambda c, code, lang, fp: c.explain_code(code, lang, fp),
            lambda w, result: ui.write_output(w, "=== Explain ===\n" + str(result)),
        )


class A6sRefactorCommand(_SelectionCommand):
    def run(self, edit: Any) -> None:  # type: ignore[override]
        self._run_with_selection(
            "refactor",
            lambda c, code, lang, fp: c.refactor_code(code, lang, fp),
            lambda w, result: ui.write_output(
                w, "=== Refactor ({} artifacts) ===\n{}".format(
                    len(result), ui.format_artifacts_preview({"files": [
                        {"action": "modify", "path": a.get("path", ""), "diff": a.get("content", "")[:500]}
                        for a in (result or [])
                    ]})
                )
            ),
        )


class A6sReviewCommand(_SelectionCommand):
    def run(self, edit: Any) -> None:  # type: ignore[override]
        self._run_with_selection(
            "review",
            lambda c, code, lang, fp: c.review_code(code, lang, fp, "all"),
            lambda w, result: ui.write_output(
                w, "=== Review ===\n" + (result.get("summary", "") + "\n" if isinstance(result, dict) else "") +
                ui.format_review_issues(result.get("issues", []) if isinstance(result, dict) else [])
            ),
        )


class A6sGenerateTestsCommand(_SelectionCommand):
    def run(self, edit: Any) -> None:  # type: ignore[override]
        self._run_with_selection(
            "generate-tests",
            lambda c, code, lang, fp: c.generate_tests(code, lang, fp),
            lambda w, result: ui.write_output(
                w, "=== Generated Tests ({} artifacts) ===\n".format(len(result or [])) +
                "\n".join("- " + a.get("path", "?") for a in (result or []))
            ),
        )


# ---------------------------------------------------------------------------
# Background task commands
# ---------------------------------------------------------------------------

class A6sListAgentsCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def work() -> None:
            try:
                agents = client.list_agents()
            except Exception as exc:
                ui.show_error("A6s: failed to list agents: {}".format(exc))
                return
            if not agents:
                ui.show_error("A6s: no agents available.")
                return
            def on_pick(agent: Optional[Dict[str, Any]]) -> None:
                if agent is None:
                    return
                ui.write_output(
                    self.window,
                    "Agent: {} — {}".format(
                        agent.get("id", "?"), agent.get("description", "")
                    ),
                )
            ui.show_agent_picker(self.window, agents, on_pick)
        _run_async(work)


class A6sExecutionStatusCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def on_exec_id(exec_id: str) -> None:
            validated = validate_input(exec_id)
            if validated is None:
                return
            def work() -> None:
                try:
                    result = client.execution_status(validated)
                except Exception as exc:
                    ui.show_error("A6s: execution status failed: {}".format(exc))
                    return
                status = result.get("status", "unknown")
                phase = result.get("phase", "unknown")
                progress = result.get("progress", 0)
                ui.write_output(
                    self.window,
                    "=== Execution {} ===\nstatus={} phase={} progress={}%".format(
                        validated, status, phase, progress
                    ),
                )
            _run_async(work)
        ui.show_input(self.window, "Execution ID:", "", on_exec_id)


class A6sBackgroundLaunchCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def fetch() -> None:
            try:
                agents = client.list_agents()
            except Exception as exc:
                ui.show_error("A6s: failed to list agents: {}".format(exc))
                return
            if not agents:
                ui.show_error("A6s: no agents available.")
                return
            def on_agent(agent: Optional[Dict[str, Any]]) -> None:
                if agent is None:
                    return
                def on_task(task: str) -> None:
                    validated = validate_input(task)
                    if validated is None:
                        return
                    def launch() -> None:
                        try:
                            task_id = client.background_launch(validated, agent.get("id", ""))
                            ui.set_phase_status(
                                self.window,
                                "background",
                                "launched {}".format(task_id),
                                0,
                            )
                        except Exception as exc:
                            ui.show_error("A6s: launch failed: {}".format(exc))
                    _run_async(launch)
                ui.show_input(self.window, "Task for {}:".format(agent.get("name", agent.get("id", ""))), "", on_task)
            ui.show_agent_picker(self.window, agents, on_agent)
        _run_async(fetch)


class A6sBackgroundOutputCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def on_task_id(task_id: str) -> None:
            validated = validate_input(task_id)
            if validated is None:
                return
            def work() -> None:
                try:
                    output = client.background_output(validated)
                except Exception as exc:
                    ui.show_error("A6s: task output failed: {}".format(exc))
                    return
                ui.write_output(
                    self.window,
                    "=== Task {} Output ===\n{}".format(validated, output),
                )
            _run_async(work)
        ui.show_input(self.window, "Task ID:", "", on_task_id)


class A6sListTasksCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def work() -> None:
            try:
                tasks = client.background_list()
            except Exception as exc:
                ui.show_error("A6s: list tasks failed: {}".format(exc))
                return
            if not tasks:
                ui.write_output(self.window, "A6s: no background tasks.")
                return
            def on_pick(task: Optional[Dict[str, Any]]) -> None:
                if task is None:
                    return
                ui.write_output(
                    self.window,
                    "Task {}: {} ({}%)".format(
                        task.get("id", "?"),
                        task.get("status", "?"),
                        task.get("progress", 0),
                    ),
                )
            ui.show_task_picker(self.window, tasks, on_pick)
        _run_async(work)


class A6sCancelTaskCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def work() -> None:
            try:
                tasks = client.background_list()
            except Exception as exc:
                ui.show_error("A6s: list tasks failed: {}".format(exc))
                return
            active = [t for t in tasks if t.get("status") in ("queued", "running")]
            if not active:
                ui.show_error("A6s: no cancellable tasks.")
                return
            def on_pick(task: Optional[Dict[str, Any]]) -> None:
                if task is None:
                    return
                def do_cancel() -> None:
                    try:
                        client.background_cancel(task.get("id", ""))
                        ui.write_output(self.window, "A6s: cancelled {}.".format(task.get("id")))
                    except Exception as exc:
                        ui.show_error("A6s: cancel failed: {}".format(exc))
                _run_async(do_cancel)
            ui.show_task_picker(self.window, active, on_pick)
        _run_async(work)


# ---------------------------------------------------------------------------
# Artifact commands
# ---------------------------------------------------------------------------

class A6sPreviewArtifactsCommand(_WindowCommand):
    def run(self, artifacts: Optional[List[Dict[str, Any]]] = None) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        arts = artifacts or []
        def work() -> None:
            try:
                preview = client.artifacts_preview(arts)
            except Exception as exc:
                ui.show_error("A6s: preview failed: {}".format(exc))
                return
            ui.write_output(self.window, "=== Artifact Preview ===\n" + ui.format_artifacts_preview(preview))
        _run_async(work)


class A6sApplyArtifactsCommand(_WindowCommand):
    def run(self, artifacts: Optional[List[Dict[str, Any]]] = None) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        arts = artifacts or []
        def work() -> None:
            try:
                result = client.artifacts_apply(arts)
            except Exception as exc:
                ui.show_error("A6s: apply failed: {}".format(exc))
                return
            ui.write_output(
                self.window,
                "=== Apply Result ===\napplied={} skipped={} errors={}".format(
                    result.get("applied", 0),
                    result.get("skipped", 0),
                    len(result.get("errors", [])),
                ),
            )
        _run_async(work)


# ---------------------------------------------------------------------------
# Fleet commands
# ---------------------------------------------------------------------------

class A6sFleetListCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def work() -> None:
            try:
                agents = client.fleet_list()
            except Exception as exc:
                ui.show_error("A6s: fleet list failed: {}".format(exc))
                return
            if not agents:
                ui.write_output(self.window, "A6s: no agents in fleet.")
                return
            lines = ["=== Fleet ({} agents) ===".format(len(agents))]
            for a in agents:
                lines.append("{}: {} [{}]".format(
                    a.get("id", "?"),
                    a.get("name", "?"),
                    a.get("status", "unknown"),
                ))
            ui.write_output(self.window, "\n".join(lines))
        _run_async(work)


class A6sFleetStatusCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def fetch() -> None:
            try:
                agents = client.fleet_list()
            except Exception as exc:
                ui.show_error("A6s: fleet list failed: {}".format(exc))
                return
            if not agents:
                ui.show_error("A6s: no agents in fleet.")
                return
            def on_agent(agent: Optional[Dict[str, Any]]) -> None:
                if agent is None:
                    return
                def work() -> None:
                    try:
                        result = client.fleet_status(agent.get("id", ""))
                    except Exception as exc:
                        ui.show_error("A6s: fleet status failed: {}".format(exc))
                        return
                    ui.write_output(
                        self.window,
                        "=== Fleet Status: {} ===\nstatus={} uptime={} tasks={}".format(
                            agent.get("name", agent.get("id", "?")),
                            result.get("status", "unknown"),
                            result.get("uptime", "?"),
                            result.get("activeTasks", 0),
                        ),
                    )
                _run_async(work)
            ui.show_agent_picker(self.window, agents, on_agent)
        _run_async(fetch)


# ---------------------------------------------------------------------------
# Workflow commands
# ---------------------------------------------------------------------------

class A6sWorkflowListCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def work() -> None:
            try:
                workflows = client.workflow_list()
            except Exception as exc:
                ui.show_error("A6s: workflow list failed: {}".format(exc))
                return
            if not workflows:
                ui.write_output(self.window, "A6s: no workflows available.")
                return
            lines = ["=== Workflows ({}) ===".format(len(workflows))]
            for w in workflows:
                lines.append("{}: {}".format(
                    w.get("id", "?"), w.get("description", w.get("name", ""))
                ))
            ui.write_output(self.window, "\n".join(lines))
        _run_async(work)


class A6sWorkflowRunCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def fetch() -> None:
            try:
                workflows = client.workflow_list()
            except Exception as exc:
                ui.show_error("A6s: workflow list failed: {}".format(exc))
                return
            if not workflows:
                ui.show_error("A6s: no workflows available.")
                return
            items = [
                [w.get("name", w.get("id", "?")), w.get("description", "")]
                for w in workflows
            ]
            def on_pick(idx: int) -> None:
                if idx < 0:
                    return
                workflow = workflows[idx]
                def do_run() -> None:
                    try:
                        exec_id = client.workflow_run(workflow.get("id", ""))
                        ui.write_output(
                            self.window,
                            "A6s: started workflow {} (execution {})".format(
                                workflow.get("name", workflow.get("id", "?")), exec_id
                            ),
                        )
                    except Exception as exc:
                        ui.show_error("A6s: workflow run failed: {}".format(exc))
                _run_async(do_run)
            def show() -> None:
                if self.window is None:
                    return
                self.window.show_quick_panel(items, on_pick)
            if _HAS_SUBLIME:
                import sublime as _sl
                _sl.set_timeout(show, 0)  # type: ignore
            else:
                show()
        _run_async(fetch)


class A6sWorkflowStatusCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def on_exec_id(exec_id: str) -> None:
            validated = validate_input(exec_id)
            if validated is None:
                return
            def work() -> None:
                try:
                    result = client.workflow_status(validated)
                except Exception as exc:
                    ui.show_error("A6s: workflow status failed: {}".format(exc))
                    return
                ui.write_output(
                    self.window,
                    "=== Workflow Execution {} ===\nstatus={} phase={} progress={}%".format(
                        validated,
                        result.get("status", "unknown"),
                        result.get("phase", "unknown"),
                        result.get("progress", 0),
                    ),
                )
            _run_async(work)
        ui.show_input(self.window, "Workflow Execution ID:", "", on_exec_id)


class A6sWorkflowCancelCommand(_WindowCommand):
    def run(self) -> None:  # type: ignore[override]
        client = _require_client(self.window)
        if client is None:
            return
        def on_exec_id(exec_id: str) -> None:
            validated = validate_input(exec_id)
            if validated is None:
                return
            def work() -> None:
                try:
                    client.workflow_cancel(validated)
                    ui.write_output(
                        self.window,
                        "A6s: cancelled workflow execution {}.".format(validated),
                    )
                except Exception as exc:
                    ui.show_error("A6s: workflow cancel failed: {}".format(exc))
            _run_async(work)
        ui.show_input(self.window, "Workflow Execution ID to cancel:", "", on_exec_id)
