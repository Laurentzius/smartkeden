import json
import logging
from typing import List, Optional, Any

from fastapi import APIRouter, HTTPException, Form, File, UploadFile
from langfuse import observe, propagate_attributes
from app.core.config import settings

from app.core.orchestrator.models import (
    IntentType,
    ChatMessage,
    OrchestrateResponse,
)
from app.core.orchestrator.workflow_graph import (
    _runner,
    _APP_NAME,
    _USER_ID,
    _session_service,
)
from google.genai import types as genai_types


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orchestrate", tags=["Orchestrator"])


@router.post("", response_model=OrchestrateResponse)
@observe(name="orchestrate")
async def orchestrate(
    text: str = Form(...),
    session_id: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Main orchestrator endpoint. Accepts a user message, runs it through
    the ADK 2.0 ``KedenCustomsWorkflow`` graph, and returns the
    ``OrchestrateResponse`` from the terminating workflow node.
    """
    if not text or not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Пожалуйста, напишите ваш вопрос или загрузите файл.",
        )

    clean_text = text.strip()
    sess_id = session_id or "default"

    # Parse history
    parsed_history: List[ChatMessage] = []
    if history:
        try:
            data_list = json.loads(history)
            if isinstance(data_list, list):
                parsed_history = [ChatMessage(**m) for m in data_list]
        except Exception as e:
            logger.error(f"Failed to parse history: {e}")

    # Read uploaded file
    file_bytes: Optional[bytes] = None
    file_mime: Optional[str] = None
    file_name: Optional[str] = None
    if file is not None:
        file_bytes = await file.read()
        file_mime = file.content_type
        file_name = file.filename

    async def _run_workflow() -> Optional[dict[str, Any]]:
        """Create an ADK session seeded with request state, run the workflow,
        and return the terminal node's output."""
        # Wipe any prior session for this session_id so we start fresh
        try:
            await _session_service.delete_session(
                app_name=_APP_NAME,
                user_id=_USER_ID,
                session_id=sess_id,
            )
        except Exception:
            pass

        # Create a session whose initial state is picked up as ctx.state
        # by the workflow nodes (user_text + history).
        state_dict = {
            "user_text": clean_text,
            "history": [m.model_dump() for m in parsed_history]
            if parsed_history
            else [],
        }
        if file_bytes is not None:
            state_dict["uploaded_file_bytes"] = file_bytes
            state_dict["uploaded_file_mime"] = file_mime
            state_dict["uploaded_file_name"] = file_name

        await _session_service.create_session(
            app_name=_APP_NAME,
            user_id=_USER_ID,
            session_id=sess_id,
            state=state_dict,
        )
        final_output: Optional[dict[str, Any]] = None
        try:
            async for event in _runner.run_async(
                user_id=_USER_ID,
                session_id=sess_id,
                new_message=genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=clean_text)],
                ),
            ):
                if event.output is not None:
                    final_output = event.output
        except Exception as exc:
            logger.error(f"Workflow execution failed: {exc}", exc_info=True)
            final_output = None
        return final_output

    if settings.LANGFUSE_ENABLED and sess_id:
        with propagate_attributes(session_id=sess_id, tags=[settings.GEMINI_MODEL_ID]):
            return _workflow_output_to_response(await _run_workflow())
    return _workflow_output_to_response(await _run_workflow())


def _workflow_output_to_response(
    final_output: Optional[dict[str, Any]],
) -> OrchestrateResponse:
    """Map the terminal workflow node's return value to an OrchestrateResponse."""
    if final_output and isinstance(final_output, dict):
        intent_str = final_output.get("intent", "unclear")
        try:
            intent = IntentType(intent_str)
        except ValueError:
            intent = IntentType.unclear

        message = final_output.get("message") or ""
        pipeline_results = final_output.get("pipeline_results")
        chain_warning = final_output.get("chain_warning")

        return OrchestrateResponse(
            intent=intent,
            message=message,
            pipeline_results=pipeline_results,
            chain_warning=chain_warning,
        )

    # Fallback: no output from workflow
    return OrchestrateResponse(
        intent=IntentType.unclear,
        message="Извините, при обработке вашего запроса произошла техническая ошибка. Попробуйте ещё раз.",
    )
