"""
Thread-safe ring buffer for storing recent frames before a violation is detected.
"""

import threading
from collections import deque

import numpy as np


class FrameBuffer:
    """스레드 안전 링 버퍼.

    감지 스레드가 프레임을 지속적으로 append하고,
    위반 발생 시 snapshot()으로 최근 N프레임을 안전하게 가져간다.

    SRP: 이 클래스는 오직 프레임 버퍼링 책임만 담당한다.
    """

    def __init__(self, maxlen: int) -> None:
        """
        Args:
            maxlen: 보관할 최대 프레임 수 (오래된 프레임은 자동으로 제거됨)
        """
        # deque는 maxlen 초과 시 가장 오래된 항목을 자동 제거
        self._buffer: deque[np.ndarray] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, frame: np.ndarray) -> None:
        """프레임을 버퍼에 추가한다. (감지 스레드에서 호출)"""
        with self._lock:
            # 스냅샷 비용을 줄이기 위해 참조만 저장 (복사 X)
            # 호출자가 프레임을 수정하지 않는다고 가정
            self._buffer.append(frame)

    def snapshot(self) -> list[np.ndarray]:
        """현재 버퍼의 모든 프레임을 리스트로 복사하여 반환한다.

        반환값은 버퍼와 독립적인 새 리스트이므로
        이후의 append가 결과에 영향을 주지 않는다.
        """
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """버퍼를 비운다."""
        with self._lock:
            self._buffer.clear()

    @property
    def size(self) -> int:
        """현재 버퍼에 저장된 프레임 수"""
        with self._lock:
            return len(self._buffer)
