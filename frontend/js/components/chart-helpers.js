/**
 * Chart.js 차트 생성 팩토리 함수.
 * 반복되는 Chart 설정을 추상화하여 코드 중복을 줄인다.
 */

/**
 * 막대 + 선 혼합 차트를 생성한다 (위반 건수 막대 + 준수율 선).
 * @param {HTMLCanvasElement} canvas
 * @param {string[]} labels - X축 레이블
 * @param {number[]} violationData - 위반 건수 데이터
 * @param {number[]} complianceData - 준수율 데이터 (0~100%)
 * @returns {Chart}
 */
export function createComplianceChart(canvas, labels, violationData, complianceData) {
  return new Chart(canvas, {
    data: {
      labels,
      datasets: [
        {
          type: "bar",
          label: "위반 건수",
          data: violationData,
          backgroundColor: "rgba(220, 38, 38, 0.75)",
          borderColor: "rgba(220, 38, 38, 1)",
          borderWidth: 1,
          borderRadius: 3,
          yAxisID: "y",
        },
        {
          type: "line",
          label: "준수율 (%)",
          data: complianceData,
          borderColor: "rgba(37, 99, 235, 1)",
          backgroundColor: "rgba(37, 99, 235, 0.08)",
          borderWidth: 2,
          pointRadius: 3,
          fill: true,
          tension: 0.3,
          yAxisID: "y2",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "top",
          labels: { font: { size: 12 }, usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (ctx.datasetIndex === 1) {
                return ` 준수율: ${ctx.raw.toFixed(1)}%`;
              }
              return ` 위반: ${ctx.raw}건`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 11 } },
        },
        y: {
          beginAtZero: true,
          position: "left",
          title: { display: true, text: "위반 건수", font: { size: 11 } },
          ticks: { stepSize: 1, font: { size: 11 } },
        },
        y2: {
          beginAtZero: false,
          min: 0,
          max: 100,
          position: "right",
          title: { display: true, text: "준수율 (%)", font: { size: 11 } },
          ticks: {
            font: { size: 11 },
            callback: (v) => `${v}%`,
          },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

/**
 * 기존 차트를 파괴하고 새 데이터로 다시 생성한다.
 * 페이지 재진입 시 캔버스에 이전 차트가 남아있는 문제를 방지한다.
 *
 * @param {Chart|null} existingChart
 * @param {HTMLCanvasElement} canvas
 * @param {string[]} labels
 * @param {number[]} violationData
 * @param {number[]} complianceData
 * @returns {Chart}
 */
export function refreshChart(existingChart, canvas, labels, violationData, complianceData) {
  if (existingChart) {
    existingChart.destroy();
  }
  return createComplianceChart(canvas, labels, violationData, complianceData);
}
