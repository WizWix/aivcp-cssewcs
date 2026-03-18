"""
Background detection loop that runs in a dedicated thread.
Owns the camera capture, ONNX inference, frame distribution, and violation dispatching.
"""

import asyncio
import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Coroutine

import cv2
import numpy as np

from backend.config import Settings
from backend.core.event_bus import EventBus
from backend.core.frame_buffer import FrameBuffer
from backend.core.stream_manager import StreamManager
from backend.models.onnx_detector import PPEDetector
from backend.models.schemas import ComplianceResult

logger = logging.getLogger(__name__)

# 카메라 재연결 시도 간격 (지수 백오프: 1, 2, 4, 8, ... 최대 30초)
_RECONNECT_BASE_SEC = 1.0
_RECONNECT_MAX_SEC = 30.0

# "카메라 없음" 상태를 표시하는 플레이스홀더 프레임 높이/폭
_NO_SIGNAL_H = 480
_NO_SIGNAL_W = 640


class DetectionLoop:
    """카메라 캡처와 PPE 추론을 전담하는 백그라운드 스레드 관리자.

    SRP: 이 클래스는 오직 영상 입력 → 추론 → 결과 디스패치 책임만 담당한다.
    DIP: ViolationCallback을 인터페이스(Callable)로 받아 의존성을 역전시킨다.
    """

    # 위반 콜백 타입 정의: async 함수 참조
    ViolationCallback = Callable[
        [list[np.ndarray], ComplianceResult, str],
        Coroutine[Any, Any, None],
    ]
    # 준수 감지 콜백: 인자 없는 코루틴 (total_detections만 증가)
    CompliantCallback = Callable[[], Coroutine[Any, Any, None]]

    def __init__(
        self,
        config: Settings,
        detector: PPEDetector,
        frame_buffer: FrameBuffer,
        stream_manager: StreamManager,
        event_bus: EventBus,
        violation_callback: ViolationCallback,
        compliant_callback: "DetectionLoop.CompliantCallback | None" = None,
    ) -> None:
        self._config = config
        self._detector = detector
        self._frame_buffer = frame_buffer
        self._stream_manager = stream_manager
        self._event_bus = event_bus
        self._violation_callback = violation_callback
        self._compliant_callback = compliant_callback

        # 스레드 제어
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # asyncio 루프 참조 (lifespan에서 주입)
        self._loop: asyncio.AbstractEventLoop | None = None

        # 영상 소스 상태
        self._cap: cv2.VideoCapture | None = None
        self._source_type: str = "none"  # "rtsp" | "file" | "webcam" | "none"
        self._source_url: str | None = None
        self._file_start_ts: datetime | None = None
        self._source_lock = threading.Lock()

        # 오탐 방지용 시간 평활화 윈도우
        # violation smoother: True = 이 프레임에서 위반 감지됨
        # compliant smoother: True = 이 프레임에서 보호구 착용 준수 감지됨
        self._smoother: deque[bool] = deque(maxlen=config.smoothing_window_size)
        self._compliant_smoother: deque[bool] = deque(maxlen=config.smoothing_window_size)

        # 위반 쿨다운: 마지막 위반 발생 시각 (epoch seconds)
        self._last_violation_time: float = 0.0
        # 준수 감지 쿨다운: 마지막 준수 기록 시각
        self._last_compliant_time: float = 0.0

        # 위반 후 추가 프레임 캡처 중 여부 (클립 생성용)
        self._post_violation_frames_remaining: int = 0
        self._post_violation_buffer: list[np.ndarray] = []
        self._pre_violation_snapshot: list[np.ndarray] = []
        self._pending_result: ComplianceResult | None = None

    # ── 생명주기 메서드 ────────────────────────────────────────────────────────

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """감지 루프 스레드를 시작한다.

        Args:
            loop: FastAPI lifespan에서 가져온 asyncio 이벤트 루프
        """
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="DetectionLoop",
            daemon=True,
        )
        self._thread.start()
        logger.info("감지 루프 스레드 시작됨")

    def stop(self) -> None:
        """감지 루프 스레드를 중지하고 카메라를 해제한다."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._release_cap()
        logger.info("감지 루프 스레드 종료됨")

    # ── 소스 전환 메서드 ───────────────────────────────────────────────────────

    def set_source_rtsp(self, url: str) -> None:
        """RTSP 스트림으로 영상 소스를 변경한다. (스레드 안전)"""
        with self._source_lock:
            self._source_url = url
            self._source_type = "rtsp"
            self._file_start_ts = None
            self._release_cap()  # 루프에서 다음 반복 시 재연결됨
        logger.info(f"RTSP 소스 변경: {url}")

    def set_source_webcam(self, device_id: int = 0) -> None:
        """연결된 웹캠으로 영상 소스를 변경한다. (스레드 안전)"""
        with self._source_lock:
            self._source_url = str(device_id)  # 표시용 (device index)
            self._source_type = "webcam"
            self._file_start_ts = None
            self._release_cap()
        logger.info(f"웹캠 소스 변경: device_id={device_id}")

    def set_source_file(self, path: str, start_timestamp: datetime) -> None:
        """로컬 영상 파일로 소스를 변경한다. (스레드 안전)"""
        with self._source_lock:
            self._source_url = path
            self._source_type = "file"
            self._file_start_ts = start_timestamp
            self._release_cap()
        logger.info(f"파일 소스 변경: {path} (시작: {start_timestamp})")

    @property
    def source_status(self) -> dict[str, Any]:
        """현재 소스 상태를 반환한다."""
        return {
            "source_type": self._source_type,
            "source_url": self._source_url,
            "is_running": self._thread is not None and self._thread.is_alive(),
        }

    # ── 내부 구현 ──────────────────────────────────────────────────────────────

    def _release_cap(self) -> None:
        """VideoCapture 객체를 안전하게 해제한다."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _open_source(self) -> bool:
        """현재 설정된 소스로 VideoCapture를 열고 성공 여부를 반환한다."""
        with self._source_lock:
            url = self._source_url

        if url is None:
            return False

        # 웹캠은 정수 인덱스 + DirectShow 백엔드 (Windows MSMF보다 안정적)
        # RTSP/파일은 문자열 경로
        if self._source_type == "webcam":
            cap = cv2.VideoCapture(int(url), cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(url)

        if not cap.isOpened():
            logger.warning(f"영상 소스 열기 실패: {url}")
            return False

        self._cap = cap
        logger.info(f"영상 소스 열기 성공: {url}")
        return True

    def _make_no_signal_frame(self) -> np.ndarray:
        """카메라 신호 없음을 나타내는 플레이스홀더 프레임을 생성한다."""
        frame = np.zeros((_NO_SIGNAL_H, _NO_SIGNAL_W, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "NO SIGNAL",
            (_NO_SIGNAL_W // 2 - 100, _NO_SIGNAL_H // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (100, 100, 100),
            2,
            cv2.LINE_AA,
        )
        return frame

    def _check_violation_majority(self) -> bool:
        """평활화 윈도우의 다수결로 위반 여부를 판단한다.

        윈도우가 가득 찼을 때만 판단하여 시스템 시작 직후 오탐을 방지한다.
        """
        if len(self._smoother) < self._config.smoothing_window_size:
            return False
        # 과반수가 위반 프레임이면 위반으로 판정
        violation_count = sum(1 for v in self._smoother if v)
        return violation_count > self._config.smoothing_window_size // 2

    def _check_compliant_majority(self) -> bool:
        """평활화 윈도우의 다수결로 보호구 착용 준수 여부를 판단한다."""
        if len(self._compliant_smoother) < self._config.smoothing_window_size:
            return False
        compliant_count = sum(1 for v in self._compliant_smoother if v)
        return compliant_count > self._config.smoothing_window_size // 2

    def _trigger_compliant_detection(self) -> None:
        """준수 감지 시 total_detections 카운터 증가를 비동기 큐에 등록한다."""
        now = time.time()
        if now - self._last_compliant_time < self._config.compliant_detection_cooldown_sec:
            return
        if self._loop is None or self._compliant_callback is None:
            return

        self._last_compliant_time = now
        logger.info("준수 감지 - 통계 업데이트")
        self._loop.call_soon_threadsafe(
            asyncio.ensure_future,
            self._compliant_callback(),
        )

    def _trigger_violation(self, result: ComplianceResult) -> None:
        """위반 감지 시 클립 캡처와 비동기 처리를 시작한다."""
        now = time.time()

        # 쿨다운 체크: 마지막 위반 후 설정된 시간이 지나지 않았으면 무시
        if now - self._last_violation_time < self._config.violation_cooldown_sec:
            return

        self._last_violation_time = now
        logger.info(f"위반 감지! 미착용: helmet={not result.has_helmet}, jacket={not result.has_jacket}")

        # 위반 전 프레임 스냅샷 저장
        self._pre_violation_snapshot = self._frame_buffer.snapshot()

        # 위반 후 프레임 추가 캡처 시작
        self._post_violation_frames_remaining = self._config.post_violation_frames
        self._post_violation_buffer = []
        self._pending_result = result

    def _finalize_violation(self) -> None:
        """위반 후 추가 캡처 완료 시 비동기 위반 처리를 큐에 등록한다."""
        if self._loop is None or self._pending_result is None:
            return

        # 위반 전 + 위반 후 프레임 합치기
        all_frames = self._pre_violation_snapshot + self._post_violation_buffer
        result = self._pending_result
        source_type = self._source_type

        # asyncio 이벤트 루프에 코루틴 스케줄링 (스레드 → 루프 경계)
        self._loop.call_soon_threadsafe(
            asyncio.ensure_future,
            self._violation_callback(all_frames, result, source_type),
        )

        # 상태 초기화
        self._post_violation_buffer = []
        self._pre_violation_snapshot = []
        self._pending_result = None

    def _run(self) -> None:
        """감지 루프의 메인 스레드 함수."""
        reconnect_delay = _RECONNECT_BASE_SEC
        frame_interval = 1.0 / self._config.detection_fps_target

        while not self._stop_event.is_set():
            # ── 소스 연결 또는 재연결 ───────────────────────────────────────
            if self._cap is None:
                if self._source_url is None:
                    # 소스가 설정되지 않은 경우 대기
                    no_signal = self._make_no_signal_frame()
                    if self._loop:
                        self._stream_manager.push(no_signal, no_signal, self._loop)
                    time.sleep(1.0)
                    continue

                if not self._open_source():
                    logger.warning(f"{reconnect_delay:.0f}초 후 재연결 시도...")
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX_SEC)
                    continue

                reconnect_delay = _RECONNECT_BASE_SEC  # 연결 성공 시 백오프 초기화

            # ── 프레임 읽기 ────────────────────────────────────────────────
            loop_start = time.monotonic()

            assert self._cap is not None
            ret, frame = self._cap.read()

            if not ret:
                logger.warning("프레임 읽기 실패 - 카메라 재연결 시도")
                self._release_cap()
                no_signal = self._make_no_signal_frame()
                if self._loop:
                    self._stream_manager.push(no_signal, no_signal, self._loop)
                continue

            # ── AI 추론 ────────────────────────────────────────────────────
            result = self._detector.detect(frame)
            annotated = self._detector.draw_boxes(frame, result)

            # ── 프레임 배포 ────────────────────────────────────────────────
            self._frame_buffer.append(frame)

            if self._loop:
                self._stream_manager.push(frame, annotated, self._loop)

            # ── 위반 후 추가 캡처 처리 ────────────────────────────────────
            if self._post_violation_frames_remaining > 0:
                self._post_violation_buffer.append(frame)
                self._post_violation_frames_remaining -= 1
                if self._post_violation_frames_remaining == 0:
                    self._finalize_violation()

            # ── 시간 평활화 및 위반/준수 판정 ────────────────────────────
            elif self._pending_result is None:
                # 이 프레임에서 보호구 미착용 여부
                frame_has_violation = not result.is_compliant and bool(result.detections)
                # 이 프레임에서 보호구 착용 준수 여부 (사람이 감지되어야 함)
                frame_is_compliant = result.is_compliant and bool(result.detections)

                self._smoother.append(frame_has_violation)
                self._compliant_smoother.append(frame_is_compliant)

                if self._check_violation_majority():
                    self._trigger_violation(result)
                    self._smoother.clear()
                    self._compliant_smoother.clear()
                elif self._check_compliant_majority():
                    self._trigger_compliant_detection()
                    self._compliant_smoother.clear()  # 쿨다운 중 중복 트리거 방지

            # ── FPS 제어 (목표 FPS 초과 시 슬립) ─────────────────────────
            elapsed = time.monotonic() - loop_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("감지 루프 종료")
