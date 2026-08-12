<script setup lang="ts">
import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref } from "vue";

import * as dashboardApi from "@/api/dashboard";
import type { DashboardCharts } from "@/types";

export interface ChartCasesRequest {
  title: string;
  hint?: string;
  kind: string;
  value: string;
}

const emit = defineEmits<{ (e: "show-cases", payload: ChartCasesRequest): void }>();

// 与 styles/tokens.css 的 accent 色系一致。
const COLORS = {
  cyan: "#22d3ee",
  blue: "#3b82f6",
  green: "#34d399",
  amber: "#f59e0b",
  red: "#f87171",
  purple: "#8e44ad",
  gray: "#94a3b8",
};

// 紧急度颜色与卡片/监控页的标签语义一致(红=超期,橙红=紧急,黄=临近,紫=中止过久…)。
// 后端图表口径不含 closed/rejected,此处缺省时兜底显示原字符串。
const URGENCY_META: Record<string, { label: string; color: string }> = {
  overdue: { label: "已超期", color: COLORS.red },
  urgent: { label: "紧急", color: "#f97316" },
  soon: { label: "临近", color: COLORS.amber },
  normal: { label: "正常", color: COLORS.green },
  paused: { label: "已中止", color: COLORS.gray },
  paused_overdue: { label: "中止过久", color: COLORS.purple },
};

const trendRef = ref<HTMLDivElement>();
const openStepsRef = ref<HTMLDivElement>();
const endWaysRef = ref<HTMLDivElement>();
const urgencyRef = ref<HTMLDivElement>();
const loading = ref(true);
const empty = ref(false);

const charts: echarts.ECharts[] = [];

function baseGrid() {
  return { left: 8, right: 24, top: 36, bottom: 8, containLabel: true };
}

function monthTitle(month: string) {
  const [year, m] = month.split("-");
  return `${year}年${Number(m)}月`;
}

function renderTrend(el: HTMLDivElement, data: DashboardCharts) {
  const chart = echarts.init(el);
  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["立案", "结案"], top: 0 },
    grid: baseGrid(),
    xAxis: {
      type: "category",
      data: data.monthly_trend.map((p) => p.month.slice(2).replace("-", "/")),
      boundaryGap: false,
    },
    yAxis: { type: "value", minInterval: 1 },
    series: [
      {
        name: "立案",
        type: "line",
        smooth: true,
        cursor: "pointer",
        data: data.monthly_trend.map((p) => p.filed),
        itemStyle: { color: COLORS.blue },
        areaStyle: { opacity: 0.08 },
      },
      {
        name: "结案",
        type: "line",
        smooth: true,
        cursor: "pointer",
        data: data.monthly_trend.map((p) => p.closed),
        itemStyle: { color: COLORS.green },
        areaStyle: { opacity: 0.08 },
      },
    ],
  });
  chart.on("click", (params) => {
    const point = data.monthly_trend[params.dataIndex];
    if (!point) return;
    const kind = params.seriesName === "立案" ? "filed_month" : "closed_month";
    emit("show-cases", {
      title: `${monthTitle(point.month)}${params.seriesName}案件`,
      kind,
      value: point.month,
    });
  });
  charts.push(chart);
}

function renderOpenSteps(el: HTMLDivElement, data: DashboardCharts) {
  const items = [...data.open_steps].reverse(); // 横向条形图数量多的在上
  const chart = echarts.init(el);
  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: baseGrid(),
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: items.map((i) => i.name) },
    series: [
      {
        type: "bar",
        data: items.map((i) => i.count),
        barWidth: 16,
        cursor: "pointer",
        itemStyle: { color: COLORS.cyan, borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right" },
      },
    ],
  });
  chart.on("click", (params) => {
    const item = items[params.dataIndex];
    if (!item) return;
    emit("show-cases", {
      title: `在办案件 · ${item.name}`,
      kind: "open_step",
      value: item.name,
    });
  });
  charts.push(chart);
}

