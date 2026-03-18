/**
 * 실시간 모니터링 페이지.
 * MJPEG 영상 스트림과 오늘의 통계를 표시한다.
 */

import { fetchDailyStats } from "../api.js";

/** @type {string} */
let _bboxMode = "false";

/** @type {Function|null} 위반 이벤트 리스너 (페이지 이탈 시 제거용) */
let _violationListener = null;

/** @type {Function|null} 준수 이벤트 리스너 (페이지 이탈 시 제거용) */
let _compliantListener = null;

/** @type {number|null} 통계 자동 갱신 타이머 ID */
let _statsIntervalId = null;

/**
 * 모니터링 페이지 HTML을 렌더링하고 이벤트를 등록한다.
 * app.js의 라우터에서 페이지 전환 시 호출한다.
 *
 * @param {HTMLElement} container - 콘텐츠를 삽입할 부모 요소
 */
export async function init(container) {
  // 이전 타이머/리스너 정리
  if (_statsIntervalId !== null) {
    clearInterval(_statsIntervalId);
    _statsIntervalId = null;
  }
  if (_violationListener) {
    window.removeEventListener("ppe:violation", _violationListener);
  }
  if (_compliantListener) {
    window.removeEventListener("ppe:compliant", _compliantListener);
  }

  // 위반 SSE 이벤트 시 즉시 갱신 + 배지 업데이트
  _violationListener = () => {
    _loadTodayStats();
    _updateLastDetectionBadge("violation");
  };
  window.addEventListener("ppe:violation", _violationListener);

  // 준수 SSE 이벤트 시 즉시 갱신 + 배지 업데이트
  _compliantListener = () => {
    _loadTodayStats();
    _updateLastDetectionBadge("compliant");
  };
  window.addEventListener("ppe:compliant", _compliantListener);

  // SSE 이벤트 누락 대비 폴백 폴링 (30초)
  _statsIntervalId = setInterval(() => _loadTodayStats(), 30_000);

  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-header__title">실시간 모니터링</h1>
      <p class="page-header__sub">카메라 영상과 오늘의 현황을 확인합니다.</p>
    </div>

    <div class="monitor">
      <!-- 영상 피드 -->
      <div class="feed">
        <div class="feed__header">
          <span class="feed__title">카메라 피드</span>
          <div class="feed__controls">
            <label class="feed__bbox-toggle">
              <input type="checkbox" id="bboxToggle"> 바운딩박스 표시
            </label>
          </div>
        </div>
        <div class="feed__video-wrap">
          <img id="liveStream" src="/api/stream?bbox=false" alt="카메라 피드" />
          <div class="feed__status-dot" id="streamDot"></div>
        </div>
      </div>

      <!-- 오늘 현황 패널 -->
      <div class="today-panel">
        <div class="card">
          <div class="card__title">오늘의 현황</div>
          <div id="todayStats">
            <div class="spinner"></div>
          </div>
          <div id="lastDetectionBadge" style="display:none;margin-top:10px;padding:7px 10px;border-radius:var(--radius);font-size:12px;align-items:center;gap:6px;"></div>
        </div>

        <div class="card">
          <div class="card__title">영상 소스 변경</div>
          <div style="display:flex;flex-direction:column;gap:8px;">
            <button class="btn btn--secondary" id="webcamApplyBtn" style="width:100%;">
              웹캠 연결
            </button>
            <input
              id="rtspInput"
              class="filter-bar__input"
              style="width:100%;"
              placeholder="rtsp://..."
            />
            <button class="btn btn--primary" id="rtspApplyBtn" style="width:100%;">
              RTSP 적용
            </button>
          </div>
        </div>
      </div>
    </div>
  `;

  // 바운딩박스 토글 처리
  const bboxToggle = document.getElementById("bboxToggle");
  const liveStream = document.getElementById("liveStream");

  bboxToggle.checked = _bboxMode === "true";
  bboxToggle.addEventListener("change", () => {
    _bboxMode = bboxToggle.checked ? "true" : "false";
    // src 변경만으로 MJPEG 스트림 전환
    liveStream.src = `/api/stream?bbox=${_bboxMode}&_t=${Date.now()}`;
  });

  // 스트림 에러 시 상태 점 색상 변경
  liveStream.addEventListener("error", () => {
    const dot = document.getElementById("streamDot");
    if (dot) dot.style.backgroundColor = "var(--color-danger)";
  });

  // 웹캠 소스 변경
  document.getElementById("webcamApplyBtn").addEventListener("click", async () => {
    try {
      const { setWebcamSource } = await import("../api.js");
      await setWebcamSource(0);
      liveStream.src = `/api/stream?bbox=${_bboxMode}&_t=${Date.now()}`;
    } catch (e) {
      alert(`웹캠 연결 실패: ${e.message}`);
    }
  });

  // RTSP 소스 변경
  document.getElementById("rtspApplyBtn").addEventListener("click", async () => {
    const url = document.getElementById("rtspInput").value.trim();
    if (!url) return;
    try {
      const { setRtspSource } = await import("../api.js");
      await setRtspSource(url);
      liveStream.src = `/api/stream?bbox=${_bboxMode}&_t=${Date.now()}`;
    } catch (e) {
      alert(`RTSP 변경 실패: ${e.message}`);
    }
  });

  // 오늘 통계 로드
  await _loadTodayStats();
}

/**
 * 마지막 감지 상태 배지를 갱신한다.
 * @param {"violation"|"compliant"} type
 */
function _updateLastDetectionBadge(type) {
  const badge = document.getElementById("lastDetectionBadge");
  if (!badge) return;

  const now = new Date().toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  if (type === "compliant") {
    badge.style.background = "rgba(22,163,74,0.08)";
    badge.style.color = "var(--color-success)";
    badge.style.border = "1px solid var(--color-success)";
    badge.innerHTML = `<span style="font-size:14px;font-weight:700;">✓</span> 보호구 착용 확인 <span style="margin-left:auto;opacity:0.7;">${now}</span>`;
  } else {
    badge.style.background = "rgba(220,38,38,0.08)";
    badge.style.color = "var(--color-danger)";
    badge.style.border = "1px solid var(--color-danger)";
    badge.innerHTML = `<span style="font-size:14px;font-weight:700;">✗</span> 보호구 미착용 감지 <span style="margin-left:auto;opacity:0.7;">${now}</span>`;
  }

  badge.style.display = "flex";
}

/**
 * 오늘의 통계를 API에서 조회하여 카드를 렌더링한다.
 */
async function _loadTodayStats() {
  const statsEl = document.getElementById("todayStats");
  if (!statsEl) return;

  try {
    const data = await fetchDailyStats();
    const rate = (data.compliance_rate * 100).toFixed(1);

    statsEl.innerHTML = `
      <div class="stat-grid" style="grid-template-columns:1fr 1fr;gap:12px;">
        <div class="stat-card">
          <div class="stat-card__label">총 감지</div>
          <div class="stat-card__value">${data.total_detections}</div>
        </div>
        <div class="stat-card">
          <div class="stat-card__label">위반 건수</div>
          <div class="stat-card__value stat-card__value--danger">${data.violations_count}</div>
        </div>
        <div class="stat-card">
          <div class="stat-card__label">안전모 미착용</div>
          <div class="stat-card__value stat-card__value--danger">${data.no_helmet_count}</div>
        </div>
        <div class="stat-card">
          <div class="stat-card__label">조끼 미착용</div>
          <div class="stat-card__value stat-card__value--danger">${data.no_jacket_count}</div>
        </div>
      </div>
      <div style="margin-top:12px;padding:10px;background:var(--color-bg);border-radius:var(--radius);text-align:center;">
        <div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px;">준수율</div>
        <div style="font-size:24px;font-weight:700;color:${parseFloat(rate) >= 90 ? "var(--color-success)" : "var(--color-danger)"}">
          ${rate}%
        </div>
      </div>
    `;
  } catch (e) {
    statsEl.innerHTML = `<p style="color:var(--color-text-muted);font-size:13px;">통계를 불러올 수 없습니다.</p>`;
  }
}
