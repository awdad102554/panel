<script setup lang="ts">
import * as echarts from "echarts";
import { ElMessage } from "element-plus";
import { onBeforeUnmount, onMounted, ref } from "vue";

import * as dashboardApi from "@/api/dashboard";
import * as statsApi from "@/api/stats";
import InternalCaseDialog from "@/components/InternalCaseDialog.vue";
import type { StatsOverview } from "@/types";

const COLORS = {
  blue: "#3b82f6",
  green: "#34d399",
  amber: "#f59e0b",
  red: "#f87171",
  cyan: "#22d3ee",
  gray: "#94a3b8",
};

const overview = ref<StatsOverview | null>(null);
const loading = ref(true);

const arbitratorRef = ref<HTMLDivElement>();
const durationRef = ref<HTMLDivElement>();
const compareRef = ref<HTMLDivElement>();
const caseDialog = ref<InstanceType<typeof InternalCaseDialog>>();

const charts: echarts.ECharts[] = [];

// 年度对比图:指标切换(立案/结案),累计曲线——今年实线、去年虚线,
// 两条线的差距即同比差值,tooltip 显示当月值/累计值/累计同比。
const compareMetric = ref<"立案" | "结案">("立案");
let compareChart: echarts.ECharts | null = null;

function _cumsum(arr: number[]): number[] {
  let sum = 0;
  return arr.map((v) => (sum += v));
}

