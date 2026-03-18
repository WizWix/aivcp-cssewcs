/**
 * 감지 기록 페이지.
 * 위반 목록을 페이지네이션과 날짜 필터로 조회한다.
 */

import { fetchViolations } from "../api.js";

/** @type {number} */
let _currentPage = 1;
/** @type {string|null} */
let _filterDate = null;
/** @type {number} */
let _totalPages = 1;

const LIMIT = 20;

/**
 * 감지 기록 페이지를 초기화한다.
 * @param {HTMLElement} container
 */
export async function init(container) {
  _currentPage = 1;
  _filterDate = null;

  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-header__title">감지 기록</h1>
      <p class="page-header__sub">보호구 미착용 감지 기록을 조회합니다.</p>
    </div>

    <div class="card">
      <!-- 날짜 필터 -->
      <div class="filter-bar">
        <span class="filter-bar__label">날짜 필터:</span>
        <input type="date" id="dateFilter" class="filter-bar__input" />
        <button class="btn btn--outline" id="clearFilter">초기화</button>
      </div>

      <!-- 테이블 -->
      <div id="logContent">
        <div class="spinner"></div>
      </div>

      <!-- 페이지네이션 -->
      <div class="pagination" id="pagination" style="display:none;"></div>
    </div>
  `;

  // 날짜 필터 이벤트
  document.getElementById("dateFilter").addEventListener("change", async (e) => {
    _filterDate = e.target.value || null;
    _currentPage = 1;
    await _loadLogs();
  });

  document.getElementById("clearFilter").addEventListener("click", async () => {
    _filterDate = null;
    _currentPage = 1;
    document.getElementById("dateFilter").value = "";
    await _loadLogs();
  });

  await _loadLogs();
}

/**
 * 현재 페이지/필터 설정으로 위반 기록을 로드하여 테이블을 렌더링한다.
 */
async function _loadLogs() {
  const logContent = document.getElementById("logContent");
  logContent.innerHTML = '<div class="spinner"></div>';

  try {
    const data = await fetchViolations(_currentPage, LIMIT, _filterDate);
    _totalPages = Math.ceil(data.total / LIMIT) || 1;
    _renderTable(data.items);
    _renderPagination(data.total);
  } catch (e) {
    logContent.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">⚠️</div>
        <div class="empty-state__text">기록을 불러올 수 없습니다: ${e.message}</div>
      </div>
    `;
  }
}

/**
 * 위반 기록 배열을 HTML 테이블로 렌더링한다.
 * @param {Array} items
 */
function _renderTable(items) {
  const logContent = document.getElementById("logContent");

  if (!items.length) {
    logContent.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">✅</div>
        <div class="empty-state__text">해당 조건의 위반 기록이 없습니다.</div>
      </div>
    `;
    return;
  }

  const rows = items.map((item) => {
    const missing = _buildMissingBadges(item);
    const time = _formatDateTime(item.occurred_at);
    const conf = item.confidence !== null
      ? `${(item.confidence * 100).toFixed(1)}%`
      : "-";

    return `
      <tr>
        <td>${item.id}</td>
        <td>${time}</td>
        <td>${missing}</td>
        <td>${conf}</td>
        <td>
          ${item.clip_path
        ? `<button class="log-table__play-btn" data-clip="${item.clip_path}">▶ 재생</button>`
        : '<span style="color:var(--color-text-muted);">없음</span>'
      }
          <div class="clip-player" id="player-${item.id}" style="display:none;"></div>
        </td>
      </tr>
    `;
  }).join("");

  logContent.innerHTML = `
    <div class="log-table-wrap">
      <table class="log-table">
        <thead>
          <tr>
            <th>#</th>
            <th>발생 시각</th>
            <th>미착용 항목</th>
            <th>신뢰도</th>
            <th>영상 클립</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  // 클립 재생 버튼 이벤트 위임
  logContent.querySelector("tbody")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".log-table__play-btn");
    if (!btn) return;

    const clipPath = btn.dataset.clip;
    const row = btn.closest("tr");
    const idMatch = row.querySelector(".clip-player")?.id.match(/\d+/);
    if (!idMatch) return;

    const playerId = `player-${idMatch[0]}`;
    const playerEl = document.getElementById(playerId);
    if (!playerEl) return;

    // 토글: 이미 열려있으면 닫기
    if (playerEl.style.display !== "none") {
      playerEl.style.display = "none";
      playerEl.innerHTML = "";
      return;
    }

    // 클립 URL: clips/ 접두사를 /clips/로 변환
    const clipUrl = `/${clipPath}`;
    playerEl.style.display = "block";
    playerEl.innerHTML = `
      <video controls autoplay style="width:100%;max-width:400px;border-radius:6px;">
        <source src="${clipUrl}" type="video/mp4" />
        브라우저가 비디오를 지원하지 않습니다.
      </video>
    `;
  });
}

/**
 * 페이지네이션 UI를 렌더링한다.
 * @param {number} total
 */
function _renderPagination(total) {
  const paginationEl = document.getElementById("pagination");
  if (total <= LIMIT) {
    paginationEl.style.display = "none";
    return;
  }

  paginationEl.style.display = "flex";
  paginationEl.innerHTML = `
    <button class="pagination__btn" id="prevBtn" ${_currentPage <= 1 ? "disabled" : ""}>이전</button>
    <span class="pagination__info">${_currentPage} / ${_totalPages}</span>
    <button class="pagination__btn" id="nextBtn" ${_currentPage >= _totalPages ? "disabled" : ""}>다음</button>
  `;

  document.getElementById("prevBtn")?.addEventListener("click", async () => {
    if (_currentPage > 1) {
      _currentPage--;
      await _loadLogs();
    }
  });

  document.getElementById("nextBtn")?.addEventListener("click", async () => {
    if (_currentPage < _totalPages) {
      _currentPage++;
      await _loadLogs();
    }
  });
}

/**
 * 미착용 항목을 배지 HTML로 변환한다.
 * @param {Object} item
 * @returns {string}
 */
function _buildMissingBadges(item) {
  const badges = [];
  if (item.missing_helmet) badges.push('<span class="badge badge--danger">안전모</span>');
  if (item.missing_jacket) badges.push('<span class="badge badge--danger">안전 조끼</span>');
  return badges.length > 0
    ? `<div style="display:flex;gap:4px;flex-wrap:wrap;">${badges.join("")}</div>`
    : '<span class="badge badge--success">정상</span>';
}

/**
 * ISO8601 문자열을 읽기 쉬운 형식으로 변환한다.
 * @param {string} isoString
 * @returns {string}
 */
function _formatDateTime(isoString) {
  try {
    return new Date(isoString).toLocaleString("ko-KR");
  } catch {
    return isoString;
  }
}
