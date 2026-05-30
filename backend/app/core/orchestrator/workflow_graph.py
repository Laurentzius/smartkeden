import logging

from app.core.orchestrator.workflow_nodes import (
    coordinator_node,
    greeting_node,
    document_upload_node,
    unclear_node,
    legal_rag_node,
    hs_classifier_node,
    calculator_node,
    conditional_route_node,
    interception_response_node,
    faq_response_node,
)
from google.adk.workflow import Workflow, Edge, START
from google.adk.sessions import InMemorySessionService
from google.adk import Runner


logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
#  Workflow Graph  (Section 4 of google_adk_orchestration_flow.md)
# ════════════════════════════════════════════════════════════════════════
#
#  State machine:
#    START -> coordinator_node
#    coordinator_node -(route: intent)-> specialist_node
#    specialist_node -> END (automatic)
#    hs_classifier_node -> conditional_route_node
#    conditional_route_node -(chain_to_calc)-> calculator_node
# ════════════════════════════════════════════════════════════════════════

_KEDEN_WORKFLOW_EDGES: list[Edge] = [
    # Entry
    Edge(from_node=START, to_node=coordinator_node),
    # Conditional intent-based routing from coordinator
    Edge(from_node=coordinator_node, to_node=greeting_node, route="greeting"),
    Edge(
        from_node=coordinator_node,
        to_node=document_upload_node,
        route="document_upload",
    ),
    Edge(from_node=coordinator_node, to_node=unclear_node, route="unclear"),
    Edge(
        from_node=coordinator_node,
        to_node=hs_classifier_node,
        route="product_description",
    ),
    Edge(
        from_node=coordinator_node, to_node=legal_rag_node, route="question_about_law"
    ),
    Edge(
        from_node=coordinator_node, to_node=calculator_node, route="calculation_request"
    ),
    # Smart interception routes
    Edge(
        from_node=coordinator_node,
        to_node=interception_response_node,
        route="interception_response",
    ),
    # FAQ fastpath route
    Edge(from_node=coordinator_node, to_node=faq_response_node, route="faq_response"),
    # HS -> Conditional -> Calculator chain
    Edge(from_node=hs_classifier_node, to_node=conditional_route_node),
    Edge(
        from_node=conditional_route_node, to_node=calculator_node, route="chain_to_calc"
    ),
]

KedenCustomsWorkflow: Workflow = Workflow(
    name="KedenCustomsWorkflow",
    edges=_KEDEN_WORKFLOW_EDGES,
    rerun_on_resume=True,
)

# Stateless in-memory session service -- each request manages its own
# session lifecycle to carry request-scoped state into ctx.state.
_APP_NAME = "keden_customs"
_USER_ID = "default_user"
_session_service: InMemorySessionService = InMemorySessionService()

_runner: Runner = Runner(
    node=KedenCustomsWorkflow,
    session_service=_session_service,
    app_name=_APP_NAME,
    auto_create_session=False,
)