function buildCompareOption() {
  const yc = overview.value?.year_compare;
  if (!yc) return {};
  const thisY = yc.this_year.year;
  const lastY = yc.last_year.year;
  const isFiled = compareMetric.value === "立案";
  const thisMonthly = isFiled ? yc.monthly_filed_this : yc.monthly_closed_this;
  const lastMonthly = isFiled ? yc.monthly_filed_last : yc.monthly_closed_last;
  const thisCum = _cumsum(thisMonthly);
  const lastCum = _cumsum(lastMonthly);
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params: { dataIndex: number }[]) => {
        const idx = params[0]?.dataIndex ?? 0;
        const fmt = (pct: number) => `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
        const cumYoy = lastCum[idx] > 0 ? fmt(((thisCum[idx] - lastCum[idx]) / lastCum[idx]) * 100) : "-";
        const monYoy =
          lastMonthly[idx] > 0 ? fmt(((thisMonthly[idx] - lastMonthly[idx]) / lastMonthly[idx]) * 100) : "-";
        return (
          `${idx + 1}月(${compareMetric.value})<br/>` +
          `${thisY} 当月 ${thisMonthly[idx]} 件 / 累计 ${thisCum[idx]} 件<br/>` +
          `${lastY} 当月 ${lastMonthly[idx]} 件 / 累计 ${lastCum[idx]} 件<br/>` +
          `当月同比: ${monYoy} · 累计同比: ${cumYoy}`
        );
      },
    },
    legend: { data: [`${thisY}年累计`, `${lastY}年累计`], top: 0 },
    grid: { left: 8, right: 24, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: Array.from({ length: 12 }, (_, i) => `${i + 1}月`), boundaryGap: false },
    yAxis: { type: "value", minInterval: 1 },
    series: [
      {
        name: `${thisY}年累计`,
        type: "line",
        smooth: true,
        cursor: "pointer",
        data: thisCum,
        itemStyle: { color: COLORS.blue },
        lineStyle: { width: 3 },
        areaStyle: { opacity: 0.08 },
        symbol: "circle",
        symbolSize: 7,
      },
      {
        name: `${lastY}年累计`,
        type: "line",
        smooth: true,
        cursor: "pointer",
        data: lastCum,
        itemStyle: { color: COLORS.gray },
        lineStyle: { type: "dashed", width: 2 },
        symbol: "circle",
        symbolSize: 6,
      },
    ],
  };
}

function renderCompareChart(el: HTMLDivElement) {
  const yc = overview.value?.year_compare;
  if (!yc) return;
  compareChart = echarts.init(el);
  compareChart.setOption(buildCompareOption());
  compareChart.on("click", (params) => {
    // 点"去年累计"钻取去年该月,其余(今年累计/当月同比柱)钻取今年该月。
    const year =
      String(params.seriesName) === `${yc.last_year.year}年累计` ? yc.last_year.year : yc.this_year.year;
    const kind = compareMetric.value === "立案" ? "filed_month" : "closed_month";
    const month = `${year}-${String(params.dataIndex + 1).padStart(2, "0")}`;
    caseDialog.value?.open(`${year}年${params.dataIndex + 1}月${compareMetric.value}案件`, "", () =>
      dashboardApi.getChartCases(kind, month),
    );
  });
  charts.push(compareChart);
}

function onCompareMetricChange() {
  // 切换立案/结案时整体重绘(option 从最新 overview + 指标构建)
  compareChart?.setOption(buildCompareOption(), true);
}

function renderAll(data: StatsOverview) {
  if (arbitratorRef.value) {
    const items = [...data.arbitrator_stats].reverse();
    const chart = echarts.init(arbitratorRef.value);
    chart.setOption({
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: ["已结案", "在办"], top: 0 },
      grid: { left: 8, right: 24, top: 36, bottom: 8, containLabel: true },
      xAxis: { type: "value", minInterval: 1 },
      yAxis: { type: "category", data: items.map((p) => p.name) },
      series: [
        {
          name: "已结案",
          type: "bar",
          stack: "total",
          cursor: "pointer",
          data: items.map((p) => p.closed),
          itemStyle: { color: COLORS.blue },
        },
        {
          name: "在办",
          type: "bar",
          stack: "total",
          cursor: "pointer",
          data: items.map((p) => p.open),
          itemStyle: { color: COLORS.amber },
        },
      ],
    });
    chart.on("click", (params) => {
      const person = items[params.dataIndex];
      if (!person) return;
      caseDialog.value?.open(`仲裁员 · ${person.name}`, "该仲裁员经办的全部案件(含已结案历史)。", () =>
        dashboardApi.getChartCases("arbitrator", person.name),
      );
    });
    charts.push(chart);
  }

  if (durationRef.value) {
    const items = data.duration_buckets;
    const chart = echarts.init(durationRef.value);
    chart.setOption({
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 8, right: 24, top: 36, bottom: 8, containLabel: true },
      xAxis: { type: "category", data: items.map((i) => i.name) },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        {
          type: "bar",
          data: items.map((i, idx) => ({
            value: i.count,
            itemStyle: { color: [COLORS.green, COLORS.amber, COLORS.red, COLORS.red][idx] },
          })),
          barWidth: 36,
          cursor: "pointer",
          itemStyle: { borderRadius: [4, 4, 0, 0] },
          label: { show: true, position: "top" },
        },
      ],
    });
    chart.on("click", (params) => {
      const item = items[params.dataIndex];
      if (!item) return;
      caseDialog.value?.open(
        `审理时长 · ${item.name}`,
        "审理时长 = 结案日期 - 立案日期 - 中止天数(中止期间不计入法定审限,法定审限 45 天,可延长 15 天)。",
        () => dashboardApi.getChartCases("duration_bucket", item.name),
      );
    });
    charts.push(chart);
  }
}

function resizeAll() {
  charts.forEach((c) => c.resize());
}

function formatRate(rate: number) {
  return `${(rate * 100).toFixed(1)}%`;
}

function openOverLimit(kind: string, title: string) {
  caseDialog.value?.open(
    title,
    "超审限 = 经过天数(立案至结案/今天,扣除中止期间) > 45 天法定审限 + 已批准延期。",
    () => dashboardApi.getChartCases(kind, ""),
  );
}

// 卸载标志:加载期间离开页面时,rAF 回调不得再向 charts 追加实例。
let unmounted = false;

onMounted(async () => {
  // 监听器同步注册(不能等 await 之后),否则加载期间离开页面会永久泄漏。
  window.addEventListener("resize", resizeAll);
  try {
    const data = await statsApi.getStatsOverview();
    overview.value = data;
    // 图表依赖渲染后的 DOM 尺寸,等下一帧再初始化。
    requestAnimationFrame(() => {
      if (unmounted) return;
      renderAll(data);
      if (compareRef.value) renderCompareChart(compareRef.value);
    });
  } catch {
    ElMessage.error("统计数据加载失败,请稍后重试");
  } finally {
    loading.value = false;
  }
});

onBeforeUnmount(() => {
  unmounted = true;
  window.removeEventListener("resize", resizeAll);
  charts.forEach((c) => c.dispose());
});
</script>

<template>
  <div v-loading="loading" class="stats-view">
    <div class="stats-header">
      <h2>统计分析</h2>
      <el-tag v-if="overview?.source === 'internal'" type="success" effect="dark" class="source-tag">
        数据来源：内网案件系统（真实数据）
      </el-tag>
      <el-tag v-else-if="overview?.source === 'local'" type="warning" effect="dark" class="source-tag">
        数据来源：本地模拟数据（未连接内网，仅供测试）
      </el-tag>
    </div>

    <div class="kpi-row">
      <div class="kpi-card accent-blue">
        <div class="kpi-value">{{ overview?.kpis.receive_total ?? "-" }}</div>
        <div class="kpi-label">累计收件</div>
      </div>
      <div class="kpi-card accent-blue">
        <div class="kpi-value">{{ overview?.kpis.filed_total ?? "-" }}</div>
        <div class="kpi-label">累计立案</div>
      </div>
      <div class="kpi-card accent-cyan">
        <div class="kpi-value">{{ overview?.kpis.open_cases ?? "-" }}</div>
        <div class="kpi-label">在办案件</div>
      </div>
      <div class="kpi-card accent-green">
        <div class="kpi-value">{{ overview?.kpis.closed_cases ?? "-" }}</div>
        <div class="kpi-label">已结案</div>
      </div>
      <div class="kpi-card accent-green">
        <div class="kpi-value">{{ overview ? formatRate(overview.kpis.mediation_rate) : "-" }}</div>
        <div class="kpi-label">调解率</div>
      </div>
      <div class="kpi-card accent-amber">
        <div class="kpi-value">{{ overview ? `${overview.kpis.avg_duration_days} 天` : "-" }}</div>
        <div class="kpi-label">平均审理时长</div>
      </div>
      <div class="kpi-card accent-red">
        <div class="kpi-value">{{ overview?.kpis.overdue_cases ?? "-" }}</div>
        <div class="kpi-label">当前超期</div>
      </div>
      <div
        class="kpi-card accent-red clickable"
        title="经过天数(扣中止) > 45天法定审限+批准延期;点击查看案件"
        @click="openOverLimit('over_limit_open', '在办超审限')"
      >
        <div class="kpi-value">{{ overview?.kpis.over_limit_open ?? "-" }}</div>
        <div class="kpi-label">在办超审限</div>
      </div>
      <div
        class="kpi-card accent-amber clickable"
        title="结案时实际审理天数(扣中止)超过审限的案件;点击查看案件"
        @click="openOverLimit('over_limit_closed', '结案超审限')"
      >
        <div class="kpi-value">{{ overview?.kpis.over_limit_closed ?? "-" }}</div>
        <div class="kpi-label">结案超审限</div>
      </div>
    </div>

    <div class="charts-grid">
      <div class="chart-card">
        <h3>仲裁员办案量</h3>
        <div ref="arbitratorRef" class="chart-body" />
      </div>
      <div class="chart-card">
        <h3>审理时长分布（已扣除中止期间）</h3>
        <div ref="durationRef" class="chart-body" />
      </div>
    </div>

    <div v-if="overview?.year_compare" class="chart-card full-width">
      <h3 class="compare-header">
        年度对比（{{ overview.year_compare.this_year.year }} vs {{ overview.year_compare.last_year.year }}）
        <el-radio-group v-model="compareMetric" size="small" @change="onCompareMetricChange">
          <el-radio-button value="立案">立案</el-radio-button>
          <el-radio-button value="结案">结案</el-radio-button>
        </el-radio-group>
        <span class="year-summary">
          今年立案 {{ overview.year_compare.this_year.filed }} / 结案 {{ overview.year_compare.this_year.closed }}，
          去年立案 {{ overview.year_compare.last_year.filed }} / 结案 {{ overview.year_compare.last_year.closed }}
        </span>
      </h3>
      <div ref="compareRef" class="chart-body" />
    </div>

    <InternalCaseDialog ref="caseDialog" />
  </div>
</template>

<style scoped>
.stats-header {
  margin-bottom: 16px;
}

.stats-header h2 {
  margin: 0 0 8px;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}

.kpi-card {
  position: relative;
  background: #fff;
  border-radius: var(--radius-md);
  box-shadow: 0 2px 10px rgba(15, 31, 74, 0.06);
  padding: 18px 20px 14px 20px;
  overflow: hidden;
}

.kpi-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}

.kpi-card.clickable {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.kpi-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(15, 31, 74, 0.1);
}

.accent-cyan::before {
  background: var(--accent-cyan);
}
.accent-blue::before {
  background: var(--accent-blue);
}
.accent-green::before {
  background: var(--accent-green);
}
.accent-amber::before {
  background: var(--accent-amber);
}
.accent-red::before {
  background: var(--accent-red);
}

.kpi-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
  white-space: nowrap;
}

.kpi-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-top: 6px;
  white-space: nowrap;
}

.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
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
  height: 280px;
  /* body 全局 zoom 1.1 会让 echarts 画布命中坐标错位,反向缩放抵消(1.1×0.9091≈1)。 */
  zoom: 0.9091;
}

.full-width {
  margin-top: 16px;
}

.year-summary {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
  margin-left: 12px;
}

.compare-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

@media (max-width: 1200px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
