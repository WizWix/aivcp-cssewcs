/**
 * 월간 통계 페이지.
 * 이번 달의 일별 위반 건수와 준수율을 차트로 표시한다.
 */

import { fetchMonthlyStats } from "../api.js";
import { refreshChart } from "../components/chart-helpers.js";

/** @type {Chart|null} */
let _chart = null;

/** @type {{year: number, month: number}} */
let _current = _getThisMonth();

/**
 * 이번 달의 연/월을 반환한다.
 * @returns {{year: number, month: number}}
 */
function _getThisMonth() {
  const today = new Date();
  return { year: today.getFullYear(), month: today.getMonth() + 1 };
}

/**
 * 월간 통계 페이지를 초기화한다.
 * @param {HTMLElement} container
 */
export async function init(container) {
  _current = _getThisMonth();

  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-header__title">월간 현황</h1>
      <p class="page-header__sub">월간 보호구 착용 준수율과 위반 현황입니다.</p>
    </div>

    <div class="card">
      <!-- 월 선택 -->
      <div class="filter-bar" style="margin-bottom:20px;">
        <button class="btn btn--outline" id="prevMonth">◀ 이전 달</button>
        <span id="monthLabel" style="font-weight:600;font-size:13px;"></span>
        <button class="btn btn--outline" id="nextMonth">다음 달 ▶</button>
      </div>

      <!-- 요약 통계 -->
      <div id="monthlySummary" class="stat-grid" style="margin-bottom:20px;"></div>

      <!-- 차트 -->
      <div class="chart-section">
        <div class="chart-section__title">일별 위반 건수 / 준수율</div>
        <div class="chart-container">
          <canvas id="monthlyChart"></canvas>
        </div>
      </div>
    </div>
  `;

  document.getElementById("prevMonth").addEventListener("click", async () => {
    _current.month--;
    if (_current.month < 1) { _current.month = 12; _current.year--; }
    await _loadMonthlyData();
  });

  document.getElementById("nextMonth").addEventListener("click", async () => {
    _current.month++;
    if (_current.month > 12) { _current.month = 1; _current.year++; }
    await _loadMonthlyData();
  });

  await _loadMonthlyData();
}

/**
 * 월간 데이터를 API에서 조회하여 차트와 요약을 갱신한다.
 */
async function _loadMonthlyData() {
  document.getElementById("monthLabel").textContent =
    `${_current.year}년 ${_current.month}월`;

  try {
    const data = await fetchMonthlyStats(_current.year, _current.month);

    // 차트 데이터 준비 (날짜 → 일(day) 숫자만 레이블로 사용)
    const labels = data.days.map((d) => `${parseInt(d.date.slice(-2))}일`);
    const violations = data.days.map((d) => d.violations_count);
    const compliance = data.days.map((d) => +(d.compliance_rate * 100).toFixed(1));

    // 차트 갱신
    const canvas = document.getElementById("monthlyChart");
    _chart = refreshChart(_chart, canvas, labels, violations, compliance);

    // 요약 통계
    const totalViolations = data.total_violations;
    const daysWithData = data.days.filter((d) => d.total_detections > 0);
    const avgCompliance = daysWithData.length > 0
      ? daysWithData.reduce((s, d) => s + d.compliance_rate, 0) / daysWithData.length
      : 1.0;

    document.getElementById("monthlySummary").innerHTML = `
      <div class="stat-card">
        <div class="stat-card__label">월간 총 위반</div>
        <div class="stat-card__value stat-card__value--danger">${totalViolations}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card__label">월 평균 준수율</div>
        <div class="stat-card__value ${avgCompliance >= 0.9 ? "stat-card__value--success" : "stat-card__value--danger"}">
          ${(avgCompliance * 100).toFixed(1)}%
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-card__label">감지 활성 일수</div>
        <div class="stat-card__value">${daysWithData.length}일</div>
      </div>
    `;
  } catch (e) {
    const chartWrap = document.getElementById("monthlyChart")?.closest(".chart-container");
    if (chartWrap) {
      chartWrap.innerHTML =
        `<p style="text-align:center;color:var(--color-text-muted);padding:40px;">데이터를 불러올 수 없습니다: ${e.message}</p>`;
    }
  }
}
