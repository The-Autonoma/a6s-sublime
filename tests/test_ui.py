"""Tests for autonoma_ui helpers using the sublime stub."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests import sublime_stub  # noqa: E402

# Install stub BEFORE importing autonoma_ui
sublime_stub.install()

import autonoma_ui as ui  # noqa: E402


class StatusTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()
        self.window = sublime_stub.new_window()
        self.view = sublime_stub._View("hello")
        self.window.add_view(self.view)

    def test_set_connection_status_connected(self):
        ui.set_connection_status(self.window, True)
        self.assertIn("connected", self.view._status[ui.STATUS_KEY])

    def test_set_connection_status_offline(self):
        ui.set_connection_status(self.window, False, detail="retrying")
        self.assertIn("offline", self.view._status[ui.STATUS_KEY])
        self.assertIn("retrying", self.view._status[ui.STATUS_KEY])

    def test_set_phase_status(self):
        ui.set_phase_status(self.window, "generate", "running", 42)
        text = self.view._status[ui.STATUS_KEY]
        self.assertIn("generate", text)
        self.assertIn("42", text)

    def test_clear_status(self):
        ui.set_connection_status(self.window, True)
        ui.clear_status(self.window)
        self.assertNotIn(ui.STATUS_KEY, self.view._status)

    def test_clear_status_no_window(self):
        ui.clear_status(None)  # no crash


class OutputPanelTests(unittest.TestCase):
    def setUp(self):
        self.window = sublime_stub.new_window()

    def test_write_output_creates_panel(self):
        ui.write_output(self.window, "hello")
        self.assertIsNotNone(self.window.find_output_panel(ui.OUTPUT_PANEL_NAME))
        # show_panel command should have been issued
        self.assertTrue(any(c[0] == "show_panel" for c in self.window.commands_run))

    def test_write_output_appends_newline(self):
        ui.write_output(self.window, "no-newline", show=False)
        # no crash, panel exists
        self.assertIsNotNone(self.window.find_output_panel(ui.OUTPUT_PANEL_NAME))

    def test_clear_output(self):
        ui.write_output(self.window, "x")
        ui.clear_output(self.window)

    def test_write_output_no_window(self):
        ui.write_output(None, "x")  # no crash


class DialogTests(unittest.TestCase):
    def setUp(self):
        sublime_stub.reset()

    def test_show_error(self):
        ui.show_error("oops")
        self.assertIn("oops", sublime_stub.errors())

    def test_show_message(self):
        ui.show_message("hello")
        self.assertIn("hello", sublime_stub.messages())


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.window = sublime_stub.new_window()

    def test_agent_picker_select(self):
        agents = [{"id": "a", "name": "A", "description": "d"}, {"id": "b", "name": "B", "description": "d"}]
        result = []
        ui.show_agent_picker(self.window, agents, lambda a: result.append(a))
        items, cb = self.window.quick_panel_calls[0]
        self.assertEqual(len(items), 2)
        cb(1)
        self.assertEqual(result[0]["id"], "b")

    def test_agent_picker_cancel(self):
        result = []
        ui.show_agent_picker(self.window, [{"id": "a", "name": "A", "description": ""}], lambda a: result.append(a))
        _, cb = self.window.quick_panel_calls[0]
        cb(-1)
        self.assertIsNone(result[0])

    def test_agent_picker_no_window(self):
        result = []
        ui.show_agent_picker(None, [], lambda a: result.append(a))
        self.assertIsNone(result[0])

    def test_task_picker(self):
        tasks = [{"id": "t1", "task": "x", "agentType": "a", "status": "running", "progress": 50}]
        result = []
        ui.show_task_picker(self.window, tasks, lambda t: result.append(t))
        _, cb = self.window.quick_panel_calls[0]
        cb(0)
        self.assertEqual(result[0]["id"], "t1")

    def test_task_picker_cancel(self):
        result = []
        ui.show_task_picker(self.window, [{"id": "t1", "task": "x", "agentType": "a", "status": "running", "progress": 0}], lambda t: result.append(t))
        _, cb = self.window.quick_panel_calls[0]
        cb(-1)
        self.assertIsNone(result[0])

    def test_task_picker_no_window(self):
        result = []
        ui.show_task_picker(None, [], lambda t: result.append(t))
        self.assertIsNone(result[0])

    def test_show_input(self):
        ui.show_input(self.window, "Enter:", "init", lambda s: None)
        self.assertEqual(len(self.window.input_panel_calls), 1)

    def test_show_input_no_window(self):
        ui.show_input(None, "x", "", lambda s: None)


class FormatTests(unittest.TestCase):
    def test_format_review_issues_empty(self):
        self.assertIn("No issues", ui.format_review_issues([]))

    def test_format_review_issues(self):
        out = ui.format_review_issues([
            {"severity": "error", "message": "m", "line": 5, "suggestion": "s"},
            {"severity": "warning", "message": "m2"},
        ])
        self.assertIn("ERROR", out)
        self.assertIn("line 5", out)
        self.assertIn("suggestion", out)
        self.assertIn("WARNING", out)

    def test_format_artifacts_preview_empty(self):
        self.assertIn("No files", ui.format_artifacts_preview({"files": []}))

    def test_format_artifacts_preview(self):
        out = ui.format_artifacts_preview({"files": [
            {"path": "x.py", "action": "create", "diff": "+foo"},
            {"path": "y.py", "action": "modify"},
        ]})
        self.assertIn("create", out)
        self.assertIn("x.py", out)
        self.assertIn("+foo", out)
        self.assertIn("modify", out)


if __name__ == "__main__":
    unittest.main()
