"""
Pydantic schemas for API request/response validation and serialization.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 감지 결과 내부 데이터 클래스 ──────────────────────────────────────────────


class Detection(BaseModel):
    """단일 객체 감지 결과"""

    label: str  # 클래스 이름 (예: "helmet", "jacket")
    confidence: float  # 감지 신뢰도 (0.0 ~ 1.0)
    bbox: tuple[int, int, int, int]  # 바운딩 박스 (x1, y1, x2, y2)


class ComplianceResult(BaseModel):
    """단일 프레임의 보호구 착용 판단 결과"""

    has_helmet: bool = False
    has_jacket: bool = False
    detections: list[Detection] = Field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        """헬멧과 조끼를 모두 착용한 경우에만 True"""
        return self.has_helmet and self.has_jacket

    @property
    def missing_items(self) -> dict[str, bool]:
        """미착용 항목 딕셔너리 반환"""
        return {
            "helmet": not self.has_helmet,
            "jacket": not self.has_jacket,
        }


# ── API 응답 스키마 ────────────────────────────────────────────────────────────


class ViolationResponse(BaseModel):
    """위반 기록 API 응답 스키마"""

    id: int
    occurred_at: str
    clip_path: str
    missing_helmet: bool
    missing_jacket: bool
    confidence: float | None
    source_type: str


class ViolationListResponse(BaseModel):
    """위반 목록 페이지네이션 응답"""

    items: list[ViolationResponse]
    total: int
    page: int
    limit: int


class DailyStatsResponse(BaseModel):
    """일별 통계 응답"""

    date: str
    total_detections: int
    violations_count: int
    no_helmet_count: int
    no_jacket_count: int
    compliance_rate: float = 0.0  # 계산 필드: (total - violations) / total


class WeeklyStatsResponse(BaseModel):
    """주간 통계 응답 (7일치 일별 데이터)"""

    week_start: str
    days: list[DailyStatsResponse]
    total_violations: int


class MonthlyStatsResponse(BaseModel):
    """월간 통계 응답"""

    year: int
    month: int
    days: list[DailyStatsResponse]
    total_violations: int


# ── API 요청 스키마 ────────────────────────────────────────────────────────────


class RtspSourceRequest(BaseModel):
    """RTSP 소스 변경 요청"""

    url: str = Field(..., description="RTSP 스트림 URL")


class WebcamSourceRequest(BaseModel):
    """웹캠 소스 변경 요청"""

    device_id: int = Field(default=0, ge=0, description="웹캠 디바이스 인덱스 (기본값: 0)")


# ── SSE 이벤트 스키마 ──────────────────────────────────────────────────────────


class ViolationEvent(BaseModel):
    """SSE를 통해 브라우저로 전송되는 위반 알림 이벤트"""

    type: str = "violation"
    violation_id: int
    occurred_at: str
    missing_helmet: bool
    missing_jacket: bool
    clip_url: str


# ── 서버 상태 응답 ────────────────────────────────────────────────────────────


class SourceStatusResponse(BaseModel):
    """현재 영상 소스 상태"""

    source_type: str  # "rtsp" | "file" | "none"
    source_url: str | None = None
    is_running: bool = False
