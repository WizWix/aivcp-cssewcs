"""프로젝트 루트 진입점 — `py run.py`로 서버를 시작한다."""

import asyncio

import colorama
import uvicorn

from backend.config import settings


class _Server(uvicorn.Server):
    """종료 신호 수신 시 스트리밍 연결을 먼저 닫기 위해 shutdown을 오버라이드한다.

    uvicorn의 기본 shutdown 순서:
        1. "Waiting for connections to close" 출력
        2. 연결이 빌 때까지 대기
        3. lifespan cleanup (yield 이후) 실행

    문제: shutdown_event.set()이 lifespan cleanup에 있으면 연결이 닫혀야 실행되고,
         연결은 shutdown_event가 설정돼야 닫히는 교착 상태가 발생한다.

    해결: super().shutdown() 호출 전에 shutdown_event를 먼저 설정하여
         MJPEG/SSE generator가 즉시 루프를 탈출하도록 한다.
    """

    async def shutdown(self, sockets=None) -> None:
        # 지연 임포트: 순환 참조 방지
        from backend.main import app  # noqa: PLC0415

        # shutdown_event 설정 → generator가 while 루프를 탈출 → 연결 자동 종료
        if hasattr(app, "state") and hasattr(app.state, "shutdown_event"):
            app.state.shutdown_event.set()

        # 이후 super()가 연결이 닫힐 때까지 대기 (이제 빠르게 완료됨)
        await super().shutdown(sockets)


if __name__ == "__main__":
    colorama.init()

    config = uvicorn.Config(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    server = _Server(config)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
