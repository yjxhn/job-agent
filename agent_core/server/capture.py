"""Browser-capture HTTP server for Zhilian job ingestion.

Listens on 127.0.0.1:8778, receives jobs captured by the Tampermonkey
userscript from real browser sessions (bypassing Akamai anti-bot), normalizes
via ZhilianAdapter, deduplicates, and persists to the jobs table.

Endpoints:
  POST /zhilian/capture   — ingest captured jobs (JSON: {jobs, kw, page, captured_at})
  GET  /zhilian/capture/status — return capture stats (count, last_captured_at)

Security: binds 127.0.0.1 only. Optional token auth via X-Capture-Token header
or ?token= query param (disabled by default in dev mode).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from agent_core.platforms.zhilian import ZhilianAdapter

logger = logging.getLogger(__name__)

# Global stats (thread-safe via lock)
_stats_lock = threading.Lock()
_stats: dict[str, Any] = {
    "total_captured": 0,
    "total_ingested": 0,
    "total_deduped": 0,
    "last_captured_at": "",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CaptureHandler(BaseHTTPRequestHandler):
    """Minimal handler for browser-captured Zhilian jobs."""

    # Class-level config (set by start_capture_server)
    db_path: str = "data/agent.db"
    capture_token: str = ""  # Empty = dev mode (no auth)

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        """Return True if authorized (or dev mode)."""
        token = self.capture_token
        if not token:
            return True  # Dev mode
        # Check header
        header_token = self.headers.get("X-Capture-Token", "")
        if header_token == token:
            return True
        # Check query param
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(self.path).query)
        query_tokens = qs.get("token", [])
        if query_tokens and query_tokens[0] == token:
            return True
        return False

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8", "replace"))

    def do_OPTIONS(self) -> None:
        """CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Capture-Token")
        self.end_headers()

    def do_GET(self) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(self.path)

        if parsed.path == "/zhilian/capture/status":
            if not self._check_auth():
                self._json({"error": "unauthorized"}, 401)
                return
            with _stats_lock:
                self._json(dict(_stats))

        elif parsed.path == "/health":
            self._json({"status": "ok", "service": "zhilian-capture"})

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(self.path)

        if parsed.path != "/zhilian/capture":
            self._json({"error": "not found"}, 404)
            return

        if not self._check_auth():
            self._json({"error": "unauthorized"}, 401)
            return

        try:
            body = self._read_body()
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON body"}, 400)
            return

        # Validate input
        jobs_raw = body.get("jobs")
        if not isinstance(jobs_raw, list):
            self._json({"error": "jobs must be a list"}, 400)
            return

        if len(jobs_raw) == 0:
            self._json({"ok": True, "ingested": 0, "deduped": 0, "total": 0})
            return

        # Basic per-item validation
        for item in jobs_raw:
            if not isinstance(item, dict):
                self._json({"error": "each job must be a dict (Zhilian API data.list item)"}, 400)
                return
            if not item.get("name") and not item.get("positionURL"):
                self._json(
                    {
                        "error": "each job must have at least 'name' or 'positionURL'",
                        "bad_item": item,
                    },
                    400,
                )
                return

        kw = body.get("kw", "")
        page = body.get("page", 0)
        captured_at = body.get("captured_at", _now_iso())

        logger.info(
            "[Capture] Received %d jobs (kw=%s page=%s captured_at=%s)",
            len(jobs_raw),
            kw,
            page,
            captured_at,
        )

        ingested, deduped = _ingest_jobs(jobs_raw, self.db_path)

        with _stats_lock:
            _stats["total_captured"] += len(jobs_raw)
            _stats["total_ingested"] += ingested
            _stats["total_deduped"] += deduped
            _stats["last_captured_at"] = captured_at

        self._json(
            {
                "ok": True,
                "ingested": ingested,
                "deduped": deduped,
                "total": ingested + deduped,
            }
        )

    def log_message(self, format, *args):
        """Route server access logs through Python logging."""
        logger.debug("[CaptureServer] " + format % args)


def _ingest_jobs(items: list[dict], db_path: str) -> tuple[int, int]:
    """Normalize and persist Zhilian API data.list items.

    Returns (ingested, deduped) counts.
    """
    adapter = ZhilianAdapter()
    now = _now_iso()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    ingested = 0
    deduped = 0

    for item in items:
        try:
            job = adapter._api_item_to_job(item)
        except Exception:
            logger.debug("[Capture] Failed to map item, skipping")
            continue

        if not job.id:
            continue

        # Check duplicate by id
        existing = conn.execute("SELECT id FROM jobs WHERE id=?", (job.id,)).fetchone()
        if existing:
            # Update last_seen timestamp
            conn.execute("UPDATE jobs SET last_seen=? WHERE id=?", (now, job.id))
            deduped += 1
            continue

        # Insert new job
        record = job.to_storage()
        row = record.to_db_row()
        if not row.get("first_seen"):
            row["first_seen"] = now
        if not row.get("last_seen"):
            row["last_seen"] = now

        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT OR REPLACE INTO jobs ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )
        ingested += 1

    conn.commit()
    conn.close()

    logger.info("[Capture] ingested=%d deduped=%d", ingested, deduped)
    return ingested, deduped


def start_capture_server(
    port: int = 8778,
    db_path: str = "data/agent.db",
    token: str = "",
) -> None:
    """Start the browser-capture HTTP server (blocking).

    Args:
        port: Listen port (default 8778).
        db_path: Path to SQLite database.
        token: Optional auth token. Empty string = dev mode (no auth).
    """
    # Ensure DB directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    CaptureHandler.db_path = db_path
    CaptureHandler.capture_token = token

    server = HTTPServer(("127.0.0.1", port), CaptureHandler)
    host = "127.0.0.1"

    auth_note = " (auth enabled)" if token else " (dev mode, no auth)"
    print(f"\n[Zhilian Capture] Listening on http://{host}:{port}{auth_note}")
    print(f"[Zhilian Capture] DB: {db_path}")
    print()
    print("Usage:")
    print("  1. 安装 Tampermonkey 浏览器扩展")
    print("  2. 导入 tools/zhilian_capture.user.js")
    print("  3. 浏览器打开 https://sou.zhaopin.com/ 登录并搜索")
    print("  4. 职位自动捕获入库，然后 Ctrl+C 停止服务")
    print("  5. 运行 job-agent pipeline 进行后续流程")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Zhilian Capture] Shutting down...")
        server.shutdown()
        # Print final stats
        with _stats_lock:
            s = dict(_stats)
        print(
            f"[Zhilian Capture] Session stats: captured={s['total_captured']} "
            f"ingested={s['total_ingested']} deduped={s['total_deduped']}"
        )
