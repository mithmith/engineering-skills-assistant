from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.config import logger
from app.services.chat import ChatService

router = APIRouter()


def get_chat_service(request: Request) -> ChatService:
    svc = getattr(request.app.state, "chat_service", None)
    if svc is None:
        raise HTTPException(status_code=500, detail="ChatService is not initialized")
    return svc


@router.get("/health", response_model=HealthResponse)
def healthcheck():
    logger.debug("Healthcheck called")
    return HealthResponse()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, svc: ChatService = Depends(get_chat_service)):
    logger.info(f"/chat called: conversation_id={req.conversation_id}")
    conv_id = str(req.conversation_id) if req.conversation_id else None
    try:
        result = svc.chat(user_text=req.user_text, conversation_id=conv_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("/chat unexpected error")
        raise HTTPException(status_code=500, detail=f"Chat error: {e}")
    logger.debug("/chat result: conversation_id=%s response_id=%s", result.conversation_id, result.response_id)
    return ChatResponse(
        conversation_id=result.conversation_id,
        assistant_text=result.assistant_text,
        response_id=result.response_id,
    )


# /route endpoint removed: routing integrations were dropped from the project
