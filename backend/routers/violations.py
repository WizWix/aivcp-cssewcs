"""
Violation log CRUD router.
"""

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request

from backend.database import get_db
from backend.models.schemas import ViolationListResponse, ViolationResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/violations", response_model=ViolationListResponse)
async def list_violations(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    filter_date: date | None = Query(None, alias="date", description="날짜 필터 (YYYY-MM-DD)"),
):
    """위반 기록 목록을 페이지네이션으로 반환한다.

    최신 기록이 먼저 나오도록 occurred_at DESC 정렬한다.
    날짜 필터를 사용하면 해당 날짜의 기록만 반환한다.
    """
    db = await get_db()
    offset = (page - 1) * limit

    # 날짜 필터 적용 여부에 따라 쿼리 분기
    if filter_date is not None:
        date_str = filter_date.isoformat()
        count_row = await db.execute(
            "SELECT COUNT(*) FROM violations WHERE date(occurred_at) = ?",
            (date_str,),
        )
        rows_cursor = await db.execute(
            """
            SELECT id, occurred_at, clip_path, missing_helmet, missing_jacket,
                   confidence, source_type
            FROM violations
            WHERE date(occurred_at) = ?
            ORDER BY occurred_at DESC
            LIMIT ? OFFSET ?
            """,
            (date_str, limit, offset),
        )
    else:
        count_row = await db.execute("SELECT COUNT(*) FROM violations")
        rows_cursor = await db.execute(
            """
            SELECT id, occurred_at, clip_path, missing_helmet, missing_jacket,
                   confidence, source_type
            FROM violations
            ORDER BY occurred_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

    total_row = await count_row.fetchone()
    total = total_row[0] if total_row else 0

    rows = await rows_cursor.fetchall()
    items = [
        ViolationResponse(
            id=row["id"],
            occurred_at=row["occurred_at"],
            clip_path=row["clip_path"],
            missing_helmet=bool(row["missing_helmet"]),
            missing_jacket=bool(row["missing_jacket"]),
            confidence=row["confidence"],
            source_type=row["source_type"],
        )
        for row in rows
    ]

    return ViolationListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/violations/{violation_id}", response_model=ViolationResponse)
async def get_violation(violation_id: int):
    """특정 위반 기록의 상세 정보를 반환한다."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id, occurred_at, clip_path, missing_helmet, missing_jacket,
               confidence, source_type
        FROM violations
        WHERE id = ?
        """,
        (violation_id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"위반 기록을 찾을 수 없습니다: ID={violation_id}")

    return ViolationResponse(
        id=row["id"],
        occurred_at=row["occurred_at"],
        clip_path=row["clip_path"],
        missing_helmet=bool(row["missing_helmet"]),
        missing_jacket=bool(row["missing_jacket"]),
        confidence=row["confidence"],
        source_type=row["source_type"],
    )
