/**
 * SPA 라우터 및 앱 진입점.
 * nav 클릭 시 해당 페이지 모듈을 동적으로 import하여 초기화한다.
 */

import { initNotifications } from "./components/notification.js";

/** 페이지 이름 → 모듈 경로 매핑 */
const PAGE_MODULES = {
  monitoring: "./pages/monitoring.js",
  logs: "./pages/logs.js",
  weekly: "./pages/weekly.js",
  monthly: "./pages/monthly.js",
};

/** @type {string} */
let _currentPage = "";

/**
 * 지정한 페이지로 전환한다.
 * 해당 페이지 모듈을 동적으로 로드하고 init()을 호출한다.
 *
 * @param {string} pageName
 */
async function navigateTo(pageName) {
  if (_currentPage === pageName) return;
  _currentPage = pageName;

  // 네비 메뉴 활성 상태 갱신
  document.querySelectorAll(".nav__item").forEach((el) => {
    el.classList.toggle("nav__item--active", el.dataset.page === pageName);
  });

  const content = document.getElementById("content");
  if (!content) return;

  // 로딩 상태 표시
  content.innerHTML = '<div class="spinner"></div>';

  try {
    const modulePath = PAGE_MODULES[pageName];
    if (!modulePath) throw new Error(`알 수 없는 페이지: ${pageName}`);

    const module = await import(modulePath);
    await module.init(content);
  } catch (e) {
    content.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">⚠️</div>
        <div class="empty-state__text">페이지를 불러올 수 없습니다: ${e.message}</div>
      </div>
    `;
    console.error("페이지 로드 오류:", e);
  }
}

/**
 * 앱을 초기화한다.
 * DOMContentLoaded 이후 1회 실행된다.
 */
function init() {
  // 실시간 알림 컴포넌트 초기화 (모든 페이지에서 공통 실행)
  initNotifications();

  // 네비 클릭 이벤트 등록
  document.querySelectorAll(".nav__item[data-page]").forEach((el) => {
    el.addEventListener("click", () => {
      const page = el.dataset.page;
      if (page) navigateTo(page);
    });
  });

  // 기본 페이지: 실시간 모니터링
  navigateTo("monitoring");
}

// DOM 준비 완료 시 앱 시작
document.addEventListener("DOMContentLoaded", init);
