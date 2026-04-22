const state = {
  result: null,
  spendingPeriod: "annual",
  itemPeriodType: "annual",
  itemPeriodValue: "",
};

const form = document.getElementById("upload-form");
const filesInput = document.getElementById("files");
const fileList = document.getElementById("file-list");
const emptyState = document.getElementById("empty-state");
const dashboard = document.getElementById("dashboard");
const summaryGrid = document.getElementById("summary-grid");
const spendingChart = document.getElementById("spending-chart");
const itemChart = document.getElementById("item-chart");
const itemPeriodSelect = document.getElementById("item-period-select");
const itemTableBody = document.querySelector("#item-table tbody");
const weekdayChart = document.getElementById("weekday-chart");
const storeChart = document.getElementById("store-chart");
const insights = document.getElementById("insights");
const priceTrendTableBody = document.querySelector("#price-trend-table tbody");
const timelineTableBody = document.querySelector("#timeline-table tbody");
const warningsPanel = document.getElementById("warnings-panel");
const warningsList = document.getElementById("warnings-list");
const analyseButton = document.getElementById("analyse-button");
const appTabs = document.querySelectorAll(".app-tab");

appTabs.forEach((button) => {
  button.addEventListener("click", () => {
    const panelId = button.dataset.panel;
    document.querySelectorAll(".app-tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab === button);
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("is-active", panel.id === panelId);
    });
  });
});

filesInput.addEventListener("change", () => {
  const names = [...filesInput.files].map((file) => `${file.name} (${formatBytes(file.size)})`);
  fileList.innerHTML = names.length ? names.join("<br>") : "No files selected yet.";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!filesInput.files.length) {
    fileList.textContent = "Choose at least one PDF to continue.";
    return;
  }

  analyseButton.disabled = true;
  analyseButton.textContent = "Analysing...";

  try {
    const payload = new FormData();
    [...filesInput.files].forEach((file) => payload.append("files", file, file.name));

    const response = await fetch("/api/analyze", {
      method: "POST",
      body: payload,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Analysis failed.");
    }

    state.result = data;
    state.itemPeriodType = "annual";
    state.spendingPeriod = "annual";
    syncTabGroups();
    renderDashboard();
  } catch (error) {
    fileList.textContent = error.message;
  } finally {
    analyseButton.disabled = false;
    analyseButton.textContent = "Analyse";
  }
});

document.querySelectorAll("#spending-tabs .tab").forEach((button) => {
  button.addEventListener("click", () => {
    state.spendingPeriod = button.dataset.period;
    syncTabGroups();
    renderSpending();
  });
});

document.querySelectorAll("#item-tabs .tab").forEach((button) => {
  button.addEventListener("click", () => {
    state.itemPeriodType = button.dataset.period;
    syncTabGroups();
    populateItemPeriodSelect();
    renderItems();
  });
});

itemPeriodSelect.addEventListener("change", () => {
  state.itemPeriodValue = itemPeriodSelect.value;
  renderItems();
});

function syncTabGroups() {
  document.querySelectorAll("#spending-tabs .tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.period === state.spendingPeriod);
  });
  document.querySelectorAll("#item-tabs .tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.period === state.itemPeriodType);
  });
}

function renderDashboard() {
  emptyState.classList.add("hidden");
  dashboard.classList.remove("hidden");
  renderSummary();
  renderSpending();
  populateItemPeriodSelect();
  renderItems();
  renderExtras();
  renderWarnings();
}

function renderSummary() {
  const summary = state.result.summary;
  const cards = [
    {
      label: "Total spend",
      value: currency(summary.total_spend),
      note: `${summary.period_start || "-"} to ${summary.period_end || "-"}`,
    },
    {
      label: "Receipts analysed",
      value: number(summary.receipt_count),
      note: "Migros baskets detected",
    },
    {
      label: "Item rows",
      value: number(summary.item_line_count),
      note: "Individual line items parsed",
    },
    {
      label: "Average basket",
      value: currency(summary.average_basket),
      note: "Average spend per receipt",
    },
    {
      label: "Savings found",
      value: currency(summary.total_savings),
      note: "Discounts extracted from receipts",
    },
  ];

  summaryGrid.innerHTML = cards
    .map(
      (card) => `
        <article class="stat-card">
          <div class="stat-label">${escapeHtml(card.label)}</div>
          <div class="stat-value">${escapeHtml(card.value)}</div>
          <div class="stat-note">${escapeHtml(card.note)}</div>
        </article>
      `
    )
    .join("");
}

function renderSpending() {
  const rows = state.result.spending[state.spendingPeriod];
  spendingChart.innerHTML = renderBarChart({
    title: `${capitalize(state.spendingPeriod)} spending`,
    rows,
    labelKey: "period",
    valueKey: "amount",
    color: "#0a7a4f",
    formatter: currency,
  });
}

function populateItemPeriodSelect() {
  const rows = state.result.items[state.itemPeriodType];
  const periods = [...new Set(rows.map((row) => row.period))];
  const nextValue = periods.includes(state.itemPeriodValue)
    ? state.itemPeriodValue
    : periods[periods.length - 1] || "";
  state.itemPeriodValue = nextValue;
  itemPeriodSelect.innerHTML = periods
    .map((period) => `<option value="${escapeAttribute(period)}">${escapeHtml(period)}</option>`)
    .join("");
  itemPeriodSelect.value = state.itemPeriodValue;
}

