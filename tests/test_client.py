"""Tests for a6s_client.A6sClient against a mock WS server."""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest

# Make the plugin root importable
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import a6s_client as ac  # noqa: E402
from tests.mock_ws_server import MockWebSocketServer  # noqa: E402


def _make_handler(responses):
    """Build a handler that returns canned responses keyed by method."""
    def _h(msg):
        method = msg.get("method")
        if method in responses:
            return {"id": msg.get("id"), "result": responses[method]}
        return {"id": msg.get("id"), "error": "unknown method: " + str(method)}
    return _h


class ClientHandshakeTests(unittest.TestCase):
    def test_connect_and_disconnect(self):
        server = MockWebSocketServer().start()
        try:
            client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            client.connect()
            self.assertTrue(client.is_connected())
            client.disconnect()
            self.assertFalse(client.is_connected())
        finally:
            server.stop()

    def test_connect_refused(self):
        # Bind a socket, close it — port is free, connect should fail
        client = ac.A6sClient(port=1, dispatcher=lambda fn: fn())
        with self.assertRaises(ac.WebSocketError):
            client.connect()

    def test_connect_timeout_with_no_handshake(self):
        server = MockWebSocketServer(drop_before_handshake=True).start()
        try:
            client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            with self.assertRaises(ac.WebSocketError):
                client.connect(timeout=1.0)
        finally:
            server.stop()

    def test_reconnect_with_backoff_succeeds_after_server_up(self):
        # start server first so attempt succeeds on first try
        server = MockWebSocketServer().start()
        try:
            client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            ok = client.reconnect_with_backoff(max_attempts=2)
            self.assertTrue(ok)
            client.disconnect()
        finally:
            server.stop()

    def test_reconnect_with_backoff_fails(self):
        client = ac.A6sClient(port=1, dispatcher=lambda fn: fn())
        start = time.time()
        ok = client.reconnect_with_backoff(max_attempts=2)
        self.assertFalse(ok)
        # Should have slept ~1s between the 2 attempts
        self.assertGreaterEqual(time.time() - start, 0.9)


class ClientRequestTests(unittest.TestCase):

    def setUp(self):
        self.responses = {
            "agents.list": [{"id": "coder-ai", "name": "Coder", "description": "d", "status": "available"}],
            "agents.invoke": {"executionId": "exec_1"},
            "execution.status": {"executionId": "exec_1", "status": "success", "phases": [], "artifacts": []},
            "background.list": [{"id": "t1", "task": "x", "agentType": "a", "status": "running", "progress": 10, "startedAt": "2026-01-01"}],
            "background.launch": {"taskId": "t2"},
            "background.cancel": None,
            "background.output": "log line 1\nlog line 2",
            "artifacts.preview": {"files": [{"path": "x.py", "action": "create"}]},
            "artifacts.apply": {"applied": 1, "skipped": 0, "errors": []},
            "code.explain": "This does X.",
            "code.refactor": [{"id": "a1", "type": "patch", "path": "x.py", "content": "...", "language": "python"}],
            "code.generateTests": [{"id": "a2", "type": "file", "path": "x_test.py", "content": "...", "language": "python"}],
            "code.review": {"issues": [{"severity": "warning", "message": "use async"}], "summary": "ok"},
        }
        self.server = MockWebSocketServer(handler=_make_handler(self.responses)).start()
        self.client = ac.A6sClient(port=self.server.port, dispatcher=lambda fn: fn())
        self.client.connect()

    def tearDown(self):
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.server.stop()

    def test_not_connected_raises(self):
        self.client.disconnect()
        with self.assertRaises(ac.WebSocketError):
            self.client.list_agents()

    def test_list_agents(self):
        agents = self.client.list_agents()
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["id"], "coder-ai")

    def test_invoke_agent(self):
        exec_id = self.client.invoke_agent("coder-ai", "do stuff")
        self.assertEqual(exec_id, "exec_1")

    def test_execution_status(self):
        status = self.client.execution_status("exec_1")
        self.assertEqual(status["status"], "success")

    def test_background_list(self):
        tasks = self.client.background_list()
        self.assertEqual(tasks[0]["id"], "t1")

    def test_background_launch(self):
        tid = self.client.background_launch("go", "agent")
        self.assertEqual(tid, "t2")

    def test_background_cancel(self):
        self.client.background_cancel("t1")  # should not raise

    def test_background_output(self):
        out = self.client.background_output("t1")
        self.assertIn("log line 1", out)

    def test_artifacts_preview(self):
        preview = self.client.artifacts_preview([])
        self.assertEqual(preview["files"][0]["action"], "create")

    def test_artifacts_apply(self):
        result = self.client.artifacts_apply([])
        self.assertEqual(result["applied"], 1)

    def test_explain_code(self):
        txt = self.client.explain_code("code", "python", "x.py")
        self.assertIn("does X", txt)

    def test_refactor_code(self):
        arts = self.client.refactor_code("code", "python", "x.py", "improve")
        self.assertEqual(len(arts), 1)

    def test_generate_tests(self):
        arts = self.client.generate_tests("code", "python", "x.py")
        self.assertEqual(arts[0]["path"], "x_test.py")

    def test_review_code(self):
        r = self.client.review_code("code", "python", "x.py", "all")
        self.assertEqual(r["summary"], "ok")
        self.assertEqual(len(r["issues"]), 1)

    def test_server_error_propagates(self):
        with self.assertRaises(ac.WebSocketError):
            self.client.request("bogus.method", {})

    def test_request_timeout(self):
        # Handler that never responds
        server = MockWebSocketServer(handler=lambda m: None).start()
        try:
            c = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            c.connect()
            try:
                with self.assertRaises(ac.WebSocketError):
                    c.request("agents.list", {}, timeout=0.5)
            finally:
                c.disconnect()
        finally:
            server.stop()


