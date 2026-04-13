"""Tests for a6s_commands with sublime stub + mock client."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests import sublime_stub  # noqa: E402
sublime_stub.install()

import a6s_commands as cmds  # noqa: E402
import a6s_ui as ui  # noqa: E402


class _FakeClient:
    def __init__(self):
        self.connected = True
        self.calls = []
        self.agents = [{"id": "coder-ai", "name": "Coder", "description": ""}]
        self.tasks = [{"id": "t1", "task": "do", "agentType": "coder-ai", "status": "running", "progress": 10}]
        self.completed_tasks = [{"id": "t2", "task": "done", "agentType": "a", "status": "completed", "progress": 100}]
        self.raise_on = None

    def is_connected(self):
        return self.connected

    def _check(self, method):
        if self.raise_on == method:
            raise RuntimeError("fail")

    def list_agents(self):
        self._check("list_agents")
        self.calls.append(("list_agents",))
        return self.agents

    def invoke_agent(self, agent_type, task, context=None):
        self.calls.append(("invoke_agent", agent_type, task))
        return "exec_1"

    def explain_code(self, code, lang, fp):
        self.calls.append(("explain_code", code, lang, fp))
        return "explained"

    def refactor_code(self, code, lang, fp, instructions=None):
        self.calls.append(("refactor_code", code, lang, fp))
        return [{"path": "x.py", "content": "c"}]

    def review_code(self, code, lang, fp, review_type):
        self.calls.append(("review_code", code, lang, fp, review_type))
        return {"issues": [{"severity": "warning", "message": "m"}], "summary": "ok"}

    def generate_tests(self, code, lang, fp):
        self.calls.append(("generate_tests", code, lang, fp))
        return [{"path": "x_test.py"}]

    def background_list(self):
        self._check("background_list")
        self.calls.append(("background_list",))
        return self.tasks

    def execution_status(self, execution_id):
        self._check("execution_status")
        self.calls.append(("execution_status", execution_id))
        return {"status": "running", "phase": "Generate", "progress": 45}

    def background_launch(self, task, agent_type):
        self._check("background_launch")
        self.calls.append(("background_launch", task, agent_type))
        return "task_42"

    def background_output(self, task_id):
        self._check("background_output")
        self.calls.append(("background_output", task_id))
        return "task output text"

    def background_cancel(self, task_id):
        self.calls.append(("background_cancel", task_id))

    def artifacts_preview(self, artifacts):
        self.calls.append(("artifacts_preview", artifacts))
        return {"files": [{"path": "x.py", "action": "create"}]}

    def artifacts_apply(self, artifacts):
        self.calls.append(("artifacts_apply", artifacts))
        return {"applied": 1, "skipped": 0, "errors": []}


class _FakePlugin:
    def __init__(self, client, connect_ok=True):
        self.client = client
        self.settings = {"daemon_port": 9876}
        self._connect_ok = connect_ok
    def connect(self):
        return self._connect_ok
    def disconnect(self):
        self.client.connected = False


def _install_plugin(client, connect_ok=True):
    import A6s as plug_mod  # noqa: N813
    plug_mod.PLUGIN = _FakePlugin(client, connect_ok=connect_ok)
    return plug_mod.PLUGIN


class ValidateInputTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()

    def test_empty(self):
        self.assertIsNone(cmds.validate_input(""))
        self.assertTrue(sublime_stub.errors())

    def test_whitespace(self):
        self.assertIsNone(cmds.validate_input("   \n  "))

    def test_none(self):
        self.assertIsNone(cmds.validate_input(None))

    def test_too_long(self):
        self.assertIsNone(cmds.validate_input("x" * 10001))

    def test_ok(self):
        self.assertEqual(cmds.validate_input("  hi  "), "hi")


class ConnectionCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()

    def test_connect_success(self):
        _install_plugin(self.client, connect_ok=True)
        cmd = cmds.A6sConnectCommand(self.window)
        cmd.window = self.window
        cmd.run()

    def test_connect_failure_shows_instructions(self):
        _install_plugin(self.client, connect_ok=False)
        cmd = cmds.A6sConnectCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(any("a6s code --daemon" in m for m in sublime_stub.messages()))

    def test_disconnect(self):
        _install_plugin(self.client)
        cmd = cmds.A6sDisconnectCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertFalse(self.client.connected)

    def test_require_client_not_connected(self):
        self.client.connected = False
        _install_plugin(self.client)
        result = cmds._require_client(self.window)
        self.assertIsNone(result)
        self.assertTrue(sublime_stub.errors())


class InvokeAgentTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_happy_path(self):
        cmd = cmds.A6sInvokeAgentCommand(self.window)
        cmd.window = self.window
        cmd.run()
        # quick panel shown, then simulate pick
        items, cb = self.window.quick_panel_calls[0]
        self.assertEqual(len(items), 1)
        cb(0)
        # input panel shown
        caption, initial, on_done = self.window.input_panel_calls[0]
        on_done("refactor login")
        # invoke_agent call recorded
        self.assertTrue(any(c[0] == "invoke_agent" for c in self.client.calls))

    def test_empty_task_validation(self):
        cmd = cmds.A6sInvokeAgentCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, cb = self.window.quick_panel_calls[0]
        cb(0)
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("   ")
        self.assertTrue(sublime_stub.errors())

    def test_list_agents_failure(self):
        self.client.raise_on = "list_agents"
        cmd = cmds.A6sInvokeAgentCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(sublime_stub.errors())

    def test_no_agents(self):
        self.client.agents = []
        cmd = cmds.A6sInvokeAgentCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(sublime_stub.errors())

    def test_cancel_agent_picker(self):
        cmd = cmds.A6sInvokeAgentCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, cb = self.window.quick_panel_calls[0]
        cb(-1)  # cancelled
        self.assertEqual(len(self.window.input_panel_calls), 0)


class SelectionCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.view = sublime_stub._View("def f(): pass")
        self.window.add_view(self.view)
        self.client = _FakeClient()
        _install_plugin(self.client)

    def _run(self, cls):
        cmd = cls(self.view)
        cmd.view = self.view
        cmd.run(edit=None)

    def test_explain(self):
        self._run(cmds.A6sExplainCommand)
        self.assertTrue(any(c[0] == "explain_code" for c in self.client.calls))

    def test_refactor(self):
        self._run(cmds.A6sRefactorCommand)
        self.assertTrue(any(c[0] == "refactor_code" for c in self.client.calls))

    def test_review(self):
        self._run(cmds.A6sReviewCommand)
        self.assertTrue(any(c[0] == "review_code" for c in self.client.calls))

    def test_generate_tests(self):
        self._run(cmds.A6sGenerateTestsCommand)
        self.assertTrue(any(c[0] == "generate_tests" for c in self.client.calls))

    def test_no_selection_uses_buffer(self):
        self.view._sel = [sublime_stub.Region(0, 0)]
        self._run(cmds.A6sExplainCommand)
        self.assertTrue(any(c[0] == "explain_code" for c in self.client.calls))

    def test_empty_buffer_rejected(self):
        self.view._text = ""
        self.view._sel = [sublime_stub.Region(0, 0)]
        self._run(cmds.A6sExplainCommand)
        self.assertTrue(sublime_stub.errors())

    def test_disconnected_client_refuses(self):
        self.client.connected = False
        self._run(cmds.A6sExplainCommand)
        self.assertTrue(sublime_stub.errors())


class ListAgentsCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_happy_path(self):
        cmd = cmds.A6sListAgentsCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(any(c[0] == "list_agents" for c in self.client.calls))
        # quick panel shown
        items, cb = self.window.quick_panel_calls[0]
        self.assertEqual(len(items), 1)
        cb(0)

    def test_no_agents(self):
        self.client.agents = []
        cmd = cmds.A6sListAgentsCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(sublime_stub.errors())

    def test_list_failure(self):
        self.client.raise_on = "list_agents"
        cmd = cmds.A6sListAgentsCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(sublime_stub.errors())


class ExecutionStatusCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_happy_path(self):
        cmd = cmds.A6sExecutionStatusCommand(self.window)
        cmd.window = self.window
        cmd.run()
        caption, initial, on_done = self.window.input_panel_calls[0]
        on_done("exec_123")
        self.assertTrue(any(c[0] == "execution_status" for c in self.client.calls))

    def test_empty_input(self):
        cmd = cmds.A6sExecutionStatusCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("   ")
        self.assertTrue(sublime_stub.errors())

    def test_failure(self):
        self.client.raise_on = "execution_status"
        cmd = cmds.A6sExecutionStatusCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("exec_123")
        self.assertTrue(sublime_stub.errors())


class BackgroundLaunchCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_happy_path(self):
        cmd = cmds.A6sBackgroundLaunchCommand(self.window)
        cmd.window = self.window
        cmd.run()
        # agent picker shown
        items, cb = self.window.quick_panel_calls[0]
        cb(0)
        # task input shown
        caption, initial, on_done = self.window.input_panel_calls[0]
        on_done("run migration")
        self.assertTrue(any(c[0] == "background_launch" for c in self.client.calls))

    def test_empty_task(self):
        cmd = cmds.A6sBackgroundLaunchCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, cb = self.window.quick_panel_calls[0]
        cb(0)
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("")
        self.assertTrue(sublime_stub.errors())

    def test_cancel_picker(self):
        cmd = cmds.A6sBackgroundLaunchCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, cb = self.window.quick_panel_calls[0]
        cb(-1)
        self.assertEqual(len(self.window.input_panel_calls), 0)

    def test_launch_failure(self):
        self.client.raise_on = "background_launch"
        cmd = cmds.A6sBackgroundLaunchCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, cb = self.window.quick_panel_calls[0]
        cb(0)
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("do stuff")
        self.assertTrue(sublime_stub.errors())


class BackgroundOutputCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_happy_path(self):
        cmd = cmds.A6sBackgroundOutputCommand(self.window)
        cmd.window = self.window
        cmd.run()
        caption, initial, on_done = self.window.input_panel_calls[0]
        on_done("task_42")
        self.assertTrue(any(c[0] == "background_output" for c in self.client.calls))

    def test_empty_input(self):
        cmd = cmds.A6sBackgroundOutputCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("")
        self.assertTrue(sublime_stub.errors())

    def test_failure(self):
        self.client.raise_on = "background_output"
        cmd = cmds.A6sBackgroundOutputCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, _, on_done = self.window.input_panel_calls[0]
        on_done("task_42")
        self.assertTrue(sublime_stub.errors())


class BackgroundCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_list_tasks(self):
        cmd = cmds.A6sListTasksCommand(self.window)
        cmd.window = self.window
        cmd.run()
        items, cb = self.window.quick_panel_calls[0]
        self.assertEqual(len(items), 1)
        cb(0)

    def test_list_tasks_empty(self):
        self.client.tasks = []
        cmd = cmds.A6sListTasksCommand(self.window)
        cmd.window = self.window
        cmd.run()
        # No quick panel when empty
        self.assertEqual(len(self.window.quick_panel_calls), 0)

    def test_list_tasks_failure(self):
        self.client.raise_on = "background_list"
        cmd = cmds.A6sListTasksCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(sublime_stub.errors())

    def test_cancel_task(self):
        cmd = cmds.A6sCancelTaskCommand(self.window)
        cmd.window = self.window
        cmd.run()
        _, cb = self.window.quick_panel_calls[0]
        cb(0)
        self.assertTrue(any(c[0] == "background_cancel" for c in self.client.calls))

    def test_cancel_no_active_tasks(self):
        self.client.tasks = self.client.completed_tasks
        cmd = cmds.A6sCancelTaskCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(sublime_stub.errors())


class ArtifactCommandTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.client = _FakeClient()
        _install_plugin(self.client)

    def test_preview(self):
        cmd = cmds.A6sPreviewArtifactsCommand(self.window)
        cmd.window = self.window
        cmd.run(artifacts=[{"id": "a1"}])
        self.assertTrue(any(c[0] == "artifacts_preview" for c in self.client.calls))

    def test_preview_empty(self):
        cmd = cmds.A6sPreviewArtifactsCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(any(c[0] == "artifacts_preview" for c in self.client.calls))

    def test_apply(self):
        cmd = cmds.A6sApplyArtifactsCommand(self.window)
        cmd.window = self.window
        cmd.run(artifacts=[{"id": "a1"}])
        self.assertTrue(any(c[0] == "artifacts_apply" for c in self.client.calls))

    def test_apply_empty(self):
        cmd = cmds.A6sApplyArtifactsCommand(self.window)
        cmd.window = self.window
        cmd.run()
        self.assertTrue(any(c[0] == "artifacts_apply" for c in self.client.calls))


class HelperTests(unittest.TestCase):
    def test_view_language(self):
        v = sublime_stub._View("x", syntax="Packages/Python/Python.sublime-syntax")
        self.assertEqual(cmds._view_language(v), "python")

    def test_view_filename(self):
        v = sublime_stub._View("x", filename="/tmp/foo.py")
        self.assertEqual(cmds._view_filename(v), "/tmp/foo.py")

    def test_selection_text_with_region(self):
        v = sublime_stub._View("hello world")
        v._sel = [sublime_stub.Region(0, 5)]
        self.assertEqual(cmds._selection_text(v), "hello")


if __name__ == "__main__":
    unittest.main()
