from __future__ import annotations

from dataclasses import dataclass, field

from flow_ai.core.style_models import StyleIntent

from flow_ai.format.ast_intent_builder import IntentBuildContext, build_style_intent
from flow_ai.format.ast_reader import ParagraphRecord
from flow_ai.format.visual_fingerprint import build_fingerprint, fingerprint_key


@dataclass
class FormatCluster:

    cluster_id: str
    fingerprint: tuple[str, ...]
    members: list[ParagraphRecord] = field(default_factory=list)
    style_intent: StyleIntent | None = None
    representative: ParagraphRecord | None = None


def cluster_paragraphs(
    paragraphs: list[ParagraphRecord],
    intent_context: IntentBuildContext | None = None,
) -> list[FormatCluster]:
    buckets: dict[str, FormatCluster] = {}
    for record in paragraphs:
        intent = build_style_intent(record, intent_context)
        fingerprint = build_fingerprint(record, intent)
        key = fingerprint_key(fingerprint)
        if key not in buckets:
            buckets[key] = FormatCluster(cluster_id=key, fingerprint=fingerprint)
        buckets[key].members.append(record)

    clusters = list(buckets.values())
    for cluster in clusters:
        cluster.representative = _pick_representative(cluster.members)
        if cluster.representative is not None:
            cluster.style_intent = build_style_intent(
                cluster.representative,
                intent_context,
            )
    clusters.sort(key=lambda item: (-len(item.members), item.cluster_id))
    return clusters


def _pick_representative(members: list[ParagraphRecord]) -> ParagraphRecord | None:
    if not members:
        return None
    scored = sorted(
        members,
        key=lambda record: (
            record.features.dominant_font_size or 0.0,
            record.features.text_length,
        ),
        reverse=True,
    )
    return scored[0]


def cluster_map(clusters: list[FormatCluster]) -> dict[str, FormatCluster]:
    return {cluster.cluster_id: cluster for cluster in clusters}


def cluster_for_record(
    record: ParagraphRecord,
    clusters: list[FormatCluster],
    intent_context: IntentBuildContext | None = None,
) -> FormatCluster | None:
    intent = build_style_intent(record, intent_context)
    key = fingerprint_key(build_fingerprint(record, intent))
    for cluster in clusters:
        if cluster.cluster_id == key:
            return cluster
    return None
