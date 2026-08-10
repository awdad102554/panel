<script setup lang="ts">
import {
  AlarmClock,
  Calendar,
  Checked,
  ChatDotRound,
  CircleCheck,
  Folder,
  List,
  Stamp,
  VideoPause,
} from "@element-plus/icons-vue";
import { computed, onMounted, ref } from "vue";

import * as dashboardApi from "@/api/dashboard";
import { getTimeLimits } from "@/api/settings";
import DashboardCharts, { type ChartCasesRequest } from "@/components/DashboardCharts.vue";
import InternalCaseDialog from "@/components/InternalCaseDialog.vue";
import YearlyStatsPanel from "@/components/YearlyStatsPanel.vue";
import type { DashboardSummary, HearingList } from "@/types";

const summary = ref<DashboardSummary | null>(null);

// 时效阈值(从"时限设置"读取,用于生成明细弹窗的口径提示文案)。
const urgentDays = ref(1);
const soonDays = ref(3);
const pausedAlertDays = ref(15);

const today = computed(() =>
  new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" }),
);

const cards = [
  { key: "due_reminders", label: "时效提醒", icon: AlarmClock, accent: "red" },
  { key: "hearings_upcoming", label: "近日开庭", icon: Calendar, accent: "cyan" },
  { key: "pending_receive", label: "待办案件", icon: List, accent: "cyan" },
  { key: "open_cases", label: "在办案件", icon: Folder, accent: "blue" },
  { key: "pending_mediation", label: "待调解", icon: ChatDotRound, accent: "blue" },
  { key: "heard_awaiting_decision", label: "已开庭待裁决", icon: Checked, accent: "green" },
  { key: "paused_long", label: "中止过久", icon: VideoPause, accent: "amber" },
  { key: "today_filed", label: "今日立案", icon: Stamp, accent: "green" },
  { key: "today_closed", label: "今日结案", icon: CircleCheck, accent: "blue" },
] as const;

type CardKey = (typeof cards)[number]["key"];

// 明细弹窗顶部的口径提示;无特殊说明的卡片不显示。
const CARD_HINTS: Partial<Record<CardKey, string>> = {
  due_reminders: "时效维度需要处理的事项:已超期(含审批退回需返工的案件)、紧急(剩1天)、临近(剩3天内)。",
  pending_receive: "收件环节待审核、尚未立案的案件,需要工作人员审查推进;已处理/已退回的收件不在此列。",
  open_cases: "已立案、尚未结案的全部在办案件(含中止/调解/裁决中等子状态),按紧急度排序。",
  paused_long: "审理中止超过 15 天阈值的案件,需要跟进是否恢复审理。",
};

const hearingDialogVisible = ref(false);
const hearingLoading = ref(false);
const hearings = ref<HearingList | null>(null);

// 通用案件明细弹窗(卡片与图表共用)
const caseDialog = ref<InstanceType<typeof InternalCaseDialog>>();

function openCard(key: CardKey, label: string) {
  if (key === "hearings_upcoming") {
    openHearings();
    return;
  }
  caseDialog.value?.open(label, CARD_HINTS[key] ?? "", () => dashboardApi.getCardCases(key));
}

function onChartShowCases(req: ChartCasesRequest) {
  caseDialog.value?.open(req.title, req.hint ?? "", () => dashboardApi.getChartCases(req.kind, req.value));
}

async function openHearings() {
  hearingDialogVisible.value = true;
  hearingLoading.value = true;
  try {
    hearings.value = await dashboardApi.getUpcomingHearings();
  } finally {
    hearingLoading.value = false;
  }
}

function hearingDay(openAt: string) {
  const d = new Date(openAt);
  return d.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });
}

function hearingTime(openAt: string, endAt: string | null) {
  const fmt = (s: string) => s.slice(11, 16);
  return endAt ? `${fmt(openAt)}–${fmt(endAt)}` : fmt(openAt);
}

onMounted(async () => {
  summary.value = await dashboardApi.getDashboardSummary();
});
</script>

