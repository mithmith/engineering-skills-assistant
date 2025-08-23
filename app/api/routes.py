from app.config import logger

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas import ChatRequest, ChatResponse, HealthResponse, OptionsIn, RouteRequest, RouteResponse
from app.integration.openrouteservice import ors_route
from app.services.chat import ChatService
from app.services.route_processing import (
    annotate_intermediate_localities,
    enrich_localities_with_yandex,
    ensure_coords,
    ors_extract_steps,
)
from app.services.route_text import build_markdown

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
    logger.info("/chat called: conversation_id=%s", req.conversation_id)
    conv_id = str(req.conversation_id) if req.conversation_id else None
    result = svc.chat(user_text=req.user_text, conversation_id=conv_id)
    logger.debug("/chat result: conversation_id=%s response_id=%s", result.conversation_id, result.response_id)
    return ChatResponse(
        conversation_id=result.conversation_id,
        assistant_text=result.assistant_text,
        response_id=result.response_id,
    )


@router.post("/route", response_model=RouteResponse)
async def route(req: RouteRequest) -> RouteResponse:
    try:
        logger.info("/route called: a=%s b=%s options=%s", req.a, req.b, req.options)
        a_lat, a_lon, a_label = await ensure_coords(req.a)
        b_lat, b_lon, b_label = await ensure_coords(req.b)
        logger.debug("Resolved coords: A=(%s,%s) B=(%s,%s)", a_lat, a_lon, b_lat, b_lon)

        opts = req.options or OptionsIn(language="ru", avoid_tolls=False)
        data = await ors_route(a_lat, a_lon, b_lat, b_lon, opts)
        steps, total_m, total_s, coords, step_bounds = ors_extract_steps(data)
        logger.debug("ORS returned: steps=%d total_m=%s total_s=%s", len(steps), total_m, total_s)

        if not steps:
            logger.info("/route: empty steps")
            return RouteResponse(ok=False, type="error", message="Маршрут пуст (нет шагов)")

        # Обогащаем locality и добавляем промежуточные населённые пункты на длинных шагах
        await enrich_localities_with_yandex(steps)
        await annotate_intermediate_localities(steps, step_bounds, coords, min_step_m=5000, sample_interval_m=5000)

        md = build_markdown(a_label, a_lat, a_lon, b_label, b_lat, b_lon, steps, total_m, total_s)
        logger.info("/route success: steps=%d", len(steps))
        return RouteResponse(ok=True, markdown=md, steps=steps)

    except HTTPException as he:
        logger.info("/route HTTPException: %s", he.detail)
        return RouteResponse(ok=False, type="error", message=str(he.detail))
    except Exception as e:
        logger.exception("unexpected error")
        return RouteResponse(ok=False, type="error", message=f"Неожиданная ошибка: {e}")
