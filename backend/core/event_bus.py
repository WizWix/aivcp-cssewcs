"""
SSE event bus for broadcasting violation events to all connected browser clients.
"""

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# SSE 클라이언트 큐의 최대 크기 (느린 클라이언트가 메모리를 과점하지 않도록 제한)
_MAX_QUEUE_SIZE = 20


class EventBus:
    """위반 이벤트를 모든 SSE 구독자에게 팬아웃하는 브로드캐스터.

    감지 스레드(백그라운드)에서 publish()를 호출하면,
    asyncio 이벤트 루프 스레드에서 실행 중인 각 SSE 클라이언트 큐에
    스레드 안전하게 이벤트를 전달한다.

    SRP: 이 클래스는 오직 이벤트 브로드캐스트 책임만 담당한다.
    OCP: 새 이벤트 타입 추가 시 이 클래스를 수정하지 않아도 된다.
    """

    def __init__(self) -> None:
        # 구독자 목록 (각 SSE 연결마다 개인 큐를 보유)
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()  # 구독자 목록 뮤텍스
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """FastAPI lifespan에서 asyncio 이벤트 루프 참조를 주입한다.

        반드시 lifespan 시작 시 1회 호출해야 한다.
        """
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """새 SSE 연결을 위한 전용 큐를 생성하고 구독자 목록에 등록한다.

        Returns:
            이 연결 전용 asyncio.Queue (이벤트 수신용)
        """
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(q)
        logger.debug(f"SSE 구독자 추가 | 현재 구독자 수: {len(self._subscribers)}")
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """클라이언트 연결 종료 시 구독자 목록에서 제거한다."""
        with self._lock:
            try:
                self._subscribers.remove(q)
                logger.debug(f"SSE 구독자 제거 | 현재 구독자 수: {len(self._subscribers)}")
            except ValueError:
                pass  # 이미 제거된 경우 무시

    def publish(self, event: dict[str, Any]) -> None:
        """위반 이벤트를 모든 구독자에게 전파한다.

        백그라운드 감지 스레드에서 호출되므로,
        loop.call_soon_threadsafe를 사용하여 asyncio 큐에 안전하게 삽입한다.

        Args:
            event: SSE로 전송할 이벤트 딕셔너리
        """
        if self._loop is None:
            logger.warning("EventBus: 이벤트 루프가 설정되지 않았습니다.")
            return

        with self._lock:
            snapshot = list(self._subscribers)

        for q in snapshot:
            # 큐가 꽉 찬 경우(느린 클라이언트) 이벤트를 드랍하여 백프레셔 방지
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except asyncio.QueueFull:
                logger.debug("SSE 큐 초과, 이벤트 드랍 (느린 클라이언트)")
            except Exception as e:
                logger.warning(f"SSE 이벤트 전파 실패: {e}")

    @property
    def subscriber_count(self) -> int:
        """현재 활성 SSE 구독자 수"""
        with self._lock:
            return len(self._subscribers)
