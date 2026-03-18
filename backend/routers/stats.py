"""
Statistics router for daily/weekly/monthly compliance data.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Query

from backend.database import get_db
from backend.models.schemas import (
    DailyStatsResponse,
    MonthlyStatsResponse,
    WeeklyStatsResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _make_empty_daily(date_str: str) -> DailyStatsResponse:
    """해당 날짜의 기록이 없을 때 사용할 빈 통계 객체를 생성한다.

    Chart.js가 빈 배열이 아닌 0값을 기대하므로 필수적이다.
    """
    return DailyStatsResponse(
        date=date_str,
        total_detections=0,
        violations_count=0,
        no_helmet_count=0,
        no_jacket_count=0,
        compliance_rate=1.0,
    )


def _calc_compliance_rate(total: int, violations: int) -> float:
    """준수율(0.0~1.0)을 계산한다. 분모가 0이면 1.0(완벽)으로 반환한다."""
    if total == 0:
        return 1.0
    return max(0.0, (total - violations) / total)


@router.get("/stats/daily", response_model=DailyStatsResponse)
async def get_daily_stats(
    filter_date: date | None = Query(None, alias="date", description="날짜 (기본: 오늘)"),
):
    """특정 날짜의 통계를 반환한다. 날짜를 생략하면 오늘 통계를 반환한다."""
    target_date = filter_date or date.today()
    date_str = target_date.isoformat()

    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM daily_stats WHERE date = ?",
        (date_str,),
    )
    row = await cursor.fetchone()

    if row is None:
        return _make_empty_daily(date_str)

    return DailyStatsResponse(
        date=row["date"],
        total_detections=row["total_detections"],
        violations_count=row["violations_count"],
        no_helmet_count=row["no_helmet_count"],
        no_jacket_count=row["no_jacket_count"],
        compliance_rate=_calc_compliance_rate(row["total_detections"], row["violations_count"]),
    )


@router.get("/stats/weekly", response_model=WeeklyStatsResponse)
async def get_weekly_stats(
    week_start: date | None = Query(
        None,
        description="주 시작 날짜 (기본: 이번 주 월요일)",
    ),
):
    """주간(7일) 통계를 날짜별 리스트로 반환한다."""
    if week_start is None:
        today = date.today()
        # 이번 주 월요일로 자동 설정 (weekday: 0=월, 6=일)
        week_start = today - timedelta(days=today.weekday())

    db = await get_db()

    # 7일치 날짜 목록 생성
    date_list = [week_start + timedelta(days=i) for i in range(7)]
    date_strs = [d.isoformat() for d in date_list]

    # 한 번의 쿼리로 7일치 데이터 조회
    placeholders = ",".join("?" * 7)
    cursor = await db.execute(
        f"SELECT * FROM daily_stats WHERE date IN ({placeholders})",
        date_strs,
    )
    rows = await cursor.fetchall()

    # DB에서 가져온 데이터를 날짜 키로 인덱싱
    rows_by_date = {row["date"]: row for row in rows}

    # 7일 전체에 대해 없는 날짜는 빈 통계로 채우기 (미래 날짜 제외)
    today = date.today()
    days: list[DailyStatsResponse] = []
    total_violations = 0
    for date_str in date_strs:
        if date.fromisoformat(date_str) > today:
            break
        if date_str in rows_by_date:
            row = rows_by_date[date_str]
            stat = DailyStatsResponse(
                date=row["date"],
                total_detections=row["total_detections"],
                violations_count=row["violations_count"],
                no_helmet_count=row["no_helmet_count"],
                no_jacket_count=row["no_jacket_count"],
                compliance_rate=_calc_compliance_rate(row["total_detections"], row["violations_count"]),
            )
            total_violations += row["violations_count"]
        else:
            stat = _make_empty_daily(date_str)
        days.append(stat)

    return WeeklyStatsResponse(
        week_start=week_start.isoformat(),
        days=days,
        total_violations=total_violations,
    )


@router.get("/stats/monthly", response_model=MonthlyStatsResponse)
async def get_monthly_stats(
    year: int | None = Query(None, description="연도 (기본: 올해)"),
    month: int | None = Query(None, ge=1, le=12, description="월 (기본: 이번 달)"),
):
    """월간 통계를 날짜별 리스트로 반환한다."""
    today = date.today()
    target_year = year or today.year
    target_month = month or today.month

    import calendar

    _, days_in_month = calendar.monthrange(target_year, target_month)

    db = await get_db()

    # 해당 월 전체 데이터 조회 (LIKE 사용)
    month_prefix = f"{target_year:04d}-{target_month:02d}-%"
    cursor = await db.execute(
        "SELECT * FROM daily_stats WHERE date LIKE ?",
        (month_prefix,),
    )
    rows = await cursor.fetchall()
    rows_by_date = {row["date"]: row for row in rows}

    today = date.today()
    days: list[DailyStatsResponse] = []
    total_violations = 0
    for day_num in range(1, days_in_month + 1):
        date_str = f"{target_year:04d}-{target_month:02d}-{day_num:02d}"
        if date.fromisoformat(date_str) > today:
            break
        if date_str in rows_by_date:
            row = rows_by_date[date_str]
            stat = DailyStatsResponse(
                date=row["date"],
                total_detections=row["total_detections"],
                violations_count=row["violations_count"],
                no_helmet_count=row["no_helmet_count"],
                no_jacket_count=row["no_jacket_count"],
                compliance_rate=_calc_compliance_rate(row["total_detections"], row["violations_count"]),
            )
            total_violations += row["violations_count"]
        else:
            stat = _make_empty_daily(date_str)
        days.append(stat)

    return MonthlyStatsResponse(
        year=target_year,
        month=target_month,
        days=days,
        total_violations=total_violations,
    )
