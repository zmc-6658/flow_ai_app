from __future__ import annotations

from typing import Iterator

from pydantic import Field

from flow_ai.core.ast_models import NodeID, OpaqueNode, OpaqueType, StrictASTModel


class AssetBlob(StrictASTModel):

    id: NodeID = Field(description="Stable asset ID referenced by an OpaqueNode.")
    opaque_type: OpaqueType = Field(description="The opaque node type this asset restores.")
    payload: bytes | None = Field(
        default=None,
        description="Binary payload for assets such as images.",
    )
    xml: str | None = Field(
        default=None,
        description="Raw OOXML payload for assets such as tables.",
    )
    content_type: str | None = Field(default=None)
    filename: str | None = Field(default=None)
    source_relationship_id: str | None = Field(default=None)


class AssetStore:

    def __init__(self) -> None:
        self._assets: dict[str, AssetBlob] = {}

    def add(self, asset: AssetBlob) -> AssetBlob:
        self._assets[asset.id] = asset
        return asset

    def get(self, asset_id: str) -> AssetBlob | None:
        return self._assets.get(asset_id)

    def require(self, asset_id: str) -> AssetBlob:
        asset = self.get(asset_id)
        if asset is None:
            raise KeyError(f"缺少保真资源: {asset_id}")
        return asset

    def has(self, asset_id: str) -> bool:
        return asset_id in self._assets

    def __iter__(self) -> Iterator[AssetBlob]:
        return iter(self._assets.values())

    def __len__(self) -> int:
        return len(self._assets)


class PreservationTarget(StrictASTModel):

    node_id: NodeID
    asset_id: NodeID
    opaque_type: OpaqueType


class PreservationPlan(StrictASTModel):

    targets: dict[NodeID, PreservationTarget] = Field(default_factory=dict)

    @classmethod
    def from_ast_and_assets(cls, ast: object, asset_store: AssetStore) -> "PreservationPlan":
        targets: dict[str, PreservationTarget] = {}
        for node in getattr(ast, "blocks", []):
            if not isinstance(node, OpaqueNode):
                continue
            if node.suppress_render:
                continue
            if node.opaque_type not in (
                OpaqueType.IMAGE,
                OpaqueType.TABLE,
                OpaqueType.EQUATION,
                OpaqueType.TEXTBOX,
                OpaqueType.SDT,
                OpaqueType.FIELD,
                OpaqueType.UNKNOWN,
                OpaqueType.GENERIC,
            ):
                continue
            if not node.raw_ooxml_ref:
                continue
            if not asset_store.has(node.raw_ooxml_ref):
                continue
            targets[node.id] = PreservationTarget(
                node_id=node.id,
                asset_id=node.raw_ooxml_ref,
                opaque_type=node.opaque_type,
            )
        return cls(targets=targets)

    def target_for(self, node_id: str) -> PreservationTarget | None:
        return self.targets.get(node_id)
