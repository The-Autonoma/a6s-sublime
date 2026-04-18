"""
A6s WebSocket client for Sublime Text 4.

Implements the authoritative DAEMON-PROTOCOL.md spec (v1.0):
    ws://localhost:9876/ws

This module uses only the Python 3.8 stdlib (socket, struct, threading, json,
base64, hashlib, os) to perform a minimal RFC 6455 WebSocket handshake and
frame-level read/write. Sublime Text 4 ships Python 3.8 and does not guarantee
access to the `websocket-client` third-party package on all platforms, so we
keep the implementation dependency-free.

Threading model:
    - connect() spawns a single reader thread.
    - Reader thread parses frames, dispatches responses to pending futures
      and events to listeners via sublime.set_timeout (when sublime is
      available). Tests pass a stub dispatcher.
    - Public API is safe to call from any thread. Do not call from the reader
      thread itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional

try:  # pragma: no cover - only available inside Sublime
    import sublime  # type: ignore
    _HAS_SUBLIME = True
except Exception:  # pragma: no cover
    sublime = None  # type: ignore
    _HAS_SUBLIME = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

CONNECT_TIMEOUT_SEC = 5.0
REQUEST_TIMEOUT_SEC = 30.0
MAX_BACKOFF_SEC = 16.0
MAX_RECONNECT_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Minimal WebSocket frame codec
# ---------------------------------------------------------------------------

class WebSocketError(Exception):
    """Raised for any WS protocol or transport error."""


def _make_accept_key(nonce_b64: str) -> str:
    digest = hashlib.sha1((nonce_b64 + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes or raise."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise WebSocketError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock: socket.socket) -> Optional[Dict[str, Any]]:
    """Read a single WebSocket frame. Returns dict with opcode/payload/fin."""
    header = _recv_exact(sock, 2)
    b1, b2 = header[0], header[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    length = b2 & 0x7F

    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]

    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    return {"fin": fin, "opcode": opcode, "payload": payload}


def _write_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    """Write a single masked client frame."""
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))  # FIN + opcode
    length = len(payload)
    mask_bit = 0x80  # clients must mask
    if length < 126:
        header.append(mask_bit | length)
    elif length < (1 << 16):
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    mask = os.urandom(4)
    header.extend(mask)
    masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + masked_payload)


def _perform_handshake(sock: socket.socket, host: str, port: int, path: str) -> None:
    nonce = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET {path} HTTP/1.1\r\n"
        "Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: {nonce}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).format(path=path, host=host, port=port, nonce=nonce)
    sock.sendall(request.encode("ascii"))

    # Read response headers until \r\n\r\n
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(1024)
        if not chunk:
            raise WebSocketError("handshake: connection closed")
        buf.extend(chunk)
        if len(buf) > 8192:
            raise WebSocketError("handshake: response too large")

    header_bytes, _, _ = buf.partition(b"\r\n\r\n")
    lines = header_bytes.decode("iso-8859-1").split("\r\n")
    if not lines or "101" not in lines[0]:
        raise WebSocketError("handshake: unexpected status: " + lines[0])

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    expected = _make_accept_key(nonce)
    if headers.get("sec-websocket-accept") != expected:
        raise WebSocketError("handshake: Sec-WebSocket-Accept mismatch")


# ---------------------------------------------------------------------------
# Pending request future
# ---------------------------------------------------------------------------

class _Future:
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[str] = None

    def set_result(self, value: Any) -> None:
        self.result = value
        self.event.set()

    def set_error(self, message: str) -> None:
        self.error = message
        self.event.set()

    def wait(self, timeout: float) -> Any:
        if not self.event.wait(timeout):
            raise WebSocketError("request timeout")
        if self.error is not None:
            raise WebSocketError(self.error)
        return self.result


# ---------------------------------------------------------------------------
# A6sClient
# ---------------------------------------------------------------------------

class A6sClient:
    """Thread-safe WebSocket client for the A6s daemon."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9876,
        path: str = "/ws",
        dispatcher: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.path = path
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._lock = threading.Lock()
        self._pending: Dict[str, _Future] = {}
        self._handlers: Dict[str, List[Callable[[Any], None]]] = {}
        self._req_id = 0
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._dispatcher = dispatcher or self._default_dispatcher

    # -- dispatch ----------------------------------------------------------

    @staticmethod
    def _default_dispatcher(fn: Callable[[], None]) -> None:
        if _HAS_SUBLIME:
            sublime.set_timeout(fn, 0)  # type: ignore
        else:
            fn()

    # -- connection --------------------------------------------------------

    def is_connected(self) -> bool:
        return self._connected

    def connect(self, timeout: float = CONNECT_TIMEOUT_SEC) -> None:
        if self._connected:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((self.host, self.port))
            _perform_handshake(sock, self.host, self.port, self.path)
        except (OSError, WebSocketError) as exc:
            try:
                sock.close()
            except Exception:
                pass
            raise WebSocketError("connect failed: " + str(exc))
        sock.settimeout(None)
        self._sock = sock
        self._connected = True
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="a6s-ws-reader")
        self._reader.start()
        self._emit("connected", {})

    def disconnect(self) -> None:
        self._stop.set()
        self._connected = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                _write_frame(sock, OP_CLOSE, b"")
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
        # Fail any pending requests
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _, fut in pending:
            fut.set_error("disconnected")
        self._emit("disconnected", {})

    def reconnect_with_backoff(self, max_attempts: int = MAX_RECONNECT_ATTEMPTS) -> bool:
        """Attempt reconnection with exponential backoff. Returns True on success."""
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                self.connect()
                return True
            except WebSocketError:
                if attempt == max_attempts:
                    return False
                time.sleep(min(delay, MAX_BACKOFF_SEC))
                delay *= 2
        return False

    # -- event subscription ------------------------------------------------

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable[[Any], None]) -> None:
        lst = self._handlers.get(event)
        if lst and handler in lst:
            lst.remove(handler)

    def _emit(self, event: str, data: Any) -> None:
        handlers = list(self._handlers.get(event, ()))
        if not handlers:
            return
        def _run() -> None:
            for h in handlers:
                try:
                    h(data)
                except Exception:
                    pass
        self._dispatcher(_run)

    # -- reader loop -------------------------------------------------------

    def _read_loop(self) -> None:
        sock = self._sock
        assert sock is not None
        buf = bytearray()
        current_opcode = None
        try:
            while not self._stop.is_set():
                frame = _read_frame(sock)
                if frame is None:
                    break
                op = frame["opcode"]
                if op == OP_CLOSE:
                    break
                if op == OP_PING:
                    try:
                        _write_frame(sock, OP_PONG, frame["payload"])
                    except Exception:
                        break
                    continue
                if op == OP_PONG:
                    continue
                if op in (OP_TEXT, OP_BINARY):
                    buf = bytearray(frame["payload"])
                    current_opcode = op
                elif op == OP_CONTINUATION:
                    buf.extend(frame["payload"])
                if frame["fin"] and current_opcode is not None:
                    payload = bytes(buf)
                    buf = bytearray()
                    current_opcode = None
                    self._handle_text(payload)
        except (WebSocketError, OSError):
            pass
        finally:
            self._connected = False
            try:
                sock.close()
            except Exception:
                pass
            self._emit("disconnected", {})

    def _handle_text(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return  # per spec: log and ignore
        if not isinstance(msg, dict):
            return
        # Response?
        mid = msg.get("id")
        if mid and mid in self._pending:
            with self._lock:
                fut = self._pending.pop(mid, None)
            if fut is not None:
                if msg.get("error"):
                    fut.set_error(str(msg.get("error")))
                else:
                    fut.set_result(msg.get("result"))
            return
        # Event
        evt = msg.get("type")
        if evt:
            self._emit(evt, msg.get("data", msg))

    # -- request/response --------------------------------------------------

    def _next_id(self) -> str:
        with self._lock:
            self._req_id += 1
            return "req_{}".format(self._req_id)

    def request(self, method: str, params: Any, timeout: float = REQUEST_TIMEOUT_SEC) -> Any:
        if not self._connected or self._sock is None:
            raise WebSocketError("not connected")
        mid = self._next_id()
        fut = _Future()
        with self._lock:
            self._pending[mid] = fut
        envelope = {"id": mid, "method": method, "params": params}
        data = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        try:
            _write_frame(self._sock, OP_TEXT, data)
        except (OSError, WebSocketError) as exc:
            with self._lock:
                self._pending.pop(mid, None)
            raise WebSocketError("send failed: " + str(exc))
        try:
            return fut.wait(timeout)
        finally:
            with self._lock:
                self._pending.pop(mid, None)

    # -- 13 protocol methods ----------------------------------------------

    def list_agents(self) -> List[Dict[str, Any]]:
        return self.request("agents.list", {}) or []

    def invoke_agent(self, agent_type: str, task: str, context: Any = None) -> str:
        result = self.request("agents.invoke", {
            "agentType": agent_type,
            "task": task,
            "context": context,
        })
        return result.get("executionId", "") if isinstance(result, dict) else ""

    def execution_status(self, execution_id: str) -> Dict[str, Any]:
        return self.request("execution.status", {"executionId": execution_id}) or {}

    def background_list(self) -> List[Dict[str, Any]]:
        return self.request("background.list", {}) or []

    def background_launch(self, task: str, agent_type: str) -> str:
        result = self.request("background.launch", {"task": task, "agentType": agent_type})
        return result.get("taskId", "") if isinstance(result, dict) else ""

    def background_cancel(self, task_id: str) -> None:
        self.request("background.cancel", {"taskId": task_id})

    def background_output(self, task_id: str) -> str:
        return self.request("background.output", {"taskId": task_id}) or ""

    def artifacts_preview(self, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.request("artifacts.preview", {"artifacts": artifacts}) or {"files": []}

    def artifacts_apply(self, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.request("artifacts.apply", {"artifacts": artifacts}) or {
            "applied": 0, "skipped": 0, "errors": [],
        }

    def explain_code(self, code: str, language: str, file_path: str) -> str:
        return self.request("code.explain", {
            "code": code, "language": language, "filePath": file_path,
        }) or ""

    def refactor_code(self, code: str, language: str, file_path: str, instructions: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.request("code.refactor", {
            "code": code, "language": language, "filePath": file_path,
            "instructions": instructions,
        }) or []

    def generate_tests(self, code: str, language: str, file_path: str) -> List[Dict[str, Any]]:
        return self.request("code.generateTests", {
            "code": code, "language": language, "filePath": file_path,
        }) or []

    def review_code(self, code: str, language: str, file_path: str, review_type: str) -> Dict[str, Any]:
        return self.request("code.review", {
            "code": code, "language": language, "filePath": file_path,
            "reviewType": review_type,
        }) or {"issues": [], "summary": ""}

    # -- fleet methods -------------------------------------------------------

    def fleet_list(self) -> List[Dict[str, Any]]:
        return self.request("fleet.list", {}) or []

    def fleet_status(self, agent_id: str) -> Dict[str, Any]:
        return self.request("fleet.status", {"agentId": agent_id}) or {}

    def fleet_command(self, agent_id: str, command: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request("fleet.command", {
            "agentId": agent_id,
            "command": command,
            "params": params or {},
        }) or {}

    # -- workflow methods -----------------------------------------------------

    def workflow_list(self, domain: str = "") -> List[Dict[str, Any]]:
        p: Dict[str, Any] = {}
        if domain:
            p["domain"] = domain
        return self.request("workflows.list", p) or []

    def workflow_run(self, workflow_id: str, inputs: Optional[Dict[str, Any]] = None) -> str:
        result = self.request("workflows.run", {
            "workflowId": workflow_id,
            "inputs": inputs or {},
        })
        return result.get("executionId", "") if isinstance(result, dict) else ""

    def workflow_status(self, execution_id: str) -> Dict[str, Any]:
        return self.request("workflows.status", {"executionId": execution_id}) or {}

    def workflow_cancel(self, execution_id: str) -> None:
        self.request("workflows.cancel", {"executionId": execution_id})
