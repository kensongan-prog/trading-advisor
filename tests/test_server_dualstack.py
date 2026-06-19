"""
test_server_dualstack.py — the control server must answer over IPv4 AND IPv6.

Bug (2026-06-15): server bound IPv4-only (0.0.0.0), so clients reaching it over
IPv6 — `localhost` → ::1 on macOS, or a Tailscale MagicDNS/IPv6 address — got
connection-refused and the dashboard looked down. DualStackHTTPServer binds `::`
with IPV6_V6ONLY=0 so one socket serves both families. This pins that: a server
bound to `::` answers /api/status via both 127.0.0.1 and ::1.
"""
import http.client
import socket
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"))
import server  # noqa: E402


def _status(host, port):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/status")
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


def test_dualstack_server_answers_v4_and_v6():
    srv = server.DualStackHTTPServer(("::", 0), server.Handler)
    # IPV6_V6ONLY must be off or v4-mapped clients (127.0.0.1) can't connect.
    assert srv.socket.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        code4, _ = _status("127.0.0.1", port)
        assert code4 == 200, "IPv4 (127.0.0.1) should reach the dual-stack socket"
        if socket.has_ipv6:
            code6, _ = _status("::1", port)
            assert code6 == 200, "IPv6 (::1) should reach the dual-stack socket"
    finally:
        srv.shutdown()
        srv.server_close()


def test_address_family_is_ipv6():
    assert server.DualStackHTTPServer.address_family == socket.AF_INET6
