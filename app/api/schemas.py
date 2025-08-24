from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_text: str = Field(..., description="Свежий ввод пользователя")
    conversation_id: Optional[str] = Field(None, description="UUID/идентификатор диалога")


class ChatResponse(BaseModel):
    conversation_id: str
    assistant_text: str
    response_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
