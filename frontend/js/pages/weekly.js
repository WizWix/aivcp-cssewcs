/**
 * 주간 통계 페이지.
 * 이번 주 7일간의 위반 건수와 준수율을 차트로 표시한다.
 */

import { fetchWeeklyStats } from "../api.js";
import { refreshChart } from "../components/chart-helpers.js";

/** @type {Chart|null} */
let _chart = null;

/** @type {Date} */
let _weekStart = _getThisMonday();

/**
 * 이번 주 월요일 날짜를 반환한다.
 * @returns {Date}
 */
function _getThisMonday() {
  const today = new Date();
  const day = today.getDay(); // 0=일, 1=월
  const diff = day === 0 ? -6 : 1 - day;
  const monday = new Date(today);
  monday.setDate(today.getDate() + diff);
  return monday;
}

/**
 * Date 객체를 "YYYY-MM-DD" 문자열로 변환한다.
 * @param {Date} date
 * @returns {string}
 */
function _toDateString(date) {
  return date.toISOString().slice(0, 10);
}

/**
 * 주간 통계 페이지를 초기화한다.
 * @param {HTMLElement} container
 */
export async function init(container) {
  _weekStart = _getThisMonday();

  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-header__title">주간 현황</h1>
      <p class="page-header__sub">주간 보호구 착용 준수율과 위반 현황입니다.</p>
    </div>

    <div class="card">
      <!-- 주 선택 -->
      <div class="filter-bar" style="margin-bottom:20px;">
        <button class="btn btn--outline" id="prevWeek">◀ 이전 주</button>
        <span id="weekLabel" style="font-weight:600;font-size:13px;"></span>
        <button class="btn btn--outline" id="nextWeek">다음 주 ▶</button>
      </div>

      <!-- 요약 통계 -->
      <div id="weeklySummary" class="stat-grid" style="margin-bottom:20px;"></div>

      <!-- 차트 -->
      <div class="chart-section">
        <div class="chart-section__title">일별 위반 건수 / 준수율</div>
        <div class="chart-container">
          <canvas id="weeklyChart"></canvas>
        </div>
      </div>
    </div>
  `;

  // 이전/다음 주 버튼
  document.getElementById("prevWeek").addEventListener("click", async () => {
    _weekStart.setDate(_weekStart.getDate() - 7);
    await _loadWeeklyData();
  });

  document.getElementById("nextWeek").addEventListener("click", async () => {
    _weekStart.setDate(_weekStart.getDate() + 7);
    await _loadWeeklyData();
  });

  await _loadWeeklyData();
}

/**
 * 주간 데이터를 API에서 조회하여 차트와 요약을 갱신한다.
 */
async function _loadWeeklyData() {
  const dateStr = _toDateString(_weekStart);
  const weekEnd = new Date(_weekStart);
  weekEnd.setDate(_weekStart.getDate() + 6);

  // 주 레이블 갱신
  document.getElementById("weekLabel").textContent =
    `${dateStr} ~ ${_toDateString(weekEnd)}`;

  try {
    const data = await fetchWeeklyStats(dateStr);

    // 차트 데이터 준비
    const labels = data.days.map((d) => {
      const date = new Date(d.date);
      return date.toLocaleDateString("ko-KR", { weekday: "short", month: "numeric", day: "numeric" });
    });
    const violations = data.days.map((d) => d.violations_count);
    const compliance = data.days.map((d) => +(d.compliance_rate * 100).toFixed(1));

    // 차트 갱신
    const canvas = document.getElementById("weeklyChart");
    _chart = refreshChart(_chart, canvas, labels, violations, compliance);

    // 요약 통계
    const totalViolations = data.total_violations;
    const avgCompliance = data.days.reduce((s, d) => s + d.compliance_rate, 0) / data.days.length;

    document.getElementById("weeklySummary").innerHTML = `
      <div class="stat-card">
        <div class="stat-card__label">주간 총 위반</div>
        <div class="stat-card__value stat-card__value--danger">${totalViolations}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card__label">평균 준수율</div>
        <div class="stat-card__value ${avgCompliance >= 0.9 ? "stat-card__value--success" : "stat-card__value--danger"}">
          ${(avgCompliance * 100).toFixed(1)}%
        </div>
      </div>
    `;
  } catch (e) {
    document.getElementById("weeklyChart").closest(".chart-container").innerHTML =
      `<p style="text-align:center;color:var(--color-text-muted);padding:40px;">데이터를 불러올 수 없습니다: ${e.message}</p>`;
  }
}
