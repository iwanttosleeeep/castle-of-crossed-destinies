import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _database_path() -> Path:
    configured = os.getenv("CASTLE_DB_PATH")
    return Path(configured) if configured else Path(__file__).resolve().parents[1] / "castle.db"


class CaseStore:
    def __init__(self, path: Path | None = None):
        self.path = path or _database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS cases (
                        id TEXT PRIMARY KEY,
                        token_hash TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def create(self, profile: dict, systems: list[str]) -> tuple[dict, str]:
        case_id = f"CCD-{datetime.now():%y%m%d}-{uuid4().hex[:8].upper()}"
        token = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "case_id": case_id,
            "profile": profile,
            "systems": systems,
            "status": "awaiting_uploads",
            "extractions": {},
            "confirmed_facts": {},
            "reports": {},
            "tribunal": None,
            "debates": [],
            "created_at": now,
            "updated_at": now,
        }
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO cases (id, token_hash, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (case_id, self._hash(token), json.dumps(payload, ensure_ascii=False), now, now),
                )
        return payload, token

    def get(self, case_id: str, token: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT token_hash, payload FROM cases WHERE id = ?", (case_id,)
            ).fetchone()
        if not row or not token or not hmac.compare_digest(row[0], self._hash(token)):
            return None
        return json.loads(row[1])

    def save(self, payload: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload["updated_at"] = now
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "UPDATE cases SET payload = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False), now, payload["case_id"]),
                )

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
