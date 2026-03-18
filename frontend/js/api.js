/**
 * 중앙화된 API 호출 모듈.
 * 모든 fetch 요청을 이 모듈을 통해 수행하여 에러 처리를 일관되게 유지한다.
 */

const BASE_URL = "/api";

/**
 * API 요청을 수행하고 JSON 응답을 반환한다.
 * @param {string} path - API 경로 (/api 이후)
 * @param {RequestInit} [options] - fetch 옵션
 * @returns {Promise<any>}
 */
async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`API 오류 ${response.status}: ${errorBody}`);
  }

  // 204 No Content 등 본문이 없는 응답 처리
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return null;
}

/**
 * 위반 기록 목록 조회
 * @param {number} page
 * @param {number} limit
 * @param {string|null} date - "YYYY-MM-DD" 형식
 */
export async function fetchViolations(page = 1, limit = 20, date = null) {
  const params = new URLSearchParams({ page, limit });
  if (date) params.set("date", date);
  return request(`/violations?${params}`);
}

/**
 * 단일 위반 기록 조회
 * @param {number} id
 */
export async function fetchViolation(id) {
  return request(`/violations/${id}`);
}

/**
 * 일별 통계 조회
 * @param {string|null} date - "YYYY-MM-DD" (기본: 오늘)
 */
export async function fetchDailyStats(date = null) {
  const params = date ? `?date=${date}` : "";
  return request(`/stats/daily${params}`);
}

/**
 * 주간 통계 조회
 * @param {string|null} weekStart - "YYYY-MM-DD" (기본: 이번 주 월요일)
 */
export async function fetchWeeklyStats(weekStart = null) {
  const params = weekStart ? `?week_start=${weekStart}` : "";
  return request(`/stats/weekly${params}`);
}

/**
 * 월간 통계 조회
 * @param {number|null} year
 * @param {number|null} month
 */
export async function fetchMonthlyStats(year = null, month = null) {
  const params = new URLSearchParams();
  if (year) params.set("year", year);
  if (month) params.set("month", month);
  const qs = params.toString();
  return request(`/stats/monthly${qs ? "?" + qs : ""}`);
}

/**
 * RTSP 소스 변경
 * @param {string} url
 */
export async function setRtspSource(url) {
  return request("/source/rtsp", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

/**
 * 웹캠 소스 변경
 * @param {number} deviceId - 웹캠 디바이스 인덱스 (기본값: 0)
 */
export async function setWebcamSource(deviceId = 0) {
  return request("/source/webcam", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId }),
  });
}

/**
 * 영상 소스 상태 조회
 */
export async function fetchSourceStatus() {
  return request("/source/status");
}