function renderItems() {
  const rows = state.result.items[state.itemPeriodType]
    .filter((row) => row.period === state.itemPeriodValue)
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 15);

  itemChart.innerHTML = renderGroupedMetricCard(rows);
  itemTableBody.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.item)}</td>
          <td>${escapeHtml(currency(row.amount))}</td>
          <td>${escapeHtml(number(row.quantity, 3))}</td>
          <td>${escapeHtml(currency(row.avg_price))}</td>
          <td>${escapeHtml(number(row.purchase_count))}</td>
          <td>${escapeHtml(currency(row.savings))}</td>
        </tr>
      `
    )
    .join("");

  if (!rows.length) {
    itemTableBody.innerHTML = `
      <tr>
        <td colspan="6">No item data available for this period.</td>
      </tr>
    `;
  }
}

function renderExtras() {
  weekdayChart.innerHTML = renderBarChart({
    title: "Spending by weekday",
    rows: state.result.extra.weekday_spend,
    labelKey: "weekday",
    valueKey: "amount",
    color: "#c96f38",
    formatter: currency,
  });

  storeChart.innerHTML = renderBarChart({
    title: "Spend by store",
    rows: state.result.extra.stores,
    labelKey: "store",
    valueKey: "amount",
    color: "#355c7d",
    formatter: currency,
  });

  insights.innerHTML = state.result.extra.insights
    .map(
      (item) => `
        <article class="insight-card">
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.detail)}</p>
        </article>
      `
    )
    .join("");

  priceTrendTableBody.innerHTML = state.result.extra.price_trends
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.item)}</td>
          <td>${escapeHtml(currency(row.min_price))}</td>
          <td>${escapeHtml(currency(row.max_price))}</td>
          <td>${escapeHtml(currency(row.latest_price))}</td>
          <td>${escapeHtml(currency(row.volatility))}</td>
          <td>${escapeHtml(number(row.observations))}</td>
        </tr>
      `
    )
    .join("");

  const topTimeline = [...state.result.extra.timeline]
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 25);

  timelineTableBody.innerHTML = topTimeline
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.date)}</td>
          <td>${escapeHtml(row.time)}</td>
          <td>${escapeHtml(row.store)}</td>
          <td>${escapeHtml(currency(row.amount))}</td>
          <td>${escapeHtml(number(row.items))}</td>
          <td>${escapeHtml(currency(row.savings))}</td>
          <td>${escapeHtml(row.source_file)}</td>
        </tr>
      `
    )
    .join("");
}

function renderWarnings() {
  const warnings = state.result.warnings || [];
  warningsPanel.classList.toggle("hidden", warnings.length === 0);
  warningsList.innerHTML = warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("");
}

function renderBarChart({ title, rows, labelKey, valueKey, color, formatter }) {
  const values = rows.map((row) => row[valueKey]);
  const max = Math.max(...values, 1);
  const barHeight = 24;
  const gap = 18;
  const labelWidth = 160;
  const valueWidth = 100;
  const chartWidth = 840;
  const usableWidth = chartWidth - labelWidth - valueWidth - 10;
  const chartHeight = rows.length * (barHeight + gap) + 20;

  const bars = rows
    .map((row, index) => {
      const y = index * (barHeight + gap);
      const width = Math.max((row[valueKey] / max) * usableWidth, 2);
      return `
        <text class="bar-label" x="0" y="${y + 16}">${escapeHtml(row[labelKey])}</text>
        <rect x="${labelWidth}" y="${y}" rx="10" ry="10" width="${usableWidth}" height="${barHeight}" fill="rgba(0,0,0,0.05)"></rect>
        <rect x="${labelWidth}" y="${y}" rx="10" ry="10" width="${width}" height="${barHeight}" fill="${color}"></rect>
        <text class="bar-value" x="${labelWidth + Math.min(width + 10, usableWidth + 10)}" y="${y + 16}">${escapeHtml(formatter(row[valueKey]))}</text>
      `;
    })
    .join("");

  return `
    <div class="chart-title">${escapeHtml(title)}</div>
    <svg class="chart-svg" viewBox="0 0 ${chartWidth} ${chartHeight}" preserveAspectRatio="xMidYMin meet">
      ${bars}
    </svg>
  `;
}

function renderGroupedMetricCard(rows) {
  if (!rows.length) {
    return `<div class="chart-title">No item data for this period.</div>`;
  }

  const topAmount = rows[0];
  const topQuantity = [...rows].sort((a, b) => b.quantity - a.quantity)[0];
  const topSavings = [...rows].sort((a, b) => b.savings - a.savings)[0];

  return `
    <div class="chart-title">Top items for ${escapeHtml(state.itemPeriodValue)}</div>
    <div class="metric-triptych">
      ${renderMiniMetric("Highest spend", topAmount.item, currency(topAmount.amount), "#0a7a4f")}
      ${renderMiniMetric("Highest quantity", topQuantity.item, number(topQuantity.quantity, 3), "#c96f38")}
      ${renderMiniMetric("Most savings", topSavings.item, currency(topSavings.savings), "#355c7d")}
    </div>
    ${renderBarChart({
      title: "Top items by spend",
      rows,
      labelKey: "item",
      valueKey: "amount",
      color: "#0a7a4f",
      formatter: currency,
    })}
  `;
}

function renderMiniMetric(label, item, value, color) {
  return `
    <div class="mini-metric" style="border-color:${color}">
      <div class="mini-label">${escapeHtml(label)}</div>
      <div class="mini-item">${escapeHtml(item)}</div>
      <div class="mini-value">${escapeHtml(value)}</div>
    </div>
  `;
}

function currency(value) {
  return new Intl.NumberFormat("en-CH", {
    style: "currency",
    currency: "CHF",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

function number(value, digits = 0) {
  return new Intl.NumberFormat("en-CH", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? Math.min(digits, 1) : 0,
  }).format(value || 0);
}

function capitalize(value) {
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}

function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
