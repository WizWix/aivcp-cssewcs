"""
Violation handling orchestrator.
Coordinates clip saving, DB logging, audio alert, gate lock, and SSE notification.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.config import Settings
from backend.core.event_bus import EventBus
from backend.database import get_db
from backend.models.schemas import ComplianceResult, ViolationEvent
from backend.services.audio_service import AudioService
from backend.services.gate_service import GateController

logger = logging.getLogger(__name__)

# 저장할 영상 클립의 FPS (실제 캡처 FPS와 맞춤)
_CLIP_FPS = 10

# 시도할 코덱 우선순위: 브라우저 재생 호환 H.264 계열을 먼저 시도하고,
# OpenH264 버전 불일치 등으로 실패하면 다음 후보로 폴백한다.
_CODEC_CANDIDATES = ["avc1", "H264", "mp4v"]


class ViolationService:
    """PPE 위반 이벤트를 처리하는 오케스트레이터.

    SRP: 각 하위 작업(클립 저장, DB 기록, 오디오, 게이트, SSE)은
         전담 서비스/모듈에 위임하고 이 클래스는 순서 조율만 담당한다.
    DIP: 하위 서비스를 인터페이스(GateController)나 인스턴스 주입으로 받는다.
    """

    def __init__(
        self,
        config: Settings,
        event_bus: EventBus,
        audio_service: AudioService,
        gate_controller: GateController,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._audio_service = audio_service
        self._gate_controller = gate_controller

        # 동일 시각에 중복 DB 쓰기를 막기 위한 락
        self._db_lock = asyncio.Lock()

        # 클립 저장 디렉터리 생성 (없는 경우)
        Path(config.clips_dir).mkdir(parents=True, exist_ok=True)

    async def handle_violation(
        self,
        frames: list[np.ndarray],
        result: ComplianceResult,
        source_type: str,
    ) -> None:
        """위반 이벤트를 처리하는 메인 코루틴.

        실행 순서:
        1. 클립 파일 저장 (run_in_executor로 블로킹 I/O 비차단화)
        2. DB에 위반 기록 저장
        3. 오디오 알림 재생
        4. 게이트 잠금
        5. SSE 이벤트 브로드캐스트

        Args:
            frames: 위반 전후의 프레임 목록 (클립 생성 재료)
            result: 감지 결과 (착용 여부 + 신뢰도)
            source_type: 영상 소스 종류 ("rtsp" | "file")
        """
        occurred_at = datetime.now()
        missing = result.missing_items

        logger.info(f"위반 처리 시작 | 시각: {occurred_at.isoformat()} | 미착용: {missing}")

        # 1. 영상 클립 저장 (블로킹 I/O → executor로 오프로드)
        clip_filename = self._make_clip_filename(occurred_at, missing["helmet"], missing["jacket"])
        clip_path = Path(self._config.clips_dir) / clip_filename
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                self._save_clip,
                frames,
                clip_path,
            )
        except Exception as e:
            logger.error(f"클립 저장 실패: {e}")
            clip_filename = ""  # 실패 시 빈 경로로 DB 기록

        # DB 상의 상대 경로 (clips/ 디렉터리 기준)
        db_clip_path = f"clips/{clip_filename}" if clip_filename else ""

        # 평균 신뢰도 계산
        avg_confidence = self._calc_avg_confidence(result)

        # 2. DB 기록 (violations + daily_stats)
        violation_id: int | None = None
        try:
            async with self._db_lock:
                violation_id = await self._write_db(
                    occurred_at=occurred_at,
                    clip_path=db_clip_path,
                    missing_helmet=missing["helmet"],
                    missing_jacket=missing["jacket"],
                    confidence=avg_confidence,
                    source_type=source_type,
                )
        except Exception as e:
            logger.error(f"DB 기록 실패: {e}")

        # 3. 오디오 알림 (비차단 재생)
        self._audio_service.play_non_blocking(
            missing_helmet=missing["helmet"],
            missing_jacket=missing["jacket"],
        )

        # 4. 게이트 잠금
        self._gate_controller.lock(self._config.gate_lock_duration_sec)

        # 5. SSE 이벤트 브로드캐스트
        if violation_id is not None:
            event = ViolationEvent(
                violation_id=violation_id,
                occurred_at=occurred_at.isoformat(),
                missing_helmet=missing["helmet"],
                missing_jacket=missing["jacket"],
                clip_url=f"/clips/{clip_filename}" if clip_filename else "",
            )
            payload = event.model_dump()
            payload["event_type"] = "violation"
            self._event_bus.publish(payload)

        logger.info(f"위반 처리 완료 | ID: {violation_id}")

    async def log_compliant_detection(self) -> None:
        """보호구 착용 준수 감지를 daily_stats에 기록한다.

        violations_count는 증가시키지 않고 total_detections만 증가시킨다.
        이로써 compliance_rate = (total - violations) / total 계산이 의미 있어진다.
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        try:
            async with self._db_lock:
                db = await get_db()
                await db.execute(
                    """
                    INSERT INTO daily_stats (date, total_detections, violations_count, no_helmet_count, no_jacket_count)
                    VALUES (?, 1, 0, 0, 0)
                    ON CONFLICT(date) DO UPDATE SET
                        total_detections = total_detections + 1
                    """,
                    (date_str,),
                )
                await db.commit()
            # SSE 준수 이벤트 브로드캐스트
            self._event_bus.publish({
                "event_type": "compliant",
                "occurred_at": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error(f"준수 감지 DB 기록 실패: {e}")

    @staticmethod
    def _make_clip_filename(occurred_at: datetime, missing_helmet: bool, missing_jacket: bool) -> str:
        """위반 발생 시각 기반 클립 파일명을 생성한다."""
        date_dir = occurred_at.strftime('%Y%m%d')
        time_part = occurred_at.strftime('%H%M%S') + '-' + occurred_at.strftime('%f')[:3]
        if missing_helmet and missing_jacket:
            violation_type = 'hj'
        elif missing_helmet:
            violation_type = 'h'
        elif missing_jacket:
            violation_type = 'j'
        else:
            violation_type = 'unknown'  # shouldn't happen
        return f"{date_dir}/{time_part}-{violation_type}.mp4"

    @staticmethod
    def _calc_avg_confidence(result: ComplianceResult) -> float | None:
        """감지된 객체들의 평균 신뢰도를 계산한다."""
        if not result.detections:
            return None
        return sum(d.confidence for d in result.detections) / len(result.detections)

    def _save_clip(self, frames: list[np.ndarray], output_path: Path) -> None:
        """프레임 목록을 MP4 영상 파일로 저장한다.

        executor 스레드에서 실행되어 이벤트 루프를 블로킹하지 않는다.
        avc1(H.264) → H264(FFmpeg libx264) → mp4v 순서로 코덱을 시도한다.
        """
        if not frames:
            logger.warning("저장할 프레임이 없습니다.")
            return

        h, w = frames[0].shape[:2]

        # 날짜 디렉터리 생성
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer: cv2.VideoWriter | None = None
        used_codec = ""
        for codec in _CODEC_CANDIDATES:
            candidate = cv2.VideoWriter(
                str(output_path),
                cv2.VideoWriter_fourcc(*codec),
                _CLIP_FPS,
                (w, h),
            )
            if candidate.isOpened():
                writer = candidate
                used_codec = codec
                break
            candidate.release()

        if writer is None:
            raise RuntimeError("사용 가능한 영상 인코더가 없습니다 (avc1/H264/mp4v 모두 실패)")

        try:
            for frame in frames:
                writer.write(frame)
        finally:
            writer.release()

        file_size = output_path.stat().st_size
        logger.info(f"클립 저장 완료: {output_path} ({len(frames)} 프레임, codec={used_codec}, size={file_size} bytes)")

    async def _write_db(
        self,
        occurred_at: datetime,
        clip_path: str,
        missing_helmet: bool,
        missing_jacket: bool,
        confidence: float | None,
        source_type: str,
    ) -> int:
        """violations 테이블에 위반 기록을 INSERT하고 daily_stats를 업데이트한다.

        Returns:
            새로 생성된 위반 레코드의 ID
        """
        db = await get_db()

        # violations 테이블 INSERT
        cursor = await db.execute(
            """
            INSERT INTO violations
                (occurred_at, clip_path, missing_helmet, missing_jacket, confidence, source_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                occurred_at.isoformat(),
                clip_path,
                1 if missing_helmet else 0,
                1 if missing_jacket else 0,
                confidence,
                source_type,
            ),
        )
        violation_id = cursor.lastrowid

        # daily_stats UPSERT (날짜별 집계)
        date_str = occurred_at.strftime("%Y-%m-%d")
        await db.execute(
            """
            INSERT INTO daily_stats (date, total_detections, violations_count, no_helmet_count, no_jacket_count)
            VALUES (?, 1, 1, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_detections = total_detections + 1,
                violations_count = violations_count + 1,
                no_helmet_count  = no_helmet_count  + excluded.no_helmet_count,
                no_jacket_count  = no_jacket_count  + excluded.no_jacket_count
            """,
            (
                date_str,
                1 if missing_helmet else 0,
                1 if missing_jacket else 0,
            ),
        )

        await db.commit()
        return violation_id
