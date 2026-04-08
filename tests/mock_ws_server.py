"""
Minimal RFC 6455 WebSocket mock server used by client tests.

Implements:
    - handshake with Sec-WebSocket-Accept
    - text frame read/write (unmasked server -> client, masked client -> server)
    - a handler callback that receives each JSON message and returns responses
      or pushes events.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from typing import Any, Callable, List, Optional, Tuple

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf.extend(chunk)
    return bytes(buf)


def _accept_key(nonce: str) -> str:
    return base64.b64encode(hashlib.sha1((nonce + WS_GUID).encode()).digest()).decode()


def _read_frame(sock: socket.socket) -> Tuple[int, bytes]:
    header = _recv_exact(sock, 2)
    b1, b2 = header[0], header[1]
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
    return opcode, payload


def _write_text(sock: socket.socket, payload: bytes) -> None:
    header = bytearray([0x81])  # FIN + text
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    sock.sendall(bytes(header) + payload)


def _write_close(sock: socket.socket) -> None:
    try:
        sock.sendall(bytes([0x88, 0x00]))
    except Exception:
        pass


class MockWebSocketServer:
    """Threaded mock WebSocket server for tests."""

    def __init__(
        self,
        handler: Optional[Callable[[dict], Any]] = None,
        skip_handshake: bool = False,
        drop_before_handshake: bool = False,
    ) -> None:
        self.handler = handler or (lambda m: {"id": m.get("id"), "result": None})
        self.skip_handshake = skip_handshake
        self.drop_before_handshake = drop_before_handshake
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = threading.Event()
        self.clients: List[socket.socket] = []
        self.pending_events: List[dict] = []
        self._event_lock = threading.Lock()

    def start(self) -> "MockWebSocketServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except Exception:
            pass
        for c in list(self.clients):
            try:
                c.close()
            except Exception:
                pass

    def push_event(self, event: dict) -> None:
        """Queue an event to send after the next request."""
        with self._event_lock:
            self.pending_events.append(event)

    def push_event_now(self, event: dict) -> None:
        for c in list(self.clients):
            try:
                _write_text(c, json.dumps(event).encode("utf-8"))
            except Exception:
                pass

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    conn, _addr = self.sock.accept()
                except OSError:
                    return
                self.clients.append(conn)
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
        except Exception:
            pass

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            if self.drop_before_handshake:
                conn.close()
                return
            # Read HTTP headers
            buf = bytearray()
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                buf.extend(chunk)
            if self.skip_handshake:
                return
            lines = buf.decode("iso-8859-1").split("\r\n")
            nonce = ""
            for line in lines:
                if line.lower().startswith("sec-websocket-key:"):
                    nonce = line.split(":", 1)[1].strip()
            accept = _accept_key(nonce)
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).format(accept=accept)
            conn.sendall(response.encode("ascii"))
            # Message loop
            while not self._stop.is_set():
                try:
                    opcode, payload = _read_frame(conn)
                except (ConnectionError, OSError):
                    return
                if opcode == 0x8:  # close
                    _write_close(conn)
                    return
                if opcode != 0x1:
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8"))
                except Exception:
                    continue
                response_obj = self.handler(msg)
                if response_obj is not None:
                    _write_text(conn, json.dumps(response_obj).encode("utf-8"))
                with self._event_lock:
                    evts = list(self.pending_events)
                    self.pending_events.clear()
                for evt in evts:
                    _write_text(conn, json.dumps(evt).encode("utf-8"))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
