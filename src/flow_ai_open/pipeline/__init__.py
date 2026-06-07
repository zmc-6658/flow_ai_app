from __future__ import annotations

from pathlib import Path

from flow_ai.contracts.classification_contracts import ClassificationDecision, ResolverResult
from flow_ai.contracts.error_codes import ErrorCode
from flow_ai.contracts.status_shell import StatusShell
from flow_ai.core.ast_models import DocumentAST
from flow_ai.core.preservation_models import AssetStore, PreservationPlan
from flow_ai.core.style_models import RenderPlan
from flow_ai_open.adapters.core_adapter import CoreAdapter
from flow_ai_open.adapters.patch_merger import DecisionPatch, PatchMerger
from flow_ai_open.engine.rule_engine import RuleEngine
from flow_ai_open.engine.yaml_loader import load_profiles_from_yaml, load_rules_from_yaml
from flow_ai_open.ingestion.docx_parser import DocxParser
from flow_ai_open.renderer.docx_renderer import DocxRenderer


class PipelineContext:

    def __init__(self) -> None:
        self.ast: DocumentAST | None = None
        self.asset_store: AssetStore = AssetStore()
        self.classified_ast: DocumentAST | None = None
        self.resolver_result: ResolverResult | None = None
        self.decisions: list[ClassificationDecision] = []
        self.render_plan: RenderPlan | None = None
        self.style_assignments: dict[str, str | None] = {}


class FlowPipeline:

    def __init__(self) -> None:
        self._ctx = PipelineContext()
        self._adapter = CoreAdapter()
        self._merger = PatchMerger()

    @property
    def context(self) -> PipelineContext:
        return self._ctx

    def parse(self, docx_path: str | Path) -> StatusShell[DocumentAST]:
        source_path = Path(docx_path)
        if not source_path.exists():
            return StatusShell(
                data=None,
                error_code=ErrorCode.FILE_NOT_FOUND,
                message=f"文件不存在: {source_path}",
            )
        try:
            parser = DocxParser()
            ast, asset_store = parser.parse_with_assets(source_path)
            self._ctx.ast = ast
            self._ctx.asset_store = asset_store
            return StatusShell(data=ast)
        except Exception as exc:
            return StatusShell(
                data=None,
                error_code=ErrorCode.PARSE_FAILED,
                message=str(exc),
            )

    def classify(self) -> StatusShell[ResolverResult]:
        if self._ctx.ast is None:
            return StatusShell(
                data=None,
                error_code=ErrorCode.E_INVALID_AST,
                message="请先执行 parse() 解析文档",
            )
        try:
            classified_ast, shell = self._adapter.classify_ast(self._ctx.ast)
            if shell.data is not None:
                self._ctx.classified_ast = classified_ast
                self._ctx.resolver_result = shell.data
                self._ctx.decisions = shell.data.decisions
            return shell
        except Exception as exc:
            return StatusShell(
                data=None,
                error_code=ErrorCode.CLASSIFY_FAILED,
                message=str(exc),
            )

    def patch_decisions(
        self, patches: list[DecisionPatch]
    ) -> StatusShell[list[ClassificationDecision]]:
        if not self._ctx.decisions:
            return StatusShell(
                data=None,
                error_code=ErrorCode.PATCH_CONFLICT,
                message="当前无决策可修改，请先执行 classify()",
            )
        result = self._merger.merge(self._ctx.decisions, patches)
        if result.error_code is not None:
            return result

        self._ctx.decisions = result.data
        for patch in patches:
            if "assigned_style_id" in patch.model_fields_set:
                self._ctx.style_assignments[patch.node_id] = patch.assigned_style_id
        return StatusShell(data=self._ctx.decisions)

    def compile_plan(
        self, rules_path: str | Path | None = None
    ) -> StatusShell[RenderPlan]:
        ast = self._ctx.classified_ast or self._ctx.ast
        if ast is None:
            return StatusShell(
                data=None,
                error_code=ErrorCode.E_INVALID_AST,
                message="请先执行 parse() 解析文档",
            )
        try:
            rules = load_rules_from_yaml(str(rules_path)) if rules_path else []
            profiles = load_profiles_from_yaml(str(rules_path)) if rules_path else None
            plan = RuleEngine(rules).compile_plan(ast, self._ctx.decisions)
            self._ctx.render_plan = plan
            self._ctx._profiles = profiles
            return StatusShell(data=plan)
        except Exception as exc:
            return StatusShell(
                data=None,
                error_code=ErrorCode.E_RENDER_FAILURE,
                message=str(exc),
            )

    def render(self, output_path: str | Path) -> StatusShell[Path]:
        ast = self._ctx.classified_ast or self._ctx.ast
        if ast is None:
            return StatusShell(
                data=None,
                error_code=ErrorCode.E_INVALID_AST,
                message="请先执行 parse() 解析文档",
            )
        if self._ctx.render_plan is None:
            return StatusShell(
                data=None,
                error_code=ErrorCode.E_RENDER_FAILURE,
                message="请先执行 compile_plan() 编译规则",
            )
        try:
            preservation_plan = PreservationPlan.from_ast_and_assets(
                ast, self._ctx.asset_store
            )
            profiles = getattr(self._ctx, "_profiles", None)
            renderer = DocxRenderer(
                preservation_plan=preservation_plan,
                asset_store=self._ctx.asset_store,
                profiles=profiles,
            )
            renderer.render(ast, self._ctx.render_plan, str(output_path))
            return StatusShell(data=Path(output_path))
        except Exception as exc:
            return StatusShell(
                data=None,
                error_code=ErrorCode.RENDER_FAILED,
                message=str(exc),
            )

    def reset(self) -> None:
        self._ctx = PipelineContext()
