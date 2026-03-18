"""
MJPEG video stream router.
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

# 프레임 대기 타임아웃 (초): 서버 종료 신호를 이 간격마다 확인한다
_FRAME_WAIT_TIMEOUT_SEC = 0.5


@router.get("/stream")
async def mjpeg_stream(request: Request, bbox: bool = False):
    """MJPEG 멀티파트 스트림 엔드포인트.

    bbox=false: 원본 영상 스트림
    bbox=true:  바운딩박스 오버레이 영상 스트림

    브라우저에서 <img src="/api/stream?bbox=false"> 형태로 사용한다.
    """
    stream_manager = request.app.state.stream_manager
    shutdown_event: asyncio.Event = request.app.state.shutdown_event

    # bbox 옵션에 따라 구독할 큐 선택
    if bbox:
        q = stream_manager.subscribe_annotated()
    else:
        q = stream_manager.subscribe_raw()

    async def generate():
        """클라이언트가 연결되어 있는 동안 JPEG 프레임을 전송한다."""
        try:
            while not shutdown_event.is_set():
                # 클라이언트 연결 종료 감지
                if await request.is_disconnected():
                    break

                # 프레임 대기: 타임아웃으로 주기적으로 종료 여부를 확인
                try:
                    jpeg_bytes = await asyncio.wait_for(q.get(), timeout=_FRAME_WAIT_TIMEOUT_SEC)
                except asyncio.TimeoutError:
                    continue

                if not jpeg_bytes:
                    continue

                # MJPEG 멀티파트 형식으로 전송
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n")
        finally:
            # 연결 종료 시 구독 해제
            stream_manager.unsubscribe(q, annotated=bbox)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
