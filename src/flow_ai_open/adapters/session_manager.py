from __future__ import annotations

from uuid import uuid4

from flow_ai.contracts.classification_contracts import ClassificationDecision
from flow_ai.contracts.draft_decisions_v3 import DraftDecisionSidecar
from flow_ai.core.ast_models import DocumentAST
from flow_ai.core.style_models import RenderPlan


class SessionState:

    def __init__(self) -> None:
        self.ast: DocumentAST | None = None
        self.decisions: list[ClassificationDecision] = []
        self.draft_sidecar: DraftDecisionSidecar | None = None
        self.render_plan: RenderPlan | None = None


class SessionManager:

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create_session(self) -> str:
        session_id = str(uuid4())
        self._sessions[session_id] = SessionState()
        return session_id

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def update_ast(self, session_id: str, ast: DocumentAST) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.ast = ast

    def update_decisions(
        self, session_id: str, decisions: list[ClassificationDecision]
    ) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.decisions = decisions

    def update_draft_sidecar(
        self, session_id: str, sidecar: DraftDecisionSidecar
    ) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.draft_sidecar = sidecar

    def update_render_plan(self, session_id: str, plan: RenderPlan) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.render_plan = plan

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
