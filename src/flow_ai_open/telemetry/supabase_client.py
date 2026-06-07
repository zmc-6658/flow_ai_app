"""Supabase REST telemetry client for fingerprint slot voting.

Upload path:
    upload_pending(kb) → drain upload_queue → POST /rest/v1/fingerprint_votes

Download path:
    download_top_signatures() → GET aggregated view → list[dict]

Both functions fail silently on network errors to never block the main flow.

Supabase table (create once in Supabase dashboard):
----------------------------------------------------
CREATE TABLE fingerprint_votes (
  fingerprint_key TEXT        NOT NULL,
  section         TEXT        NOT NULL DEFAULT 'body',
  slot_id         TEXT        NOT NULL,
  install_id      TEXT        NOT NULL,
  doc_type        TEXT        DEFAULT 'thesis',
  voted_at        TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (fingerprint_key, section, slot_id, install_id)
);
ALTER TABLE fingerprint_votes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "anon_read"   ON fingerprint_votes FOR SELECT USING (true);
CREATE POLICY "anon_insert" ON fingerprint_votes FOR INSERT WITH CHECK (true);

Aggregation view used for downloads:
----------------------------------------------------
CREATE VIEW fingerprint_votes_agg AS
SELECT fingerprint_key, section, slot_id,
       COUNT(DISTINCT install_id) AS device_count
FROM fingerprint_votes
GROUP BY fingerprint_key, section, slot_id;
"""
from __future__ import annotations

import logging
from typing import Any

from flow_ai_open.config_loader import get_supabase_url, get_supabase_anon_key

logger = logging.getLogger(__name__)

# 配置来源优先级：环境变量 > config.yaml > 空值（跳过上传）
_SUPABASE_URL: str = get_supabase_url()
_SUPABASE_ANON_KEY: str = get_supabase_anon_key()

_VOTES_TABLE = "fingerprint_votes"
_AGG_VIEW = "fingerprint_votes_agg"
_DOWNLOAD_LIMIT = 500
_MIN_DEVICE_COUNT = 3
_UPLOAD_BATCH_SIZE = 50
_TIMEOUT_S = 8.0


def _headers() -> dict[str, str]:
    return {
        "apikey": _SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {_SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _is_configured() -> bool:
    return bool(_SUPABASE_URL and _SUPABASE_ANON_KEY)


def upload_pending(kb: Any) -> int:
    """Upload pending queue rows from the KnowledgeBase.

    Args:
        kb: A KnowledgeBase instance (thread-local, freshly opened).

    Returns:
        Number of rows successfully uploaded.
    """
    if not _is_configured():
        logger.debug("Supabase not configured — skipping upload")
        return 0

    pending = kb.pending_uploads()
    if not pending:
        return 0

    uploaded_ids: list[int] = []
    try:
        import httpx

        with httpx.Client(timeout=_TIMEOUT_S) as client:
            for i in range(0, len(pending), _UPLOAD_BATCH_SIZE):
                batch = pending[i : i + _UPLOAD_BATCH_SIZE]
                payload = [
                    {
                        "fingerprint_key": row["fingerprint_key"],
                        "section": row["section"],
                        "slot_id": row["slot_id"],
                        "install_id": row["install_id"],
                        "doc_type": row["doc_type"],
                    }
                    for row in batch
                ]
                resp = client.post(
                    f"{_SUPABASE_URL}/rest/v1/{_VOTES_TABLE}",
                    headers=_headers(),
                    json=payload,
                )
                if resp.status_code in (200, 201, 204):
                    uploaded_ids.extend(row["id"] for row in batch)
                else:
                    logger.warning("Supabase upload batch failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Supabase upload error (will retry later): %s", exc)

    if uploaded_ids:
        kb.mark_uploaded(uploaded_ids)

    return len(uploaded_ids)


def download_top_signatures() -> list[dict]:
    """Download aggregated top-voted signatures from Supabase.

    Returns:
        List of dicts with keys: fingerprint_key, section, slot_id, device_count.
        Returns empty list on any error.
    """
    if not _is_configured():
        logger.debug("Supabase not configured — skipping download")
        return []

    try:
        import httpx

        params = {
            "select": "fingerprint_key,section,slot_id,device_count",
            "device_count": f"gte.{_MIN_DEVICE_COUNT}",
            "order": "device_count.desc",
            "limit": str(_DOWNLOAD_LIMIT),
        }
        with httpx.Client(timeout=_TIMEOUT_S) as client:
            resp = client.get(
                f"{_SUPABASE_URL}/rest/v1/{_AGG_VIEW}",
                headers={
                    "apikey": _SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {_SUPABASE_ANON_KEY}",
                },
                params=params,
            )
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Supabase download failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Supabase download error: %s", exc)

    return []


_CONTENT_ROLE_TABLE = "content_role_votes"
_CONTENT_ROLE_AGG = "content_role_votes_agg"


def upload_content_role_pending(kb: Any) -> int:
    """Upload pending content_role_upload_queue rows. Fails silently."""
    if not _is_configured():
        return 0
    pending = kb.pending_content_role_uploads()
    if not pending:
        return 0
    uploaded_ids: list[int] = []
    try:
        import httpx

        with httpx.Client(timeout=_TIMEOUT_S) as client:
            for i in range(0, len(pending), _UPLOAD_BATCH_SIZE):
                batch = pending[i : i + _UPLOAD_BATCH_SIZE]
                payload = [
                    {
                        "fingerprint_key": row["fingerprint_key"],
                        "section": row["section"],
                        "content_role": row["content_role"],
                        "install_id": row["install_id"],
                        "doc_type": row["doc_type"],
                    }
                    for row in batch
                ]
                resp = client.post(
                    f"{_SUPABASE_URL}/rest/v1/{_CONTENT_ROLE_TABLE}",
                    headers=_headers(),
                    json=payload,
                )
                if resp.status_code in (200, 201, 204):
                    uploaded_ids.extend(row["id"] for row in batch)
                else:
                    logger.warning(
                        "Supabase content_role upload failed: %s %s",
                        resp.status_code,
                        resp.text[:200],
                    )
    except Exception as exc:
        logger.warning("Supabase content_role upload error: %s", exc)
    if uploaded_ids:
        kb.mark_content_role_uploaded(uploaded_ids)
    return len(uploaded_ids)
