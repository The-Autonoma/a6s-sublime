"""Tests for Autonoma.py plugin singleton."""

from __future__ import annotations

import os
import sys
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests import sublime_stub  # noqa: E402
sublime_stub.install()

import A6s as plug_mod  # noqa: E402  N813
from tests.mock_ws_server import MockWebSocketServer  # noqa: E402


def _make_handler():
    def h(msg):
        return {"id": msg.get("id"), "result": None}
    return h


class PluginLifecycleTests(unittest.TestCase):
    def test_load_no_auto_connect(self):
        p = plug_mod.A6sPlugin()
        p.settings = plug_mod._StaticSettings({"daemon_port": 9999, "auto_connect": False, "telemetry_enabled": False})
        # simulate a client that won't actually connect (no server)
        import a6s_client as ac
        p.client = ac.A6sClient(port=9999, dispatcher=lambda fn: fn())
        p._wire_event_handlers()
        self.assertIsNotNone(p.client)
        p.unload()

    def test_connect_success_and_disconnect(self):
        server = MockWebSocketServer(handler=_make_handler()).start()
        try:
            p = plug_mod.A6sPlugin()
            p.settings = plug_mod._StaticSettings({"daemon_port": server.port, "auto_connect": False, "telemetry_enabled": False})
            import a6s_client as ac
            p.client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            p._wire_event_handlers()
            self.assertTrue(p.connect())
            self.assertTrue(p.client.is_connected())
            # connect is idempotent
            self.assertTrue(p.connect())
            p.disconnect()
            self.assertFalse(p.client.is_connected())
            # disconnect when already disconnected is safe
            p.disconnect()
        finally:
            server.stop()

    def test_connect_failure(self):
        p = plug_mod.A6sPlugin()
        p.settings = plug_mod._StaticSettings({"daemon_port": 1, "auto_connect": False, "telemetry_enabled": False})
        import a6s_client as ac
        p.client = ac.A6sClient(port=1, dispatcher=lambda fn: fn())
        self.assertFalse(p.connect())

    def test_connect_with_no_client(self):
        p = plug_mod.A6sPlugin()
        p.client = None
        self.assertFalse(p.connect())

    def test_event_handlers_fire(self):
        server = MockWebSocketServer(handler=_make_handler()).start()
        try:
            p = plug_mod.A6sPlugin()
            p.settings = plug_mod._StaticSettings({"daemon_port": server.port, "auto_connect": False, "telemetry_enabled": False})
            import a6s_client as ac
            p.client = ac.A6sClient(port=server.port, dispatcher=lambda fn: fn())
            p._wire_event_handlers()
            p.connect()

            # push events - handlers hit active_window() which returns the stub
            server.push_event_now({"type": "phase.update", "data": {"phase": "generate", "status": "running", "progress": 25}})
            server.push_event_now({"type": "task.update", "data": {"taskId": "t1", "status": "running", "progress": 10}})
            server.push_event_now({"type": "execution.complete", "data": {"executionId": "e1", "status": "success"}})
            time.sleep(0.3)
            p.disconnect()
        finally:
            server.stop()

    def test_static_settings(self):
        s = plug_mod._StaticSettings({"x": 1})
        self.assertEqual(s.get("x"), 1)
        self.assertEqual(s.get("y", 2), 2)
        s.set("y", 3)
        self.assertEqual(s.get("y"), 3)


if __name__ == "__main__":
    unittest.main()
