import { h, render } from "https://esm.sh/preact@10.24.3";
import { useEffect, useMemo, useRef, useState } from "https://esm.sh/preact@10.24.3/hooks";
import { marked } from "https://esm.sh/marked@15.0.7";
import createDOMPurify from "https://esm.sh/dompurify@3.1.6";
import {
  Archive,
  Bot,
  Check,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Trash2,
  UserRound,
} from "https://esm.sh/lucide-preact@0.468.0";
import {
  createSession,
  deleteSession,
  getSession,
  listSessions,
  sendChatMessage,
  updateSession,
} from "./api.js";
import { formatDate, previewTitle } from "./utils.js";

const e = h;
const DOMPurify = createDOMPurify(window);

marked.setOptions({
  breaks: true,
  gfm: true,
});

function renderMarkdown(value) {
  const html = marked.parse(value || "", { async: false });
  return DOMPurify.sanitize(html);
}

const CHART_COLORS = ["#10b981", "#38bdf8", "#f59e0b", "#ef4444", "#14b8a6", "#f97316"];

function parseMessageData(value) {
  if (!value) return null;
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (typeof value === "object") return value;
  return null;
}

function extractVisualizationPayload(parsed) {
  if (!parsed || typeof parsed !== "object") return null;
  if (Array.isArray(parsed.visualizations)) return parsed;
  if (parsed.data && typeof parsed.data === "object" && Array.isArray(parsed.data.visualizations)) {
    return parsed.data;
  }
  return null;
}

function extractTransferReceipt(parsed) {
  if (!parsed || typeof parsed !== "object") return null;

  const direct = parsed.receipt;
  const nested = parsed.data && typeof parsed.data === "object" ? parsed.data.receipt : null;
  const receipt = (nested && typeof nested === "object" ? nested : direct) || null;

  if (!receipt || receipt.type !== "TRANSFER_SUCCESS") return null;

  return {
    transaction_ref: String(receipt.transaction_ref || "N/A"),
    transaction_time: receipt.transaction_time ? String(receipt.transaction_time) : "",
    amount: toNumber(receipt.amount),
    recipient_name: String(receipt.recipient_name || "?"),
    recipient_account_no: String(receipt.recipient_account_no || receipt.recipient_account_no_masked || "?"),
    recipient_bank: String(receipt.recipient_bank || "?"),
    service_fee: toNumber(receipt.service_fee),
    total_debit: toNumber(receipt.total_debit),
    balance_before: toNumber(receipt.balance_before),
    balance_after: toNumber(receipt.balance_after),
  };
}

