"""
Database connection and schema initialization module.
Uses aiosqlite for non-blocking async SQLite access within FastAPI's event loop.
"""

import logging
from pathlib import Path

import aiosqlite

from backend.config import settings

logger = logging.getLogger(__name__)

# 모듈 수준 공유 연결 (FastAPI lifespan 동안 유지)
_db: aiosqlite.Connection | None = None

# ── DDL: 테이블 및 인덱스 정의 ────────────────────────────────────────────────

_CREATE_VIOLATIONS = """
CREATE TABLE IF NOT EXISTS violations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at     TEXT    NOT NULL,
    clip_path       TEXT    NOT NULL,
    missing_helmet  INTEGER NOT NULL DEFAULT 0,
    missing_jacket  INTEGER NOT NULL DEFAULT 0,
    confidence      REAL,
    source_type     TEXT    NOT NULL DEFAULT 'rtsp'
)
"""

_CREATE_DAILY_STATS = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date                TEXT    PRIMARY KEY,
    total_detections    INTEGER NOT NULL DEFAULT 0,
    violations_count    INTEGER NOT NULL DEFAULT 0,
    no_helmet_count     INTEGER NOT NULL DEFAULT 0,
    no_jacket_count     INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_INDEX_OCCURRED_AT = """
CREATE INDEX IF NOT EXISTS idx_violations_occurred_at
ON violations(occurred_at)
"""


async def init_db() -> None:
    """DB 연결을 열고 스키마를 초기화한다.

    WAL 모드를 활성화하여 읽기/쓰기 동시 접근 성능을 향상시킨다.
    FastAPI lifespan의 시작 단계에서 호출해야 한다.
    """
    global _db

    # DB 파일이 위치할 디렉터리가 없으면 생성
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(db_path)

    # Row를 dict처럼 접근 가능하게 설정
    _db.row_factory = aiosqlite.Row

    # WAL 모드: 읽기가 쓰기를 블로킹하지 않도록 설정
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    # 테이블 및 인덱스 생성
    await _db.execute(_CREATE_VIOLATIONS)
    await _db.execute(_CREATE_DAILY_STATS)
    await _db.execute(_CREATE_INDEX_OCCURRED_AT)
    await _db.commit()

    logger.info(f"데이터베이스 초기화 완료: {db_path.resolve()}")


async def get_db() -> aiosqlite.Connection:
    """공유 DB 연결 인스턴스를 반환한다.

    init_db() 호출 이전에 사용하면 RuntimeError가 발생한다.
    """
    if _db is None:
        raise RuntimeError("DB가 초기화되지 않았습니다. init_db()를 먼저 호출하세요.")
    return _db


async def close_db() -> None:
    """DB 연결을 닫는다.

    FastAPI lifespan의 종료 단계에서 호출해야 한다.
    """
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("데이터베이스 연결 닫힘")
