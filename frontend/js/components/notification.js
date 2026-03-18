/**
 * SSE 기반 실시간 위반 알림 컴포넌트.
 * 모든 페이지에서 공통으로 실행되며, 위반 발생 시 팝업을 표시한다.
 */

const AUTO_DISMISS_MS = 8000;  // 위반 알림 자동 닫기 지연 (밀리초)
const PASS_DISMISS_MS = 2000;  // 준수 알림 자동 닫기 지연 (밀리초)
const MAX_NOTIFICATIONS = 5;   // 동시에 표시할 최대 알림 수

/** @type {EventSource|null} */
let _eventSource = null;

/** @type {HTMLElement} */
let _container = null;

/**
 * 알림 컴포넌트를 초기화하고 SSE 연결을 시작한다.
 * app.js의 DOMContentLoaded 핸들러에서 1회 호출한다.
 */
export function initNotifications() {
  _container = document.getElementById("notificationContainer");
  if (!_container) return;

  _connectSSE();
}

/**
 * SSE 연결을 생성하고 이벤트 핸들러를 등록한다.
 * 연결이 끊기면 브라우저가 자동으로 재연결한다 (EventSource 기본 동작).
 */
function _connectSSE() {
  if (_eventSource) {
    _eventSource.close();
  }

  _eventSource = new EventSource("/api/events");

  _eventSource.addEventListener("violation", (e) => {
    try {
      const data = JSON.parse(e.data);
      _showNotification(data);
      // 모니터링 페이지 통계 갱신을 위해 커스텀 이벤트 발행
      window.dispatchEvent(new CustomEvent("ppe:violation", { detail: data }));
    } catch (err) {
      console.error("알림 파싱 오류:", err);
    }
  });

  _eventSource.addEventListener("compliant", (e) => {
    try {
      const data = JSON.parse(e.data);
      _showPassNotification(data);
      window.dispatchEvent(new CustomEvent("ppe:compliant", { detail: data }));
    } catch (err) {
      console.error("준수 알림 파싱 오류:", err);
    }
  });

  _eventSource.addEventListener("error", () => {
    // EventSource가 자동 재연결하므로 별도 처리 불필요
    console.warn("SSE 연결 오류 - 재연결 대기 중...");
  });
}

/**
 * 위반 이벤트 데이터로 알림 팝업을 생성하여 화면에 표시한다.
 * @param {Object} data - ViolationEvent 스키마와 동일한 구조
 */
function _showNotification(data) {
  // 최대 개수 초과 시 가장 오래된 알림 제거
  const existing = _container.querySelectorAll(".notification");
  if (existing.length >= MAX_NOTIFICATIONS) {
    _dismiss(existing[0], true);
  }

  const missingItems = _buildMissingText(data);
  const timeText = _formatDateTime(data.occurred_at);

  const el = document.createElement("div");
  el.className = "notification";
  el.setAttribute("data-id", data.violation_id);
  el.innerHTML = `
    <span class="notification__icon">⚠️</span>
    <div class="notification__body">
      <div class="notification__title">보호구 미착용 감지</div>
      <div class="notification__desc">${missingItems}</div>
      <div class="notification__time">${timeText}</div>
    </div>
    <button class="notification__close" aria-label="닫기">✕</button>
    <div class="notification__progress" style="animation-duration: ${AUTO_DISMISS_MS}ms;"></div>
  `;

  // 클릭 시 상세 페이지를 새 탭에서 열기
  el.addEventListener("click", (e) => {
    if (e.target.closest(".notification__close")) return;
    window.open(`/detail.html?id=${data.violation_id}`, "_blank");
  });

  // 닫기 버튼
  el.querySelector(".notification__close").addEventListener("click", () => {
    _dismiss(el);
  });

  _container.appendChild(el);

  // 자동 닫기 타이머
  const timerId = setTimeout(() => _dismiss(el), AUTO_DISMISS_MS);
  el._timerId = timerId;
}

/**
 * 준수 감지 시 짧은 녹색 토스트 알림을 표시한다.
 * @param {Object} data - { occurred_at }
 */
function _showPassNotification(data) {
  // 최대 개수 초과 시 가장 오래된 알림 제거
  const existing = _container.querySelectorAll(".notification");
  if (existing.length >= MAX_NOTIFICATIONS) {
    _dismiss(existing[0], true);
  }

  const timeText = _formatDateTime(data.occurred_at);

  const el = document.createElement("div");
  el.className = "notification notification--pass";
  el.innerHTML = `
    <span class="notification__icon">✓</span>
    <div class="notification__body">
      <div class="notification__title">보호구 착용 확인</div>
      <div class="notification__desc">안전모·조끼 모두 착용</div>
      <div class="notification__time">${timeText}</div>
    </div>
    <button class="notification__close" aria-label="닫기">✕</button>
    <div class="notification__progress" style="animation-duration: ${PASS_DISMISS_MS}ms;"></div>
  `;

  el.querySelector(".notification__close").addEventListener("click", () => {
    _dismiss(el);
  });

  _container.appendChild(el);

  const timerId = setTimeout(() => _dismiss(el), PASS_DISMISS_MS);
  el._timerId = timerId;
}

/**
 * 알림 팝업을 닫는다.
 * @param {HTMLElement} el
 * @param {boolean} immediate - true면 애니메이션 없이 즉시 제거
 */
function _dismiss(el, immediate = false) {
  if (!el.isConnected) return;

  if (el._timerId) clearTimeout(el._timerId);

  if (immediate) {
    el.remove();
    return;
  }

  el.classList.add("notification--exiting");
  setTimeout(() => el.remove(), 300);
}

/**
 * 미착용 항목을 한국어 문자열로 변환한다.
 * @param {Object} data
 * @returns {string}
 */
function _buildMissingText(data) {
  const missing = [];
  if (data.missing_helmet) missing.push("안전모");
  if (data.missing_jacket) missing.push("안전 조끼");
  return missing.length > 0
    ? `${missing.join(", ")} 미착용`
    : "보호구 미착용";
}

/**
 * ISO8601 문자열을 읽기 쉬운 형식으로 변환한다.
 * @param {string} isoString
 * @returns {string}
 */
function _formatDateTime(isoString) {
  try {
    const d = new Date(isoString);
    return d.toLocaleString("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
}