function extractCategoryConfirmation(parsed) {
  if (!parsed || typeof parsed !== "object") return null;

  const flowStatus = String(parsed.flow_status || "");
  if (flowStatus && flowStatus !== "WAITING_CATEGORY_CONFIRMATION") return null;

  const direct = parsed.category_confirmation;
  const nested = parsed.data && typeof parsed.data === "object" ? parsed.data.category_confirmation : null;
  const category = (nested && typeof nested === "object" ? nested : direct) || null;

  if (!category) return null;

  const alternativesRaw = Array.isArray(category.alternatives) ? category.alternatives : [];
  const alternatives = alternativesRaw
    .map((item, index) => {
      if (!item || typeof item !== "object") return null;
      return {
        index: Number.isFinite(Number(item.index)) ? Number(item.index) : index + 1,
        name: String(item.name || `Lựa chọn ${index + 1}`),
        command: String(item.command || index + 1),
      };
    })
    .filter(Boolean);

  const commands = category.commands && typeof category.commands === "object" ? category.commands : {};

  return {
    predicted_name: String(category.predicted_name || "Khác"),
    alternatives,
    confirm_command: String(commands.confirm || "đúng"),
    skip_command: String(commands.skip || "bỏ qua"),
  };
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function compactAxisLabel(value, maxLength = 12) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "N/A";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(1, maxLength - 1))}…`;
}

function wrapAxisLabel(value, maxCharsPerLine = 10, maxLines = 4) {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  if (!normalized) return ["N/A"];

  const safeMaxChars = Math.max(4, maxCharsPerLine);
  const safeMaxLines = Math.max(1, maxLines);

  // Split long words first so wrapping still works without spaces.
  const words = normalized
    .split(" ")
    .flatMap((word) => {
      if (word.length <= safeMaxChars) return [word];
      const chunks = [];
      for (let i = 0; i < word.length; i += safeMaxChars) {
        chunks.push(word.slice(i, i + safeMaxChars));
      }
      return chunks;
    })
    .filter(Boolean);

  const lines = [];
  let current = "";

  for (let idx = 0; idx < words.length; idx += 1) {
    const word = words[idx];
    const candidate = current ? `${current} ${word}` : word;
    if (!current || candidate.length <= safeMaxChars) {
      current = candidate;
      continue;
    }

    lines.push(current);
    current = word;

    if (lines.length >= safeMaxLines - 1) {
      const rest = [current, ...words.slice(idx + 1)].join(" ").trim();
      if (rest) lines.push(rest);
      return lines.slice(0, safeMaxLines);
    }
  }

  if (current) lines.push(current);
  return lines.slice(0, safeMaxLines);
}

function formatMetric(value, currency = "VND", unit = null) {
  const n = toNumber(value);
  if (unit === "percent") return `${n.toFixed(2)}%`;
  if (unit === "count") return `${Math.round(n)}`;
  if (currency === "VND") {
    return `${new Intl.NumberFormat("vi-VN").format(Math.round(n))} đ`;
  }
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 }).format(n);
}

function formatVnd(value) {
  const amount = toNumber(value);
  return `${new Intl.NumberFormat("vi-VN").format(Math.round(amount))} VND`;
}

function formatReceiptTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("vi-VN", {
    hour12: false,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function estimateYAxisPadding(tickValues, currency, unit, minPadding = 56, maxPadding = 132) {
  const longest = tickValues.reduce((maxLength, value) => {
    const size = formatMetric(value, currency, unit).length;
    return Math.max(maxLength, size);
  }, 0);

  const estimated = Math.ceil(longest * 6.1 + 18);
  return Math.max(minPadding, Math.min(maxPadding, estimated));
}

function normalizeChart(chart) {
  if (!chart || typeof chart !== "object") return null;
  const labels = Array.isArray(chart.labels) ? chart.labels.map((item) => String(item)) : [];
  const series = Array.isArray(chart.series)
    ? chart.series
        .map((item) => ({
          name: String(item?.name || "Series"),
          values: Array.isArray(item?.values) ? item.values.map(toNumber) : [],
        }))
        .filter((item) => item.values.length > 0)
    : [];

  if (!labels.length || !series.length) return null;
  return {
    id: String(chart.id || ""),
    type: String(chart.type || "bar"),
    title: String(chart.title || "Biểu đồ"),
    subtitle: chart.subtitle ? String(chart.subtitle) : "",
    unit: chart.unit ? String(chart.unit) : null,
    currency: chart.currency ? String(chart.currency) : "VND",
    labels,
    series,
  };
}

function ChartLegend({ series }) {
  return e(
    "ul",
    { class: "finance-chart-legend" },
    series.map((item, index) =>
      e(
        "li",
        { key: `${item.name}-${index}` },
        e("span", {
          class: "finance-chart-legend__swatch",
          style: `background:${CHART_COLORS[index % CHART_COLORS.length]}`,
        }),
        e("span", null, item.name),
      ),
    ),
  );
}

function LineChart({ labels, series, currency, unit }) {
  const width = 640;
  const height = 236;
  const maxValue = Math.max(1, ...series.flatMap((item) => item.values.map(toNumber)));
  const yTicks = 4;
  const tickValues = Array.from({ length: yTicks + 1 }, (_, index) => (maxValue / yTicks) * (yTicks - index));
  const padding = {
    top: 16,
    right: 16,
    bottom: 34,
    left: estimateYAxisPadding(tickValues, currency, unit, 64, 136),
  };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  function x(index) {
    if (labels.length <= 1) return padding.left + chartWidth / 2;
    return padding.left + (index * chartWidth) / (labels.length - 1);
  }

  function y(value) {
    return padding.top + chartHeight - (toNumber(value) / maxValue) * chartHeight;
  }

  const paths = series.map((item, seriesIndex) => {
    const d = item.values
      .map((value, valueIndex) => `${valueIndex === 0 ? "M" : "L"} ${x(valueIndex)} ${y(value)}`)
      .join(" ");
    return e("path", {
      key: `${item.name}-line`,
      d,
      class: "finance-chart-line",
      style: `stroke:${CHART_COLORS[seriesIndex % CHART_COLORS.length]}`,
    });
  });

  return e(
    "svg",
    { class: "finance-chart-svg", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "line chart" },
    e(
      "g",
      { class: "finance-chart-grid" },
      tickValues.map((value, index) => {
        const yPos = padding.top + (chartHeight * index) / yTicks;
        return e(
          "g",
          { key: `y-${index}` },
          e("line", {
            x1: padding.left,
            y1: yPos,
            x2: width - padding.right,
            y2: yPos,
          }),
          e(
            "text",
            {
              class: "finance-chart-axis-label",
              x: padding.left - 8,
              y: yPos + 4,
              "text-anchor": "end",
            },
            formatMetric(value, currency, unit),
          ),
        );
      }),
    ),
    paths,
    series.map((item, seriesIndex) =>
      item.values.map((value, valueIndex) =>
        e("circle", {
          key: `${item.name}-point-${valueIndex}`,
          class: "finance-chart-point",
          cx: x(valueIndex),
          cy: y(value),
          r: 3.5,
          style: `fill:${CHART_COLORS[seriesIndex % CHART_COLORS.length]}`,
        }),
      ),
    ),
    e(
      "g",
      { class: "finance-chart-axis" },
      labels.map((label, index) => {
        const isFirst = index === 0;
        const isLast = index === labels.length - 1;
        const anchor = isFirst ? "start" : isLast ? "end" : "middle";
        const xPos = x(index) + (isFirst ? 2 : isLast ? -2 : 0);
        return e(
          "text",
          {
            key: `${label}-${index}`,
            class: "finance-chart-axis-label",
            x: xPos,
            y: height - 12,
            "text-anchor": anchor,
          },
          label,
        );
      }),
    ),
  );
}

function BarChart({ labels, series, currency, unit, grouped = false }) {
  const width = 640;
  const height = 262;
  const maxValue = Math.max(1, ...series.flatMap((item) => item.values.map(toNumber)));
  const yTicks = 4;
  const tickValues = Array.from({ length: yTicks + 1 }, (_, index) => (maxValue / yTicks) * (yTicks - index));
  const leftPadding = estimateYAxisPadding(tickValues, currency, unit, 64, 136);
  const chartWidth = width - leftPadding - 16;
  const groupCount = labels.length;
  const groupWidth = groupCount ? chartWidth / groupCount : chartWidth;
  const labelMaxLength = Math.max(5, Math.min(13, Math.floor(groupWidth / 6.1)));
  const wrappedLabels = labels.map((label) => wrapAxisLabel(label, labelMaxLength, 4));
  const maxLabelLines = wrappedLabels.reduce((maxLines, lines) => Math.max(maxLines, lines.length), 1);
  const labelLineHeight = 11;
  const labelBlockHeight = maxLabelLines * labelLineHeight;
  const padding = {
    top: 16,
    right: 16,
    bottom: Math.max(44, labelBlockHeight + 24),
    left: leftPadding,
  };
  const chartHeight = height - padding.top - padding.bottom;

  function y(value) {
    return padding.top + chartHeight - (toNumber(value) / maxValue) * chartHeight;
  }

  const seriesCount = grouped ? series.length : 1;
  const barArea = groupWidth * 0.74;
  const barWidth = Math.max(8, Math.min(34, barArea / Math.max(seriesCount, 1)));
  const labelY = padding.top + chartHeight + 14;

  const bars = labels.flatMap((_, labelIndex) => {
    const items = grouped ? series : [series[0]];
    return items.map((item, seriesIndex) => {
      const value = toNumber(item.values[labelIndex]);
      const baseX = padding.left + labelIndex * groupWidth + (groupWidth - barArea) / 2;
      const x = baseX + seriesIndex * barWidth;
      const yPos = y(value);
      return e("rect", {
        key: `${item.name}-${labelIndex}-${seriesIndex}`,
        class: "finance-chart-bar",
        x,
        y: yPos,
        width: Math.max(2, barWidth - 1.5),
        height: Math.max(1, padding.top + chartHeight - yPos),
        rx: 3,
        ry: 3,
        style: `fill:${CHART_COLORS[seriesIndex % CHART_COLORS.length]}`,
      });
    });
  });

  return e(
    "svg",
    { class: "finance-chart-svg", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "bar chart" },
    e(
      "g",
      { class: "finance-chart-grid" },
      tickValues.map((value, index) => {
        const yPos = padding.top + (chartHeight * index) / yTicks;
        return e(
          "g",
          { key: `bar-y-${index}` },
          e("line", {
            x1: padding.left,
            y1: yPos,
            x2: width - padding.right,
            y2: yPos,
          }),
          e(
            "text",
            {
              class: "finance-chart-axis-label",
              x: padding.left - 8,
              y: yPos + 4,
                "text-anchor": "end",
            },
            formatMetric(value, currency, unit),
          ),
        );
      }),
    ),
    bars,
    e(
      "g",
      { class: "finance-chart-axis" },
      labels.map((label, index) => {
        const xPos = padding.left + index * groupWidth + groupWidth / 2;
        const lines = wrappedLabels[index] || [String(label || "")];

        return e(
          "text",
          {
            key: `${label}-${index}`,
            class: "finance-chart-axis-label finance-chart-axis-label--multiline",
            x: xPos,
            y: labelY,
            "text-anchor": "middle",
          },
          lines.map((line, lineIndex) =>
            e(
              "tspan",
              {
                key: `${label}-${index}-line-${lineIndex}`,
                x: xPos,
                dy: lineIndex === 0 ? 0 : labelLineHeight,
              },
              line,
            ),
          ),
        );
      }),
    ),
  );
}

function FinanceChart({ chart, fallbackCurrency }) {
  const currency = chart.currency || fallbackCurrency || "VND";
  if (chart.type === "line") {
    return e(LineChart, { labels: chart.labels, series: chart.series, currency, unit: chart.unit });
  }
  if (chart.type === "bar-grouped") {
    return e(BarChart, {
      labels: chart.labels,
      series: chart.series,
      currency,
      unit: chart.unit,
      grouped: true,
    });
  }
  if (chart.type === "bar") {
    return e(BarChart, {
      labels: chart.labels,
      series: chart.series,
      currency,
      unit: chart.unit,
      grouped: false,
    });
  }
  return e("p", { class: "finance-chart-empty" }, "Biểu đồ chưa được hỗ trợ.");
}

function FinanceVisualizations({ visualizations, currency = "VND" }) {
  const charts = (visualizations || []).map(normalizeChart).filter(Boolean);
  if (!charts.length) return null;

  return e(
    "section",
    { class: "message-visualizations" },
    charts.map((chart, index) =>
      e(
        "article",
        { key: chart.id || `${chart.type}-${index}`, class: "finance-chart-card" },
        e(
          "div",
          { class: "finance-chart-card__header" },
          e("h4", { class: "finance-chart-card__title" }, chart.title),
          chart.subtitle ? e("p", { class: "finance-chart-card__subtitle" }, chart.subtitle) : null,
        ),
        e(FinanceChart, { chart, fallbackCurrency: currency }),
        chart.series.length > 1 ? e(ChartLegend, { series: chart.series }) : null,
      ),
    ),
  );
}

function TransactionReceiptCard({ receipt }) {
  const rows = [
    { label: "Số tiền", value: formatVnd(receipt.amount) },
    { label: "Người nhận", value: receipt.recipient_name },
    { label: "Số tài khoản", value: receipt.recipient_account_no },
    { label: "Ngân hàng", value: receipt.recipient_bank },
    { label: "Phí dịch vụ", value: formatVnd(receipt.service_fee) },
    { label: "Tổng tiền bị trừ", value: formatVnd(receipt.total_debit) },
    { label: "Số dư trước giao dịch", value: formatVnd(receipt.balance_before) },
    { label: "Số dư sau giao dịch", value: formatVnd(receipt.balance_after) },
  ];

  const formattedTime = formatReceiptTime(receipt.transaction_time);

  return e(
    "section",
    { class: "transaction-receipt-card" },
    e(
      "div",
      { class: "transaction-receipt-card__header" },
      e("div", { class: "transaction-receipt-card__icon" }, e(Check, { size: 16 })),
      e(
        "div",
        { class: "transaction-receipt-card__headline" },
        e(
          "h4",
          null,
          "Hệ thống ghi nhận yêu cầu. Tài khoản đã thực hiện giao dịch thành công!",
        ),
        e(
          "p",
          null,
          `Mã giao dịch: ${receipt.transaction_ref}`,
          formattedTime ? ` · ${formattedTime}` : "",
        ),
      ),
    ),
    e(
      "dl",
      { class: "transaction-receipt-card__grid" },
      rows.map((item) =>
        e(
          "div",
          { key: item.label, class: "transaction-receipt-card__row" },
          e("dt", null, item.label),
          e("dd", null, item.value),
        ),
      ),
    ),
  );
}

function CategoryChoiceButtons({ categoryConfirmation, onQuickReply, disabled = false }) {
  if (!categoryConfirmation || typeof onQuickReply !== "function") return null;

  return e(
    "section",
    { class: "category-actions" },
    e(
      "p",
      { class: "category-actions__hint" },
      "Chọn loại giao dịch (nếu bạn không chọn và gửi yêu cầu mới, hệ thống sẽ lưu giá trị dự đoán mặc định).",
    ),
    e(
      "div",
      { class: "category-actions__row" },
      e(
        "button",
        {
          type: "button",
          class: "category-action-btn primary",
          onClick: () => onQuickReply(categoryConfirmation.confirm_command),
          disabled,
        },
        `Giữ: ${categoryConfirmation.predicted_name}`,
      ),
      categoryConfirmation.alternatives.map((item) =>
        e(
          "button",
          {
            key: `${item.index}-${item.name}`,
            type: "button",
            class: "category-action-btn",
            onClick: () => onQuickReply(item.command),
            disabled,
          },
          `${item.index}. ${item.name}`,
        ),
      ),
      e(
        "button",
        {
          type: "button",
          class: "category-action-btn skip",
          onClick: () => onQuickReply(categoryConfirmation.skip_command),
          disabled,
        },
        "Bỏ qua",
      ),
    ),
  );
}

function IconButton({ title, onClick, children, kind = "ghost", disabled = false }) {
  return e(
    "button",
    { class: `icon-button ${kind}`, title, "aria-label": title, onClick, disabled },
    children,
  );
}

function Spinner() {
  return e("span", { class: "spinner", "aria-hidden": "true" });
}

function SessionSkeletonRow() {
  return e(
    "div",
    { class: "session-row skeleton", "aria-hidden": "true" },
    e("span", { class: "skeleton-line skeleton-title" }),
    e("span", { class: "skeleton-line skeleton-subtitle" }),
    e("span", { class: "skeleton-line skeleton-subtitle short" }),
  );
}

function mergeSession(list, session) {
  const filtered = list.filter((item) => item.session_id !== session.session_id);
  return [session, ...filtered];
}

function removeSession(list, sessionId) {
  return list.filter((item) => item.session_id !== sessionId);
}

function syncSession(list, session) {
  if (!session) return list;
  return list.map((item) => (item.session_id === session.session_id ? { ...item, ...session } : item));
}

function Sidebar({
  userId,
  setUserId,
  sessions,
  activeId,
  onRefresh,
  onCreate,
  onOpen,
  loading = false,
  creating = false,
  disabled = false,
}) {
  return e(
    "aside",
    { class: "sidebar" },
    e("div", { class: "brand" }, e("h1", null, "TrustFlow"), e("p", null, "Banking assistant sessions")),
    e(
      "div",
      { class: "user-strip" },
      e(UserRound, { size: 18 }),
      e("input", {
        value: userId,
        onInput: (event) => setUserId(event.currentTarget.value),
        placeholder: "user id",
      }),
    ),
    e(
      "div",
      { class: "toolbar" },
      e(
        IconButton,
        { title: "New session", kind: "primary", onClick: onCreate, disabled: loading || creating || disabled },
        creating ? e(Spinner) : e(MessageSquarePlus, { size: 18 }),
      ),
      e(
        IconButton,
        { title: "Refresh sessions", onClick: onRefresh, disabled: loading || creating || disabled },
        loading ? e(Spinner) : e(RefreshCw, { size: 18 }),
      ),
    ),
    e(
      "div",
      { class: "sidebar-count" },
      loading && sessions.length === 0
        ? "Loading sessions..."
        : `${sessions.length} session${sessions.length === 1 ? "" : "s"}`,
    ),
    e(
      "div",
      { class: "session-list" },
      loading && sessions.length === 0
        ? Array.from({ length: 4 }, (_, index) => e(SessionSkeletonRow, { key: index }))
        : sessions.map((session) =>
            e(
              "button",
              {
                key: session.session_id,
                class: `session-row ${session.session_id === activeId ? "active" : ""}`,
                onClick: () => onOpen(session.session_id),
                disabled: loading || disabled,
              },
              e("span", { class: "session-title" }, previewTitle(session)),
              e("span", { class: "session-subtitle" }, `${session.message_count || 0} messages`),
              e("span", { class: "session-subtitle" }, formatDate(session.updated_at)),
            ),
          ),
    ),
  );
}

function Topbar({ session, title, setTitle, onRename, onDelete, loading = false, saving = false }) {
  return e(
    "header",
    { class: "topbar" },
    e(
      "div",
      { class: "session-heading" },
      e("h2", null, session ? previewTitle(session) : "Select a session"),
      e(
        "p",
        null,
        session
          ? `${session.session_id} | ${session.message_count || 0} messages | ${formatDate(session.updated_at)}`
          : "Create or choose a session to begin.",
      ),
    ),
    e(
      "div",
      { class: "title-tools" },
      e("input", {
        value: title,
        onInput: (event) => setTitle(event.currentTarget.value),
        placeholder: "Session title",
        disabled: !session || loading || saving,
      }),
      e(
        IconButton,
        { title: "Save title", onClick: () => onRename(), disabled: !session || loading || saving },
        saving ? e(Spinner) : e(Check, { size: 18 }),
      ),
      e(
        IconButton,
        { title: "Archive session", onClick: () => onRename("archived"), disabled: !session || loading || saving },
        saving ? e(Spinner) : e(Archive, { size: 18 }),
      ),
      e(
        IconButton,
        { title: "Delete session", kind: "danger", onClick: onDelete, disabled: !session || loading || saving },
        saving ? e(Spinner) : e(Trash2, { size: 18 }),
      ),
    ),
  );
}

function MessageBubble({ message, isLatest = false, onQuickReply, quickReplyDisabled = false }) {
  const isUser = message.role === "user";
  const parsedData = parseMessageData(message.data);
  const vizPayload = extractVisualizationPayload(parsedData);
  const transferReceipt = extractTransferReceipt(parsedData);
  const categoryConfirmation = extractCategoryConfirmation(parsedData);
  const visualizations = Array.isArray(vizPayload?.visualizations) ? vizPayload.visualizations : [];
  const payload = parsedData ? JSON.stringify(parsedData, null, 2) : message.data ? String(message.data) : null;
  return e(
    "article",
    { class: `message ${isUser ? "user" : "assistant"} ${message.pending ? "pending" : ""}` },
    e(
      "div",
      { class: "message-meta" },
      e("span", null, isUser ? "You" : "TrustFlow"),
      message.pending ? e("span", { class: "message-status" }, "Loading...") : null,
      e("span", null, formatDate(message.created_at)),
    ),
    message.pending
      ? e("div", { class: "message-text pending-text" }, message.message)
      : e("div", {
          class: "message-text",
          dangerouslySetInnerHTML: { __html: renderMarkdown(message.message) },
        }),
    !isUser && !message.pending && transferReceipt ? e(TransactionReceiptCard, { receipt: transferReceipt }) : null,
    !isUser && !message.pending && isLatest && categoryConfirmation
      ? e(CategoryChoiceButtons, {
          categoryConfirmation,
          onQuickReply,
          disabled: quickReplyDisabled,
        })
      : null,
    !isUser && !message.pending && visualizations.length
      ? e(FinanceVisualizations, { visualizations, currency: vizPayload?.currency || "VND" })
      : null,
    payload ? e("details", null, e("summary", null, "Response data"), e("pre", null, payload)) : null,
  );
}

function MessageList({ messages, activeSessionId, loading = false, onQuickReply, quickReplyDisabled = false }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [messages.length, activeSessionId]);

  return e(
    "section",
    { class: "messages", ref },
    !activeSessionId
      ? e("div", { class: "empty-state" }, e(Bot, { size: 34 }), e("h3", null, "No session selected"))
      : loading && messages.length === 0
        ? e(
            "div",
            { class: "empty-state loading-state" },
            e(Spinner),
            e("h3", null, "Loading conversation"),
            e("p", null, "Fetching the latest messages."),
          )
      : messages.length === 0
        ? e("div", { class: "empty-state" }, e(Bot, { size: 34 }), e("h3", null, "Start the conversation"))
        : messages.map((message, index) =>
            e(MessageBubble, {
              key: message.id || `${message.role}-${message.created_at}`,
              message,
              isLatest: index === messages.length - 1,
              onQuickReply,
              quickReplyDisabled,
            }),
          ),
  );
}

function Composer({ disabled, onSend, loading = false }) {
  const [value, setValue] = useState("");

  async function submit() {
    const message = value.trim();
    if (!message) return;
    setValue("");
    await onSend(message);
  }

  return e(
    "footer",
    { class: "composer" },
    e("textarea", {
      value,
      disabled,
      placeholder: disabled ? "Create or select a session first" : "Ask TrustFlow...",
      onInput: (event) => setValue(event.currentTarget.value),
      onKeyDown: (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          submit();
        }
      },
    }),
    e(
      IconButton,
      { title: "Send", kind: "primary", disabled, onClick: submit },
      loading ? e(Spinner) : e(Send, { size: 18 }),
    ),
  );
}

function App() {
  const [userId, setUserId] = useState("u1");
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [title, setTitle] = useState("");
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isSessionLoading, setIsSessionLoading] = useState(false);
  const [busyAction, setBusyAction] = useState(null);
  const [error, setError] = useState("");
  const listRequestIdRef = useRef(0);
  const sessionRequestIdRef = useRef(0);
  const sendRequestIdRef = useRef(0);

  const canSend = useMemo(() => Boolean(activeSessionId && !busyAction && !isSessionLoading), [activeSessionId, busyAction, isSessionLoading]);

  function syncActiveSession(nextSession) {
    setActiveSession((current) => (current ? { ...current, ...nextSession } : nextSession));
    setTitle(nextSession?.title || "");
    setSessions((current) => syncSession(current, nextSession));
  }

  function appendPendingMessages(messageText, requestId) {
    const now = new Date().toISOString();
    const userTempId = `pending-user-${requestId}`;
    const assistantTempId = `pending-assistant-${requestId}`;
    setMessages((current) => [
      ...current,
      {
        id: userTempId,
        role: "user",
        message: messageText,
        created_at: now,
        pending: true,
      },
      {
        id: assistantTempId,
        role: "assistant",
        message: "TrustFlow is generating a reply...",
        created_at: now,
        pending: true,
      },
    ]);
    return { userTempId, assistantTempId };
  }

  function settlePendingMessages({ userTempId, assistantTempId, response, messageText }) {
    const now = new Date().toISOString();
    const assistantMessage = {
      id: `assistant-${assistantTempId}`,
      role: "assistant",
      message: response?.message || "No response returned.",
      data: response,
      created_at: now,
    };
    setMessages((current) =>
      current
        .map((item) => {
          if (item.id === userTempId) {
            return {
              ...item,
              pending: false,
              message: messageText,
              created_at: item.created_at || now,
            };
          }
          if (item.id === assistantTempId) {
            return assistantMessage;
          }
          return item;
        })
        .filter((item) => item.id !== userTempId || item.message || item.pending)
        .filter((item) => item.id !== assistantTempId || item.message),
    );
  }

  function clearPendingMessages(userTempId, assistantTempId) {
    setMessages((current) => current.filter((item) => item.id !== userTempId && item.id !== assistantTempId));
  }

  async function refreshSessions({ silent = false } = {}) {
    const currentUserId = userId.trim();
    if (!currentUserId) {
      setSessions([]);
      setActiveSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setTitle("");
      setIsLoadingSessions(false);
      return [];
    }

    const requestId = ++listRequestIdRef.current;
    if (!silent) {
      setIsLoadingSessions(true);
    }
    setError("");
    try {
      const data = await listSessions(currentUserId);
      if (requestId !== listRequestIdRef.current) return data;
      setSessions(data);
      if (activeSessionId) {
        const matched = data.find((session) => session.session_id === activeSessionId);
        if (matched) {
          setActiveSession((current) => (current ? { ...current, ...matched } : matched));
          if (!title.trim()) setTitle(matched.title || "");
        }
      }
      return data;
    } finally {
      if (requestId === listRequestIdRef.current && !silent) {
        setIsLoadingSessions(false);
      }
    }
  }

  async function openSession(sessionId) {
    const requestId = ++sessionRequestIdRef.current;
    const preview = sessions.find((session) => session.session_id === sessionId) || null;
    setActiveSessionId(sessionId);
    setActiveSession(preview ? { ...preview } : { session_id: sessionId });
    setMessages([]);
    setTitle(preview?.title || "");
    setIsSessionLoading(true);
    setError("");
    try {
      const detail = await getSession(sessionId);
      if (requestId !== sessionRequestIdRef.current) return;
      setActiveSession(detail);
      setMessages(detail.messages || []);
      setTitle(detail.title || "");
      setSessions((current) => syncSession(current, detail));
    } finally {
      if (requestId === sessionRequestIdRef.current) {
        setIsSessionLoading(false);
      }
    }
  }

  async function handleCreate() {
    setBusyAction("create");
    try {
      listRequestIdRef.current += 1;
      const session = await createSession(userId.trim(), title.trim() || null);
      setSessions((current) => mergeSession(current, session));
      setActiveSessionId(session.session_id);
      setActiveSession(session);
      setMessages([]);
      setTitle(session.title || "");
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRename(status) {
    if (!activeSessionId) return;
    setBusyAction("save");
    try {
      listRequestIdRef.current += 1;
      const payload = { title: title.trim() || activeSession?.title || activeSessionId };
      if (status) payload.status = status;
      const session = await updateSession(activeSessionId, payload);
      syncActiveSession(session);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDelete() {
    if (!activeSessionId || !confirm("Delete this session and all messages?")) return;
    setBusyAction("delete");
    try {
      listRequestIdRef.current += 1;
      await deleteSession(activeSessionId);
      const deletedId = activeSessionId;
      setActiveSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setTitle("");
      setSessions((current) => removeSession(current, deletedId));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSend(message) {
    if (!activeSessionId) return;
    const trimmedMessage = message.trim();
    if (!trimmedMessage) return;
    const requestId = ++sendRequestIdRef.current;
    const pendingIds = appendPendingMessages(trimmedMessage, requestId);
    setBusyAction("send");
    setError("");
    try {
      listRequestIdRef.current += 1;
      const response = await sendChatMessage({ userId: userId.trim(), sessionId: activeSessionId, message: trimmedMessage });
      if (requestId !== sendRequestIdRef.current) return;
      settlePendingMessages({ ...pendingIds, response, messageText: trimmedMessage });
      setActiveSession((current) =>
        current
          ? {
              ...current,
              updated_at: new Date().toISOString(),
              last_message_at: new Date().toISOString(),
              message_count: (current.message_count || 0) + 2,
            }
          : current,
      );
      setSessions((current) =>
        current.map((session) =>
          session.session_id === activeSessionId
            ? {
                ...session,
                updated_at: new Date().toISOString(),
                last_message_at: new Date().toISOString(),
                message_count: (session.message_count || 0) + 2,
              }
            : session,
        ),
      );
      refreshSessions({ silent: true }).catch((err) => setError(err.message));
    } catch (err) {
      clearPendingMessages(pendingIds.userTempId, pendingIds.assistantTempId);
      setError(err.message);
    } finally {
      if (requestId === sendRequestIdRef.current) {
        setBusyAction(null);
      }
    }
  }

  useEffect(() => {
    const trimmed = userId.trim();
    if (!trimmed) {
      listRequestIdRef.current += 1;
      sessionRequestIdRef.current += 1;
      sendRequestIdRef.current += 1;
      setSessions([]);
      setActiveSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setTitle("");
      setIsLoadingSessions(false);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      refreshSessions().catch((err) => setError(err.message));
    }, 250);

    return () => window.clearTimeout(timeoutId);
  }, [userId]);

  function handleRefreshClick() {
    refreshSessions().catch((err) => setError(err.message));
  }

  function handleOpenSession(sessionId) {
    openSession(sessionId).catch((err) => setError(err.message));
  }

  return e(
    "main",
    { class: "app-shell" },
    e(Sidebar, {
      userId,
      setUserId,
      sessions,
      activeId: activeSessionId,
      onRefresh: handleRefreshClick,
      onCreate: handleCreate,
      onOpen: handleOpenSession,
      loading: isLoadingSessions,
      creating: busyAction === "create",
      disabled: Boolean(busyAction),
    }),
    e(
      "section",
      { class: "workspace" },
      e(Topbar, {
        session: activeSession,
        title,
        setTitle,
        onRename: handleRename,
        onDelete: handleDelete,
        loading: isSessionLoading,
        saving: busyAction === "save" || busyAction === "delete",
      }),
      error ? e("div", { class: "error-banner" }, error) : null,
      e(MessageList, {
        messages,
        activeSessionId,
        loading: isSessionLoading,
        onQuickReply: handleSend,
        quickReplyDisabled: !canSend || busyAction === "send",
      }),
      e(Composer, { disabled: !canSend || busyAction === "send", onSend: handleSend, loading: busyAction === "send" }),
    ),
  );
}

render(e(App), document.getElementById("app"));
