"""Small HTTP helpers shared by the dashboard server (serve.py).

Kept separate so the request-handler file stays focused on routing and
business handlers. All functions are intentionally framework-free (stdlib
http.server only).
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler
from typing import Any


class _AuthRequired(Exception):
    """Raised by _require_auth to abort request handling when auth fails.

    Caught in do_GET/do_POST/do_DELETE to skip the normal error path (the
    401 response is already sent inside _require_auth).
    """

    pass


def _get_int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    """Safely parse an integer query parameter from parse_qs output."""
    try:
        val = int(params.get(key, [str(default)])[0])
    except (ValueError, TypeError):
        val = default
    return val


def _table_exists(conn, name: str) -> bool:
    """Check if a table exists in the SQLite database."""
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def _authenticate(request: BaseHTTPRequestHandler) -> tuple[bool, str | None]:
    """Check Bearer token against AGENT_DASHBOARD_TOKEN env var.

    Returns (allowed, error_message). Allowed is True when auth succeeds or
    auth is disabled (env var unset/empty).
    """
    expected = os.environ.get("AGENT_DASHBOARD_TOKEN", "").strip()
    if not expected:
        return True, None  # dev mode -- no auth required

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "Missing or invalid Authorization header"
    token = auth_header[7:]
    if token != expected:
        return False, "Invalid token"
    return True, None


def _send_json(
    handler: BaseHTTPRequestHandler,
    data: Any,
    status: int = 200,
) -> None:
    """Serialize data as JSON and write the HTTP response."""
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_html(handler: BaseHTTPRequestHandler, html: str, status: int = 200) -> None:
    """Write an HTML response."""
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    """Read a JSON request body with encoding tolerance.

    Decodes the raw bytes as UTF-8 first; on failure falls back to
    latin-1 (never raises on arbitrary bytes) so GBK-encoded Chinese
    bodies from Windows curl/scripts don't 500 the endpoint.
    """
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # GBK bodies decode as mojibake under latin-1; retry with GBK.
        try:
            return json.loads(raw.decode("gbk"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}


def _send_error(
    handler: BaseHTTPRequestHandler,
    status: int,
    message: str,
    details: str | None = None,
) -> None:
    """Send a JSON error response."""
    payload: dict[str, Any] = {"error": message}
    if details:
        payload["details"] = details
    _send_json(handler, payload, status=status)
