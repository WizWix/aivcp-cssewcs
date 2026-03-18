"""
Application configuration module.
Loads all settings from environment variables via a .env file.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py 위치 기준 프로젝트 루트 (실행 디렉터리와 무관하게 항상 일정)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """애플리케이션 전체 설정 클래스.

    .env 파일 또는 환경 변수에서 값을 자동으로 로드한다.
    pydantic-settings를 사용하여 타입 안전성을 보장한다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── 서버 설정 ────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 3000

    # ── 영상 소스 설정 ────────────────────────────────────────────────────────
    # 기본 RTSP URL (배포 환경에서 .env로 재정의)
    rtsp_url: str = "rtsp://192.168.1.100:554/stream"

    # ── 파일 경로 설정 ────────────────────────────────────────────────────────
    # 절대 경로 기본값 (_PROJECT_ROOT 기준) — .env에서 재정의 가능
    db_path: Path = _PROJECT_ROOT / "data/ppe.db"
    clips_dir: Path = _PROJECT_ROOT / "data/clips"
    audio_dir: Path = _PROJECT_ROOT / "data/audio"
    models_dir: Path = _PROJECT_ROOT / "data/models"

    # ── AI 모델 설정 ──────────────────────────────────────────────────────────
    @property
    def ppe_model_path(self) -> Path:
        """PPE 감지 ONNX 모델 경로"""
        return self.models_dir / "best.onnx"

    # ONNX 추론 입력 크기 (낮출수록 추론 속도 증가, 정확도 감소)
    model_input_size: int = 640

    # ── 감지 임계값 설정 ──────────────────────────────────────────────────────
    conf_threshold: float = 0.50  # 최소 감지 신뢰도
    nms_iou_threshold: float = 0.45  # NMS IoU 임계값

    # ── 감지 루프 설정 ────────────────────────────────────────────────────────
    # 목표 추론 FPS (CPU 저사양 환경 고려)
    detection_fps_target: int = 10

    # 오탐 방지를 위한 시간 평활화 윈도우 크기 (프레임 수)
    smoothing_window_size: int = 7

    # 위반 감지 후 재감지 억제 시간 (초) - 동일 인원 중복 기록 방지
    violation_cooldown_sec: float = 10.0

    # 준수 감지 후 재기록 억제 시간 (초) - total_detections 중복 증가 방지
    compliant_detection_cooldown_sec: float = 30.0

    # ── 영상 클립 설정 ────────────────────────────────────────────────────────
    # 링 버퍼에 보관할 최대 프레임 수 (위반 전 영상 저장용)
    # 기본값 30 ≈ 3초 @ 10fps
    frame_buffer_size: int = 30

    # 위반 후 추가로 캡처할 프레임 수 (위반 후 영상 저장용)
    post_violation_frames: int = 20

    # ── 게이트 제어 설정 ──────────────────────────────────────────────────────
    # "simulated" | "serial"
    gate_type: str = "simulated"

    # 게이트 잠금 지속 시간 (초)
    gate_lock_duration_sec: int = 5

    # 시리얼 게이트 사용 시 COM 포트 (예: "COM3" 또는 "/dev/ttyUSB0")
    gate_serial_port: str = "COM3"
    gate_serial_baudrate: int = 9600


# 전역 설정 인스턴스 (모듈 임포트 시 1회 생성)
settings = Settings()
