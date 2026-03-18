"""
Server-Sent Events (SSE) router for real-time violation notifications.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# SSE keepalive 간격 (초): 브라우저가 연결 유지 중임을 서버가 확인
_KEEPALIVE_INTERVAL_SEC = 15.0


@router.get("/events")
async def sse_events(request: Request):
    """SSE 실시간 이벤트 스트림 엔드포인트.

    브라우저의 EventSource("/api/events")가 이 엔드포인트에 연결한다.
    위반 발생 시 JSON 형식의 이벤트를 즉시 전송한다.
    클라이언트 연결 종료 시 자동으로 구독이 해제된다.
    """
    event_bus = request.app.state.event_bus
    q = event_bus.subscribe()

    shutdown_event: asyncio.Event = request.app.state.shutdown_event

    async def generator():
        """연결이 유지되는 동안 이벤트를 생성하는 비동기 제너레이터."""
        # keepalive 핑 경과 시간 추적 (1초 단위 폴링으로 shutdown 빠르게 감지)
        keepalive_elapsed = 0.0
        try:
            while not shutdown_event.is_set():
                # 클라이언트 연결 종료 확인
                if await request.is_disconnected():
                    logger.debug("SSE 클라이언트 연결 종료")
                    break

                try:
                    # 1초 단위로 폴링 → shutdown_event를 최대 1초 내에 감지
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    keepalive_elapsed = 0.0
                    # 이벤트 타입을 페이로드에서 추출하여 SSE event 필드로 사용
                    event_type = event.pop("event_type", "violation")
                    yield {
                        "event": event_type,
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    keepalive_elapsed += 1.0
                    # keepalive 핑: 15초마다 전송하여 브라우저 연결 유지
                    if keepalive_elapsed >= _KEEPALIVE_INTERVAL_SEC:
                        keepalive_elapsed = 0.0
                        yield {"event": "ping", "data": ""}

        finally:
            event_bus.unsubscribe(q)

    return EventSourceResponse(generator())