class ClientEventTests(unittest.TestCase):

    def test_events_dispatched(self):
        server = MockWebSocketServer(handler=_make_handler({"agents.list": []})).start()
        try:
            received = []
            client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            client.on("phase.update", lambda d: received.append(("phase", d)))
            client.on("task.update", lambda d: received.append(("task", d)))
            client.on("execution.complete", lambda d: received.append(("done", d)))
            client.connect()

            server.push_event({"type": "phase.update", "data": {"phase": "generate", "status": "running", "progress": 50}})
            server.push_event({"type": "task.update", "data": {"taskId": "t1", "status": "running", "progress": 10}})
            server.push_event({"type": "execution.complete", "data": {"executionId": "e1", "status": "success"}})
            # Trigger server to flush events
            client.list_agents()
            time.sleep(0.2)

            kinds = [r[0] for r in received]
            self.assertIn("phase", kinds)
            self.assertIn("task", kinds)
            self.assertIn("done", kinds)
            client.disconnect()
        finally:
            server.stop()

    def test_connected_and_disconnected_events(self):
        server = MockWebSocketServer().start()
        try:
            events = []
            client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            client.on("connected", lambda d: events.append("c"))
            client.on("disconnected", lambda d: events.append("d"))
            client.connect()
            client.disconnect()
            self.assertIn("c", events)
            self.assertIn("d", events)
        finally:
            server.stop()

    def test_off_removes_handler(self):
        client = ac.A6sClient(dispatcher=lambda fn: fn())
        calls = []
        def h(d):
            calls.append(d)
        client.on("x", h)
        client.off("x", h)
        client._emit("x", {})
        self.assertEqual(calls, [])

    def test_unknown_event_is_noop(self):
        client = ac.A6sClient(dispatcher=lambda fn: fn())
        # No handlers registered - must not raise
        client._emit("never.seen", {"foo": 1})

    def test_invalid_json_ignored(self):
        client = ac.A6sClient(dispatcher=lambda fn: fn())
        client._handle_text(b"not json")  # must not raise

    def test_handler_exception_isolated(self):
        client = ac.A6sClient(dispatcher=lambda fn: fn())
        def bad(d):
            raise RuntimeError("boom")
        good_calls = []
        client.on("x", bad)
        client.on("x", lambda d: good_calls.append(d))
        client._emit("x", {})
        self.assertEqual(len(good_calls), 1)


class CodecTests(unittest.TestCase):
    def test_accept_key(self):
        # Example from RFC 6455
        self.assertEqual(
            ac._make_accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
        )


if __name__ == "__main__":
    unittest.main()
