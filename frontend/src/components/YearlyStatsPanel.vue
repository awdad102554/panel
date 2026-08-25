<script setup lang="ts">
import * as echarts from "echarts";
import { ElMessage } from "element-plus";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import * as statsApi from "@/api/stats";
import type { YearlyStats } from "@/types";

// 年度数据区:选择某年查看该年立案/结案/调解率/审理时长与逐月分布。
// 点击钻取通过 show-cases 事件交给父级的通用案件明细弹窗。
const emit = defineEmits<{
  (e: "show-cases", payload: { title: string; hint?: string; kind: string; value: string }): void;
}>();

const COLORS = { blue: "#3b82f6", green: "#34d399" };

const currentYear = new Date().getFullYear();
const selectedYear = ref(currentYear);
const availableYears = ref<number[]>([]);
const yearly = ref<YearlyStats | null>(null);
const loading = ref(false);
const chartRef = ref<HTMLDivElement>();
let chart: echarts.ECharts | null = null;

// 快速切换年份时,旧年份的响应不得覆盖新年份的数据。
let loadSeq = 0;

async function loadYear(year: number) {
  const seq = ++loadSeq;
  loading.value = true;
  try {
    const data = await statsApi.getYearlyStats(year);
    if (seq !== loadSeq) return;
    yearly.value = data;
    availableYears.value = data.available_years;
    renderChart();
  } catch {
    if (seq === loadSeq) ElMessage.error("年度数据加载失败,请稍后重试");
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

function renderChart() {
  if (!chartRef.value || !yearly.value) return;
  if (!chart) {
    chart = echarts.init(chartRef.value);
    chart.on("click", (params) => {
      if (!yearly.value) return;
      const month = `${yearly.value.year}-${String(params.dataIndex + 1).padStart(2, "0")}`;
      const kind = params.seriesName === "立案" ? "filed_month" : "closed_month";
      emit("show-cases", {
        title: `${yearly.value.year}年${params.dataIndex + 1}月${params.seriesName}案件`,
        kind,
        value: month,
      });
    });
  }
  chart.setOption(
    {
      tooltip: { trigger: "axis" },
      legend: { data: ["立案", "结案"], top: 0 },
      grid: { left: 8, right: 24, top: 36, bottom: 8, containLabel: true },
      xAxis: { type: "category", data: Array.from({ length: 12 }, (_, i) => `${i + 1}月`) },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        {
          name: "立案",
          type: "bar",
          cursor: "pointer",
          data: yearly.value.monthly_filed,
          itemStyle: { color: COLORS.blue, borderRadius: [3, 3, 0, 0] },
        },
        {
          name: "结案",
          type: "bar",
          cursor: "pointer",
          data: yearly.value.monthly_closed,
          itemStyle: { color: COLORS.green, borderRadius: [3, 3, 0, 0] },
        },
      ],
    },
    true,
  );
}

function formatRate(rate: number) {
  return `${(rate * 100).toFixed(1)}%`;
}

// 统计年度(12-10~次年12-10)标签:2026年度 = 2025-12-10 ~ 2026-12-10。
const statRangeLabel = computed(() => `${selectedYear.value - 1}-12-10 ~ ${selectedYear.value}-12-10`);

function resize() {
  chart?.resize();
}

onMounted(() => {
  loadYear(currentYear);
  window.addEventListener("resize", resize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div class="chart-card">
    <h3 class="year-panel-header">
      年度数据
      <el-select v-model="selectedYear" size="small" style="width: 110px" :teleported="false" @change="loadYear">
        <el-option v-for="y in availableYears" :key="y" :label="`${y} 年`" :value="y" />
      </el-select>
    </h3>
    <div v-loading="loading">
      <template v-if="yearly">
        <div v-if="yearly.stat_year" class="year-row">
          <div class="year-row-label">统计年度（{{ statRangeLabel }}）</div>
          <div class="year-kpis">
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-blue">{{ yearly.stat_year.filed }}</span>
              <span class="year-kpi-label">立案</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-green">{{ yearly.stat_year.closed }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">结案率 {{ formatRate(yearly.stat_year.closing_rate) }}</span>
              <span class="year-kpi-label">结案</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-green">{{ yearly.stat_year.mediated }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">调解率 {{ formatRate(yearly.stat_year.mediation_rate) }}</span>
              <span class="year-kpi-label">调解</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-green">{{ yearly.stat_year.mediated + yearly.stat_year.withdrawn }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">调撤率 {{ formatRate(yearly.stat_year.mediation_withdrawal_rate) }}</span>
              <span class="year-kpi-label">调撤</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-amber">{{ yearly.stat_year.final }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">一裁终局率 {{ formatRate(yearly.stat_year.final_ruling_rate) }}</span>
              <span class="year-kpi-label">一裁终局</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-amber">{{ yearly.stat_year.avg_duration_days }} 天</span>
              <span class="year-kpi-label">平均审理时长</span>
            </div>
          </div>
        </div>
        <div class="year-row">
          <div class="year-row-label">自然年度</div>
          <div class="year-kpis">
            <div
              class="year-kpi clickable"
              title="点击查看该年立案案件"
              @click="emit('show-cases', { title: `${selectedYear}年立案案件`, kind: 'filed_year', value: String(selectedYear) })"
            >
              <span class="year-kpi-value accent-text-blue">{{ yearly.filed }}</span>
              <span class="year-kpi-label">立案</span>
            </div>
            <div
              class="year-kpi clickable"
              title="点击查看该年结案案件"
              @click="emit('show-cases', { title: `${selectedYear}年结案案件`, kind: 'closed_year', value: String(selectedYear) })"
            >
              <span class="year-kpi-value accent-text-green">{{ yearly.closed }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">结案率 {{ formatRate(yearly.closing_rate) }}</span>
              <span class="year-kpi-label">结案</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-green">{{ yearly.mediated }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">调解率 {{ formatRate(yearly.mediation_rate) }}</span>
              <span class="year-kpi-label">调解</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-green">{{ yearly.mediated + yearly.withdrawn }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">调撤率 {{ formatRate(yearly.mediation_withdrawal_rate) }}</span>
              <span class="year-kpi-label">调撤</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-amber">{{ yearly.final }}<span class="year-kpi-unit">件</span></span>
              <span class="year-kpi-rate">一裁终局率 {{ formatRate(yearly.final_ruling_rate) }}</span>
              <span class="year-kpi-label">一裁终局</span>
            </div>
            <div class="year-kpi">
              <span class="year-kpi-value accent-text-amber">{{ yearly.avg_duration_days }} 天</span>
              <span class="year-kpi-label">平均审理时长</span>
            </div>
          </div>
        </div>
      </template>
      <div ref="chartRef" class="chart-body" />
    </div>
  </div>
</template>

<style scoped>
.chart-card {
  background: #fff;
  border-radius: var(--radius-md);
  box-shadow: 0 2px 10px rgba(15, 31, 74, 0.06);
  padding: 16px 20px;
  margin-bottom: 16px;
}

.year-panel-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.year-row {
  margin-bottom: 10px;
}

.year-row-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 0 0 6px;
}

.year-kpis {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 16px;
  padding: 4px 0 10px;
}

.year-kpi {
  display: flex;
  flex-direction: column;
  padding: 10px 16px;
  border-radius: 8px;
  background: #f8fafc;
}

.year-kpi.clickable {
  cursor: pointer;
  transition: transform 0.15s ease, background 0.15s ease;
}

.year-kpi.clickable:hover {
  background: #eef2f7;
  transform: translateY(-1px);
}

.year-kpi-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}

.year-kpi-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.year-kpi-unit {
  font-size: 13px;
  font-weight: 400;
  margin-left: 2px;
}

.year-kpi-rate {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.chart-body {
  height: 260px;
  /* body 全局 zoom 1.1 会让 echarts 画布命中坐标错位,反向缩放抵消。 */
  zoom: 0.9091;
}

.accent-text-blue {
  color: var(--accent-blue);
}
.accent-text-green {
  color: var(--accent-green);
}
.accent-text-amber {
  color: var(--accent-amber);
}
</style>