<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h2>案件总览</h2>
      <p class="dashboard-date">{{ today }}</p>
      <el-tag v-if="summary?.source === 'internal'" type="success" effect="dark" class="source-tag">
        数据来源：内网案件系统（真实数据）
      </el-tag>
      <el-tag v-else-if="summary?.source === 'local'" type="warning" effect="dark" class="source-tag">
        数据来源：本地模拟数据（未连接内网，仅供测试）
      </el-tag>
    </div>
    <div class="cards-grid">
      <div
        v-for="card in cards"
        :key="card.key"
        class="stat-card clickable"
        :class="`accent-${card.accent}`"
        @click="openCard(card.key, card.label)"
      >
        <div class="stat-icon">
          <el-icon :size="18"><component :is="card.icon" /></el-icon>
        </div>
        <div class="stat-value">{{ summary?.[card.key] ?? "-" }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </div>
    </div>

    <YearlyStatsPanel @show-cases="onChartShowCases" />

    <DashboardCharts @show-cases="onChartShowCases" />

    <el-dialog v-model="hearingDialogVisible" title="近日开庭安排" width="1120px">
      <p class="dialog-hint">
        统计范围：{{ hearings?.start ?? "-" }} ~ {{ hearings?.end ?? "-" }}（今日至下周日），共
        {{ hearings?.total ?? 0 }} 场。数据来自内网案件系统庭审日历。
      </p>
      <el-table v-loading="hearingLoading" :data="hearings?.items ?? []" empty-text="该时间段暂无开庭安排">
        <el-table-column label="开庭日期" width="140">
          <template #default="{ row }">{{ hearingDay(row.open_at) }}</template>
        </el-table-column>
        <el-table-column label="时间" width="110">
          <template #default="{ row }">{{ hearingTime(row.open_at, row.end_at) }}</template>
        </el-table-column>
        <el-table-column label="案号" prop="case_no" width="250" show-overflow-tooltip />
        <el-table-column label="当事人" width="330" show-overflow-tooltip>
          <template #default="{ row }">{{ row.applicant ?? "?" }} → {{ row.respondent ?? "?" }}</template>
        </el-table-column>
        <el-table-column label="仲裁庭" width="110">
          <template #default="{ row }">{{ row.tribunal_name ?? "-" }}</template>
        </el-table-column>
        <el-table-column label="仲裁员" width="90">
          <template #default="{ row }">{{ row.arbitrator ?? "-" }}</template>
        </el-table-column>
        <el-table-column label="书记员" min-width="90">
          <template #default="{ row }">{{ row.clerk ?? "-" }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <InternalCaseDialog ref="caseDialog" />
  </div>
</template>

<style scoped>
.dashboard-header {
  margin-bottom: 20px;
}

.dashboard-header h2 {
  margin: 0 0 4px;
}

.dashboard-date {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0;
}

.source-tag {
  margin-top: 8px;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}

@media (max-width: 1400px) {
  .cards-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 1100px) {
  .cards-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .cards-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-card {
  position: relative;
  background: #fff;
  border-radius: var(--radius-md);
  box-shadow: 0 2px 10px rgba(15, 31, 74, 0.06);
  padding: 14px 16px 12px 18px;
  overflow: hidden;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(15, 31, 74, 0.1);
}

.stat-card.clickable {
  cursor: pointer;
}

.dialog-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0 0 12px;
}

.stat-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
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

.stat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  margin-bottom: 8px;
}

.accent-cyan .stat-icon {
  color: var(--accent-cyan);
  background: rgba(34, 211, 238, 0.12);
}
.accent-blue .stat-icon {
  color: var(--accent-blue);
  background: rgba(59, 130, 246, 0.12);
}
.accent-green .stat-icon {
  color: var(--accent-green);
  background: rgba(52, 211, 153, 0.12);
}
.accent-amber .stat-icon {
  color: var(--accent-amber);
  background: rgba(245, 158, 11, 0.12);
}
.accent-red .stat-icon {
  color: var(--accent-red);
  background: rgba(248, 113, 113, 0.12);
}

.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
}

.stat-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-top: 4px;
}
</style>
