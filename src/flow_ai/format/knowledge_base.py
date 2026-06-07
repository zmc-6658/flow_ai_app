from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path


_DEFAULT_DB_PATH = Path.home() / ".flow_ai" / "slot_signatures.db"

_DDL = """
CREATE TABLE IF NOT EXISTS slot_signatures (
    fingerprint_key TEXT NOT NULL,
    section         TEXT NOT NULL DEFAULT 'body',
    slot_id         TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT 'thesis',
    count           INTEGER NOT NULL DEFAULT 1,
    last_confirmed  TEXT,
    PRIMARY KEY (fingerprint_key, section, slot_id)
);
CREATE TABLE IF NOT EXISTS upload_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint_key TEXT NOT NULL,
    section         TEXT NOT NULL DEFAULT 'body',
    slot_id         TEXT NOT NULL,
    install_id      TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT 'thesis',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS content_role_signatures (
    fingerprint_key TEXT NOT NULL,
    section         TEXT NOT NULL DEFAULT 'body',
    content_role    TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT 'thesis',
    count           INTEGER NOT NULL DEFAULT 1,
    reject_count    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'learning',
    last_confirmed  TEXT,
    PRIMARY KEY (fingerprint_key, section, content_role)
);
CREATE TABLE IF NOT EXISTS anchor_text_signatures (
    anchor_text_normalized TEXT NOT NULL,
    content_role           TEXT NOT NULL,
    doc_type               TEXT NOT NULL DEFAULT 'thesis',
    count                  INTEGER NOT NULL DEFAULT 1,
    reject_count           INTEGER NOT NULL DEFAULT 0,
    status                 TEXT NOT NULL DEFAULT 'learning',
    last_confirmed         TEXT,
    PRIMARY KEY (anchor_text_normalized, content_role)
);
CREATE TABLE IF NOT EXISTS content_role_upload_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint_key TEXT NOT NULL,
    section         TEXT NOT NULL DEFAULT 'body',
    content_role    TEXT NOT NULL,
    install_id      TEXT NOT NULL,
    doc_type        TEXT NOT NULL DEFAULT 'thesis',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CONFIDENCE_BASE = 0.5
_CONFIDENCE_STEP = 0.05
_MIN_COUNT_FOR_HIT = 2


def _kb_confidence(count: int) -> float:
    return min(1.0, _CONFIDENCE_BASE + _CONFIDENCE_STEP * count)


def _normalize_anchor_text(text: str) -> str:
    import re

    return re.sub(r"\s+", "", text.strip().lower())


def _open(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.executescript(_DDL)
    conn.commit()
    return conn


class KnowledgeBase:
    """Local SQLite store for confirmed (fingerprint_key, section) → slot_id mappings."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._conn = _open(self._db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def lookup(self, fingerprint_key: str, section: str) -> tuple[str, float] | None:
        """Return (slot_id, confidence) for the highest-count entry, or None."""
        row = self._conn.execute(
            """
            SELECT slot_id, count
            FROM slot_signatures
            WHERE fingerprint_key = ? AND section = ?
            ORDER BY count DESC
            LIMIT 1
            """,
            (fingerprint_key, section),
        ).fetchone()
        if row is None:
            return None
        slot_id, count = row
        if count < _MIN_COUNT_FOR_HIT:
            return None
        return slot_id, _kb_confidence(count)

    def record_confirmation(
        self,
        fingerprint_key: str,
        section: str,
        slot_id: str,
        doc_type: str = "thesis",
        install_id: str | None = None,
    ) -> None:
        """Upsert a confirmation into slot_signatures and enqueue for upload."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO slot_signatures (fingerprint_key, section, slot_id, doc_type, count, last_confirmed)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT (fingerprint_key, section, slot_id)
            DO UPDATE SET count = count + 1, last_confirmed = excluded.last_confirmed
            """,
            (fingerprint_key, section, slot_id, doc_type, now),
        )
        eff_install_id = install_id or "local"
        self._conn.execute(
            """
            INSERT INTO upload_queue (fingerprint_key, section, slot_id, install_id, doc_type, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (fingerprint_key, section, slot_id, eff_install_id, doc_type, now),
        )
        self._conn.commit()

    def merge_cloud(self, rows: list[dict]) -> None:
        """Merge downloaded cloud aggregates into local slot_signatures.

        Each row: {"fingerprint_key", "section", "slot_id", "device_count"}.
        Cloud count is authoritative when higher than local.
        """
        if rows:
            self._conn.executemany(
                """
                INSERT INTO slot_signatures (fingerprint_key, section, slot_id, count)
                VALUES (:fingerprint_key, :section, :slot_id, :device_count)
                ON CONFLICT (fingerprint_key, section, slot_id)
                DO UPDATE SET count = MAX(count, excluded.count)
                """,
                rows,
            )
            self._conn.commit()

    def pending_uploads(self) -> list[dict]:
        """Return all pending upload_queue rows as dicts."""
        cur = self._conn.execute(
            "SELECT id, fingerprint_key, section, slot_id, install_id, doc_type FROM upload_queue WHERE status = 'pending'"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_uploaded(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        placeholders = ",".join("?" * len(row_ids))
        self._conn.execute(
            f"UPDATE upload_queue SET status = 'uploaded' WHERE id IN ({placeholders})",
            row_ids,
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def lookup_content_role(self, fingerprint_key: str, section: str) -> tuple[str, float] | None:
        row = self._conn.execute(
            """
            SELECT content_role, count, status
            FROM content_role_signatures
            WHERE fingerprint_key = ? AND section = ? AND status != 'blocked'
            ORDER BY count DESC
            LIMIT 1
            """,
            (fingerprint_key, section),
        ).fetchone()
        if row is None:
            return None
        role, count, status = row
        if count < _MIN_COUNT_FOR_HIT and status == "learning":
            return None
        return role, _kb_confidence(count)

    def lookup_anchor_text(self, text: str) -> tuple[str, float] | None:
        normalized = _normalize_anchor_text(text)
        row = self._conn.execute(
            """
            SELECT content_role, count, status
            FROM anchor_text_signatures
            WHERE anchor_text_normalized = ? AND status != 'blocked'
            ORDER BY count DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        role, count, status = row
        if count < _MIN_COUNT_FOR_HIT and status == "learning":
            return None
        return role, _kb_confidence(count)

    def record_content_role(
        self,
        fingerprint_key: str,
        section: str,
        content_role: str,
        *,
        doc_type: str = "thesis",
        install_id: str | None = None,
        rejected: bool = False,
    ) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        if rejected:
            self._conn.execute(
                """
                INSERT INTO content_role_signatures
                    (fingerprint_key, section, content_role, doc_type, count, reject_count, last_confirmed)
                VALUES (?, ?, ?, ?, 0, 1, ?)
                ON CONFLICT (fingerprint_key, section, content_role)
                DO UPDATE SET reject_count = reject_count + 1, last_confirmed = excluded.last_confirmed
                """,
                (fingerprint_key, section, content_role, doc_type, now),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO content_role_signatures
                    (fingerprint_key, section, content_role, doc_type, count, last_confirmed)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT (fingerprint_key, section, content_role)
                DO UPDATE SET count = count + 1, last_confirmed = excluded.last_confirmed
                """,
                (fingerprint_key, section, content_role, doc_type, now),
            )
            self._promote_content_role(fingerprint_key, section, content_role)
            eff_install_id = install_id or "local"
            self._conn.execute(
                """
                INSERT INTO content_role_upload_queue
                    (fingerprint_key, section, content_role, install_id, doc_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (fingerprint_key, section, content_role, eff_install_id, doc_type, now),
            )
        self._conn.commit()

    def record_anchor_text(
        self,
        text: str,
        content_role: str,
        *,
        doc_type: str = "thesis",
        install_id: str | None = None,
        rejected: bool = False,
    ) -> None:
        from datetime import datetime, timezone

        normalized = _normalize_anchor_text(text)
        now = datetime.now(timezone.utc).isoformat()
        if rejected:
            self._conn.execute(
                """
                INSERT INTO anchor_text_signatures
                    (anchor_text_normalized, content_role, doc_type, count, reject_count, last_confirmed)
                VALUES (?, ?, ?, 0, 1, ?)
                ON CONFLICT (anchor_text_normalized, content_role)
                DO UPDATE SET reject_count = reject_count + 1, last_confirmed = excluded.last_confirmed
                """,
                (normalized, content_role, doc_type, now),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO anchor_text_signatures
                    (anchor_text_normalized, content_role, doc_type, count, last_confirmed)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT (anchor_text_normalized, content_role)
                DO UPDATE SET count = count + 1, last_confirmed = excluded.last_confirmed
                """,
                (normalized, content_role, doc_type, now),
            )
        self._conn.commit()

    def _promote_content_role(self, fingerprint_key: str, section: str, content_role: str) -> None:
        row = self._conn.execute(
            """
            SELECT count, reject_count FROM content_role_signatures
            WHERE fingerprint_key = ? AND section = ? AND content_role = ?
            """,
            (fingerprint_key, section, content_role),
        ).fetchone()
        if row is None:
            return
        count, reject_count = row
        total = count + reject_count
        if total == 0:
            return
        if reject_count / total > 0.5:
            status = "blocked"
        elif count >= 6 and count / max(reject_count, 1) >= 4:
            status = "reliable"
        elif count >= 3:
            status = "tentative"
        else:
            status = "learning"
        self._conn.execute(
            """
            UPDATE content_role_signatures SET status = ?
            WHERE fingerprint_key = ? AND section = ? AND content_role = ?
            """,
            (status, fingerprint_key, section, content_role),
        )

    def pending_content_role_uploads(self) -> list[dict]:
        cur = self._conn.execute(
            """
            SELECT id, fingerprint_key, section, content_role, install_id, doc_type
            FROM content_role_upload_queue WHERE status = 'pending'
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_content_role_uploaded(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        placeholders = ",".join("?" * len(row_ids))
        self._conn.execute(
            f"UPDATE content_role_upload_queue SET status = 'uploaded' WHERE id IN ({placeholders})",
            row_ids,
        )
        self._conn.commit()


@dataclass
class SeedEntry:
    fingerprint_key: str
    section: str
    slot_id: str
    doc_type: str = "thesis"
    count: int = 50


def seed_from_entries(entries: list[SeedEntry], db_path: Path | None = None) -> int:
    """Write seed entries into the knowledge base. Returns count written."""
    kb = KnowledgeBase(db_path)
    if entries:
        kb._conn.executemany(
            """
            INSERT INTO slot_signatures (fingerprint_key, section, slot_id, doc_type, count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (fingerprint_key, section, slot_id)
            DO UPDATE SET count = MAX(count, excluded.count)
            """,
            [(e.fingerprint_key, e.section, e.slot_id, e.doc_type, e.count) for e in entries],
        )
        kb._conn.commit()
    written = len(entries)
    kb.close()
    return written


def open_thread_local(db_path: Path | None = None) -> KnowledgeBase:
    """Open a fresh KnowledgeBase connection for use in a background thread."""
    return KnowledgeBase(db_path or _DEFAULT_DB_PATH)
