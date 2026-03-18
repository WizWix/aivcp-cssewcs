"""
MJPEG stream manager that distributes encoded frames to per-client asyncio queues.
"""

import asyncio
import logging
import threading

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 클라이언트별 큐 최대 크기
# 2로 제한하여 느린 클라이언트가 감지 스레드를 블로킹하지 않도록 함
_QUEUE_MAXSIZE = 2

# JPEG 압축 품질 (0-100): 75는 화질/대역폭 균형점
_JPEG_QUALITY = 75


class StreamManager:
    """MJPEG 스트림을 클라이언트별로 분배하는 관리자.

    감지 스레드가 push()를 호출하면, 등록된 모든 클라이언트 큐에
    JPEG 인코딩된 프레임을 비차단 방식으로 전달한다.

    SRP: 이 클래스는 오직 MJPEG 프레임 분배 책임만 담당한다.
    """

    def __init__(self) -> None:
        # raw 프레임 구독자 (bbox=false인 클라이언트)
        self._raw_subs: set[asyncio.Queue[bytes]] = set()
        # annotated 프레임 구독자 (bbox=true인 클라이언트)
        self._annotated_subs: set[asyncio.Queue[bytes]] = set()
        self._lock = threading.Lock()

    def subscribe_raw(self) -> asyncio.Queue[bytes]:
        """원본 프레임 스트림을 위한 전용 큐를 생성하고 등록한다."""
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._raw_subs.add(q)
        logger.debug(f"Raw 스트림 구독자 추가 | 수: {len(self._raw_subs)}")
        return q

    def subscribe_annotated(self) -> asyncio.Queue[bytes]:
        """바운딩박스 오버레이 스트림을 위한 전용 큐를 생성하고 등록한다."""
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._annotated_subs.add(q)
        logger.debug(f"Annotated 스트림 구독자 추가 | 수: {len(self._annotated_subs)}")
        return q

    def unsubscribe(self, q: asyncio.Queue[bytes], annotated: bool) -> None:
        """클라이언트 연결 종료 시 구독자 목록에서 제거한다."""
        with self._lock:
            target = self._annotated_subs if annotated else self._raw_subs
            target.discard(q)

    def push(
        self,
        raw_frame: np.ndarray,
        annotated_frame: np.ndarray,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """프레임을 JPEG으로 인코딩하여 각 구독자 큐에 전달한다.

        백그라운드 감지 스레드에서 호출된다.
        loop.call_soon_threadsafe로 asyncio 큐에 안전하게 삽입한다.

        Args:
            raw_frame: 원본 BGR 프레임
            annotated_frame: 바운딩박스가 그려진 BGR 프레임
            loop: FastAPI 이벤트 루프 참조
        """
        with self._lock:
            has_raw = bool(self._raw_subs)
            has_annotated = bool(self._annotated_subs)
            raw_snapshot = set(self._raw_subs)
            annotated_snapshot = set(self._annotated_subs)

        # 구독자가 없으면 JPEG 인코딩 자체를 생략하여 CPU 절약
        raw_jpeg: bytes | None = None
        annotated_jpeg: bytes | None = None

        if has_raw:
            raw_jpeg = self._encode_jpeg(raw_frame)
        if has_annotated:
            annotated_jpeg = self._encode_jpeg(annotated_frame)

        # raw 구독자에게 전달
        if raw_jpeg is not None:
            self._distribute(raw_jpeg, raw_snapshot, loop)

        # annotated 구독자에게 전달
        if annotated_jpeg is not None:
            self._distribute(annotated_jpeg, annotated_snapshot, loop)

    @staticmethod
    def _encode_jpeg(frame: np.ndarray) -> bytes:
        """프레임을 JPEG 바이트로 인코딩한다."""
        params = [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
        success, buffer = cv2.imencode(".jpg", frame, params)
        if not success:
            return b""
        return buffer.tobytes()

    @staticmethod
    def _distribute(
        jpeg_bytes: bytes,
        subscribers: set[asyncio.Queue[bytes]],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """JPEG 바이트를 구독자 집합의 모든 큐에 비차단으로 전달한다."""
        for q in subscribers:
            # 큐가 꽉 찬 경우 오래된 프레임 드랍 (느린 클라이언트 백프레셔 방지)
            try:
                loop.call_soon_threadsafe(q.put_nowait, jpeg_bytes)
            except asyncio.QueueFull:
                pass
            except Exception as e:
                logger.debug(f"프레임 전달 실패: {e}")

    @property
    def client_count(self) -> int:
        """현재 연결된 MJPEG 클라이언트 총 수"""
        with self._lock:
            return len(self._raw_subs) + len(self._annotated_subs)