function donutBase(name: string) {
  return {
    tooltip: { trigger: "item" as const, formatter: "{b}: {c} 件 ({d}%)" },
    legend: { bottom: 0 },
    series: [
      {
        name,
        type: "pie" as const,
        radius: ["42%", "68%"],
        center: ["50%", "44%"],
        label: { formatter: "{b}\n{c} 件" },
        itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 2 },
      },
    ],
  };
}

const END_WAY_COLORS: Record<string, string> = {
  调解: COLORS.green,
  裁决: COLORS.blue,
  撤回: COLORS.amber,
  撤销: COLORS.red,
};

function renderEndWays(el: HTMLDivElement, data: DashboardCharts) {
  const chart = echarts.init(el);
  const option = donutBase("结案方式");
  chart.setOption({
    ...option,
    series: [
      {
        ...option.series[0],
        cursor: "pointer",
        data: data.end_ways.map((i) => ({
          name: i.name,
          value: i.count,
          itemStyle: { color: END_WAY_COLORS[i.name] },
        })),
      },
    ],
  });
  chart.on("click", (params) => {
    const item = data.end_ways[params.dataIndex];
    if (!item) return;
    emit("show-cases", {
      title: `结案方式 · ${item.name}`,
      kind: "end_way",
      value: item.name,
    });
  });
  charts.push(chart);
}

function renderUrgency(el: HTMLDivElement, data: DashboardCharts) {
  const chart = echarts.init(el);
  const option = donutBase("紧急度");
  chart.setOption({
    ...option,
    series: [
      {
        ...option.series[0],
        cursor: "pointer",
        data: data.urgency.map((i) => ({
          name: URGENCY_META[i.name]?.label ?? i.name,
          value: i.count,
          itemStyle: { color: URGENCY_META[i.name]?.color ?? COLORS.gray },
        })),
      },
    ],
  });
  chart.on("click", (params) => {
    const item = data.urgency[params.dataIndex];
    if (!item) return;
    emit("show-cases", {
      title: `紧急度 · ${URGENCY_META[item.name]?.label ?? item.name}`,
      kind: "urgency",
      value: item.name,
    });
  });
  charts.push(chart);
}

function resizeAll() {
  charts.forEach((c) => c.resize());
}

onMounted(async () => {
  // 监听器同步注册(不能等 await 之后),否则加载期间离开页面会永久泄漏。
  window.addEventListener("resize", resizeAll);
  try {
    const data = await dashboardApi.getDashboardCharts();
    empty.value =
      !data.monthly_trend.length && !data.open_steps.length && !data.end_ways.length && !data.urgency.length;
    if (!empty.value) {
      if (trendRef.value) renderTrend(trendRef.value, data);
      if (openStepsRef.value) renderOpenSteps(openStepsRef.value, data);
      if (endWaysRef.value) renderEndWays(endWaysRef.value, data);
      if (urgencyRef.value) renderUrgency(urgencyRef.value, data);
    }
  } finally {
    loading.value = false;
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeAll);
  charts.forEach((c) => c.dispose());
});
</script>

<template>
  <div v-loading="loading" class="charts-grid">
    <el-empty v-if="empty" description="暂无内网同步数据" class="charts-empty" />
    <template v-else>
      <div class="chart-card">
        <h3>近 12 个月立案 / 结案趋势</h3>
        <div ref="trendRef" class="chart-body" />
      </div>
      <div class="chart-card">
        <h3>在办案件状态分布</h3>
        <div ref="openStepsRef" class="chart-body" />
      </div>
      <div class="chart-card">
        <h3>结案方式分布</h3>
        <div ref="endWaysRef" class="chart-body" />
      </div>
      <div class="chart-card">
        <h3>在办案件紧急度分布</h3>
        <div ref="urgencyRef" class="chart-body" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 4px;
  min-height: 200px;
}

.charts-empty {
  grid-column: 1 / -1;
}

.chart-card {
  background: #fff;
  border-radius: var(--radius-md);
  box-shadow: 0 2px 10px rgba(15, 31, 74, 0.06);
  padding: 16px 20px;
}

.chart-card h3 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.chart-body {
  height: 260px;
  /* body 全局 zoom 1.1 会让 echarts 画布命中坐标错位,反向缩放抵消(1.1×0.9091≈1)。 */
  zoom: 0.9091;
}

@media (max-width: 1200px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
