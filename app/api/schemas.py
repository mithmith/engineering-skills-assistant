from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    user_text: str = Field(..., description="Свежий ввод пользователя")
    conversation_id: Optional[str] = Field(None, description="UUID/идентификатор диалога")


class ChatResponse(BaseModel):
    conversation_id: str
    assistant_text: str
    response_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"


class PointIn(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    @model_validator(mode="after")
    def either_address_or_coords(self):
        has_addr = bool(self.address)
        has_coords = (self.lat is not None) and (self.lon is not None)
        if not (has_addr or has_coords):
            raise ValueError("Provide either 'address' or both 'lat' and 'lon'")
        return self


class OptionsIn(BaseModel):
    # В ORS нет трафика, но оставим поле для совместимости интерфейса
    avoid_tolls: bool = False
    language: str = Field("ru", description="Язык инструкций ORS (e.g. 'ru')")


class ViaLocality(BaseModel):
    name: str
    lat: float
    lon: float


class RouteRequest(BaseModel):
    a: PointIn
    b: PointIn
    options: Optional[OptionsIn] = None


class StepOut(BaseModel):
    idx: int
    start_lat: float
    start_lon: float
    distance_m: int
    duration_s: int
    instruction: Optional[str] = None
    street: Optional[str] = None
    locality: Optional[str] = None
    via_localities: Optional[List[ViaLocality]] = None


class RouteResponse(BaseModel):
    ok: bool
    markdown: Optional[str] = None
    steps: Optional[List[StepOut]] = None
    type: Optional[str] = "result"
    message: Optional[str] = None
