"""
Gate control service with abstract interface and simulator implementation.
"""

import logging
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class GateController(ABC):
    """게이트 제어 추상 인터페이스.

    OCP/LSP: 시리얼 또는 GPIO 기반 구현체를 이 인터페이스로 교체 가능하다.
    ISP: 게이트 제어에 필요한 최소한의 메서드만 정의한다.
    """

    @abstractmethod
    def lock(self, duration_sec: int = 5) -> None:
        """게이트를 잠근다.

        Args:
            duration_sec: 잠금 지속 시간(초). 이후 자동으로 해제된다.
        """

    @abstractmethod
    def unlock(self) -> None:
        """게이트 잠금을 즉시 해제한다."""

    @abstractmethod
    def is_locked(self) -> bool:
        """현재 게이트 잠금 여부를 반환한다."""


class SimulatedGateController(GateController):
    """개발/시뮬레이션용 게이트 컨트롤러.

    실제 하드웨어 없이 잠금 상태를 메모리로 관리하고 로그를 출력한다.
    threading.Timer를 사용하여 자동 해제를 구현한다.
    """

    def __init__(self) -> None:
        self._locked: bool = False
        self._unlock_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def lock(self, duration_sec: int = 5) -> None:
        """게이트를 잠그고 duration_sec 후 자동 해제한다."""
        with self._lock:
            # 이미 잠겨 있으면 기존 타이머 취소 후 재설정
            if self._unlock_timer is not None:
                self._unlock_timer.cancel()

            self._locked = True
            logger.info(f"[게이트] 잠금 (자동 해제: {duration_sec}초 후)")

            # 비차단 자동 해제 타이머
            self._unlock_timer = threading.Timer(duration_sec, self._auto_unlock)
            self._unlock_timer.daemon = True
            self._unlock_timer.start()

    def unlock(self) -> None:
        """게이트 잠금을 즉시 해제한다."""
        with self._lock:
            if self._unlock_timer is not None:
                self._unlock_timer.cancel()
                self._unlock_timer = None
            self._locked = False
            logger.info("[게이트] 잠금 해제")

    def is_locked(self) -> bool:
        """현재 잠금 상태를 반환한다."""
        with self._lock:
            return self._locked

    def _auto_unlock(self) -> None:
        """타이머 콜백: 자동 잠금 해제"""
        with self._lock:
            self._locked = False
            self._unlock_timer = None
            logger.info("[게이트] 자동 잠금 해제")


class SerialGateController(GateController):
    """시리얼 포트(RS-232/RS-485) 기반 실제 게이트 컨트롤러.

    실제 하드웨어 연결 시 이 클래스를 사용한다.
    main.py의 gate_type 설정에 따라 SimulatedGateController와 교체된다.
    """

    # 시리얼 프로토콜 커맨드 (실제 게이트 장비 매뉴얼에 맞게 수정 필요)
    _CMD_LOCK = b"\xff\x01\x01\xff"
    _CMD_UNLOCK = b"\xff\x01\x00\xff"

    def __init__(self, port: str, baudrate: int = 9600) -> None:
        try:
            import serial

            self._serial = serial.Serial(port, baudrate, timeout=1)
            logger.info(f"시리얼 게이트 포트 열기 성공: {port}")
        except ImportError:
            raise RuntimeError("pyserial이 설치되지 않았습니다: pip install pyserial")
        except Exception as e:
            raise RuntimeError(f"시리얼 포트 열기 실패 ({port}): {e}")

        self._locked = False
        self._unlock_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def lock(self, duration_sec: int = 5) -> None:
        with self._lock:
            if self._unlock_timer is not None:
                self._unlock_timer.cancel()

            self._serial.write(self._CMD_LOCK)
            self._locked = True
            logger.info(f"[시리얼 게이트] 잠금 커맨드 전송 ({duration_sec}초)")

            self._unlock_timer = threading.Timer(duration_sec, self._auto_unlock)
            self._unlock_timer.daemon = True
            self._unlock_timer.start()

    def unlock(self) -> None:
        with self._lock:
            if self._unlock_timer is not None:
                self._unlock_timer.cancel()
                self._unlock_timer = None
            self._serial.write(self._CMD_UNLOCK)
            self._locked = False
            logger.info("[시리얼 게이트] 잠금 해제 커맨드 전송")

    def is_locked(self) -> bool:
        with self._lock:
            return self._locked

    def _auto_unlock(self) -> None:
        with self._lock:
            self._serial.write(self._CMD_UNLOCK)
            self._locked = False
            self._unlock_timer = None
            logger.info("[시리얼 게이트] 자동 잠금 해제")


def create_gate_controller(gate_type: str, **kwargs) -> GateController:
    """gate_type 설정에 따라 적절한 GateController 인스턴스를 생성한다.

    DIP: 호출자가 구체 구현체에 직접 의존하지 않아도 된다.
    """
    if gate_type == "serial":
        port = kwargs.get("port", "COM3")
        baudrate = kwargs.get("baudrate", 9600)
        return SerialGateController(port, baudrate)
    # 기본값: 시뮬레이터 (개발 환경)
    return SimulatedGateController()
