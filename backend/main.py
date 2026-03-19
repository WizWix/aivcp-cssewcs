"""
FastAPI application factory and lifespan manager.
Wires together all components and mounts routers.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.core.detection_loop import DetectionLoop
from backend.core.event_bus import EventBus
from backend.core.frame_buffer import FrameBuffer
from backend.core.stream_manager import StreamManager
from backend.database import close_db, init_db
from backend.models.onnx_detector import PPEDetector
from backend.routers import events, source, stats, stream, violations
from backend.services.audio_service import AudioService
from backend.services.gate_service import create_gate_controller
from backend.services.violation_service import ViolationService

# 로깅 설정: 콘솔에 시각·레벨·모듈명 포함 출력
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 앱 생명주기 관리자.

    yield 이전: 서버 시작 시 실행 (DB 초기화, 모델 로드, 감지 루프 시작)
    yield 이후: 서버 종료 시 실행 (감지 루프 중지, DB 연결 닫기)
    """
    logger.info("=== 시스템 시작 ===")

    # 1. 데이터베이스 초기화
    await init_db()

    # 2. asyncio 이벤트 루프 참조 획득 (백그라운드 스레드 → 루프 통신용)
    loop = asyncio.get_running_loop()

    # 3. 핵심 인프라 컴포넌트 생성
    event_bus = EventBus()
    event_bus.set_loop(loop)

    stream_manager = StreamManager()
    frame_buffer = FrameBuffer(settings.frame_buffer_size)

    # 4. AI 모델 로드 (ONNX 파일이 없으면 경고 후 계속 진행)
    detector: PPEDetector | None = None
    ppe_model_path = Path(settings.ppe_model_path)
    person_model_path = Path(settings.person_model_path)
    if ppe_model_path.exists():
        try:
            detector = PPEDetector(
                onnx_path=str(ppe_model_path),
                conf_threshold=settings.conf_threshold,
                nms_iou_threshold=settings.nms_iou_threshold,
                input_size=settings.model_input_size,
                person_weights=str(person_model_path) if person_model_path.exists() else None,
                person_conf=0.45,
            )
            logger.info("PPE 감지 모델 로드 완료")
        except Exception as e:
            logger.error(f"PPE 감지 모델 로드 실패: {e}")
    else:
        logger.warning(f"ONNX 모델 파일이 없습니다: {ppe_model_path}\n  scripts/export_onnx.py를 실행하여 모델을 생성하세요.")

    # 5. 서비스 컴포넌트 생성
    audio_service = AudioService(Path(settings.audio_dir))
    gate_controller = create_gate_controller(
        gate_type=settings.gate_type,
        port=settings.gate_serial_port,
        baudrate=settings.gate_serial_baudrate,
    )
    violation_service = ViolationService(
        config=settings,
        event_bus=event_bus,
        audio_service=audio_service,
        gate_controller=gate_controller,
    )

    # 6. 감지 루프 생성 (모델이 없으면 None 더미로 처리)
    if detector is not None:
        detection_loop = DetectionLoop(
            config=settings,
            detector=detector,
            frame_buffer=frame_buffer,
            stream_manager=stream_manager,
            event_bus=event_bus,
            violation_callback=violation_service.handle_violation,
            compliant_callback=violation_service.log_compliant_detection,
        )
        # 기본 소스: 설정된 RTSP URL로 자동 시작
        detection_loop.set_source_rtsp(settings.rtsp_url)
        detection_loop.start(loop)
        logger.info(f"감지 루프 시작 (RTSP: {settings.rtsp_url})")
    else:
        # 모델 없음: 스트리밍만 제공하는 더미 루프
        detection_loop = _DummyDetectionLoop(stream_manager, loop)
        detection_loop.start()
        logger.warning("AI 모델 없이 시작 - 영상 스트리밍만 가능합니다.")

    # 7. app.state에 컴포넌트 등록 (라우터에서 접근 가능하도록)
    shutdown_event = asyncio.Event()
    app.state.shutdown_event = shutdown_event
    app.state.detection_loop = detection_loop
    app.state.event_bus = event_bus
    app.state.stream_manager = stream_manager

    logger.info(f"=== 서버 준비 완료 | http://{settings.host}:{settings.port} ===")

    yield  # 서버 실행 중

    # 종료 처리: shutdown_event를 먼저 설정하여 MJPEG/SSE generator가 즉시 루프를 탈출하도록 함
    logger.info("=== 시스템 종료 ===")
    shutdown_event.set()
    detection_loop.stop()
    await close_db()
    logger.info("종료 완료")


def create_app() -> FastAPI:
    """FastAPI 앱 인스턴스를 생성하고 설정한다."""
    app = FastAPI(
        title="PPE Detection System",
        description="공사 현장 안전 보호구 착용 감지 시스템",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── API 라우터 등록 ────────────────────────────────────────────────────────
    prefix = "/api"
    app.include_router(stream.router, prefix=prefix, tags=["stream"])
    app.include_router(events.router, prefix=prefix, tags=["events"])
    app.include_router(violations.router, prefix=prefix, tags=["violations"])
    app.include_router(stats.router, prefix=prefix, tags=["stats"])
    app.include_router(source.router, prefix=prefix, tags=["source"])

    # ── 정적 파일 서빙 ────────────────────────────────────────────────────────
    # 위반 클립 영상 파일 (영상 플레이어에서 직접 접근)
    clips_dir = Path(settings.clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/clips", StaticFiles(directory=str(clips_dir)), name="clips")

    # 프론트엔드 SPA (마지막에 마운트: 더 구체적인 경로 우선)
    frontend_dir = Path(__file__).parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


# ── 더미 루프 (모델 없을 때 영상 스트리밍용) ─────────────────────────────────


class _DummyDetectionLoop:
    """AI 모델 없이 영상 없음 화면만 스트리밍하는 더미 루프."""

    import threading as _threading

    def __init__(self, stream_manager: StreamManager, loop: asyncio.AbstractEventLoop) -> None:
        import threading

        self._stream_manager = stream_manager
        self._loop = loop
        self._stop_event = threading.Event()
        self._thread: _threading.Thread | None = None

    def start(self) -> None:
        import threading

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def set_source_rtsp(self, url: str) -> None:
        pass

    def set_source_webcam(self, device_id: int = 0) -> None:
        pass

    def set_source_file(self, path: str, start_timestamp) -> None:
        pass

    @property
    def source_status(self) -> dict:
        return {"source_type": "none", "source_url": None, "is_running": True}

    def _run(self) -> None:
        import time
        import cv2
        import numpy as np

        while not self._stop_event.is_set():
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(
                frame,
                "MODEL NOT LOADED",
                (100, 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (80, 80, 80),
                2,
                cv2.LINE_AA,
            )
            self._stream_manager.push(frame, frame, self._loop)
            time.sleep(1.0)


# ── 앱 인스턴스 ───────────────────────────────────────────────────────────────
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
