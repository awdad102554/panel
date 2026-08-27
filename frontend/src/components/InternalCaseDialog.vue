<script setup lang="ts">
import { ElMessage } from "element-plus";
import { computed, ref } from "vue";

import type { InternalCase, InternalCaseUrgency, InternalStage } from "@/types";

// 内网案件明细弹窗:总览卡片、总览图表、统计分析页共用。
// 父组件通过 ref 调 open(title, hint, loader) 打开,loader 返回案件列表。

const STAGE_LABELS: Record<InternalStage, string> = {
  reserve: "线上预约",
  receive: "收件审查",
  handle: "立案在办",
  virtual: "预登记",
};

const URGENCY_META: Record<
  InternalCaseUrgency,
  { label: string; tagType?: "danger" | "warning" | "success" | "info"; color?: string }
> = {
  overdue: { label: "已超期", tagType: "danger" },
  urgent: { label: "紧急", color: "#f97316" },
  soon: { label: "临近", tagType: "warning" },
  normal: { label: "正常", tagType: "success" },
  paused: { label: "已中止", tagType: "info" },
  paused_overdue: { label: "中止过久", color: "#8e44ad" },
  closed: { label: "已结案", tagType: "info" },
  rejected: { label: "已退回", tagType: "info" },
};

const visible = ref(false);
const loading = ref(false);
const title = ref("");
const hint = ref("");
const cases = ref<InternalCase[]>([]);
const page = ref(1);
const PAGE_SIZE = 20;

const pagedCases = computed(() => cases.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE));

// 案前调解案件(有 state_entered_at)的表格列与其它卡片不同:剩余时间→进入状态时间、
// 结案方式→进入时长,表头按数据切换。
const hasPreMediation = computed(() => cases.value.some((c) => c.state_entered_at));
const timeColumnLabel = computed(() => (hasPreMediation.value ? "进入状态时间" : "剩余时间"));
const endWayColumnLabel = computed(() => (hasPreMediation.value ? "进入时长" : "结案方式"));

// 快速连点两个卡片时,旧 loader 的响应不得覆盖新标题下的列表。
let openSeq = 0;

function open(dialogTitle: string, dialogHint: string, loader: () => Promise<InternalCase[]>) {
  const seq = ++openSeq;
  title.value = dialogTitle;
  hint.value = dialogHint;
  cases.value = [];
  page.value = 1;
  visible.value = true;
  loading.value = true;
  loader()
    .then((items) => {
      if (seq !== openSeq) return;
      cases.value = items;
    })
    .catch(() => {
      if (seq !== openSeq) return;
      ElMessage.error("案件明细加载失败,请稍后重试");
    })
    .finally(() => {
      if (seq === openSeq) loading.value = false;
    });
}

defineExpose({ open });

function stageLabel(row: InternalCase) {
  const base = STAGE_LABELS[row.stage] ?? row.stage;
  return row.current_step ? `${base} · ${row.current_step}` : base;
}

// 案前调解(收件审核通过)已生成正式收件号,其余收件案号可能是编码/为空。
const PRE_MEDIATION_STEP = "案前调解";

function caseTitle(row: InternalCase) {
  // 收件阶段待审核案号可能为空或是编码,用当事人做标题更易辨识;案前调解已有收件号,改显收件号。
  if ((row.stage === "receive" && row.current_step !== PRE_MEDIATION_STEP) || !row.case_no) {
    return partiesLabel(row);
  }
  return row.case_no;
}

function partiesLabel(row: InternalCase) {
  return `${row.applicant ?? "?"} → ${row.respondent ?? "?"}`;
}

function remainingLabel(row: InternalCase) {
  // 中止案件没有"剩余审理时间"口径(中止天数已在紧急度列显示),剩余时间列显示 -。
  if (row.urgency === "paused" || row.urgency === "paused_overdue") return "-";
  if (row.days_remaining === null) return "-";
  if (row.days_remaining < 0) return `已超期 ${-row.days_remaining} 天`;
  return `剩 ${row.days_remaining} 天`;
}

// 案前调解没有"剩余/超期天数"口径,该列改显"进入案前调解的时间"(review_at)。
function stateEnteredLabel(row: InternalCase) {
  const s = row.state_entered_at ?? "";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : s;
}

function timeCell(row: InternalCase) {
  return row.state_entered_at ? stateEnteredLabel(row) : remainingLabel(row);
}

// 案前调解:进入调解已过自然日数(按本地自然日,与后端 CST 口径一致)。
function stateEnteredDays(row: InternalCase) {
  const s = row.state_entered_at ?? "";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const entered = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today.getTime() - entered.getTime()) / 86400000);
}

function endWayCell(row: InternalCase) {
  const days = stateEnteredDays(row);
  return days === null ? (row.end_way ?? "-") : `已进入 ${days} 天`;
}

function urgencyLabel(row: InternalCase) {
  if (row.urgency === "paused" || row.urgency === "paused_overdue") {
    return row.days_remaining === null ? "已中止" : `中止${row.days_remaining}天`;
  }
  return URGENCY_META[row.urgency as InternalCaseUrgency]?.label ?? row.urgency;
}
</script>

<template>
  <el-dialog v-model="visible" :title="title" width="1120px">
    <p v-if="hint" class="dialog-hint">{{ hint }}</p>
    <el-table v-loading="loading" :data="pagedCases" empty-text="当前没有符合条件的案件">
      <el-table-column label="案号" width="250" show-overflow-tooltip>
        <template #default="{ row }">{{ caseTitle(row) }}</template>
      </el-table-column>
      <el-table-column label="当事人" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">{{ partiesLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="环节 · 状态" width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ stageLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="紧急度" width="120">
        <template #default="{ row }">
          <el-tag
            :type="URGENCY_META[row.urgency as InternalCaseUrgency]?.tagType ?? ''"
            :color="URGENCY_META[row.urgency as InternalCaseUrgency]?.color"
            :style="URGENCY_META[row.urgency as InternalCaseUrgency]?.color ? 'color: #fff; border: none' : ''"
            effect="light"
          >
            {{ urgencyLabel(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="timeColumnLabel" width="130">
        <template #default="{ row }">{{ timeCell(row) }}</template>
      </el-table-column>
      <el-table-column :label="endWayColumnLabel" width="120">
        <template #default="{ row }">{{ endWayCell(row) }}</template>
      </el-table-column>
    </el-table>
    <div class="dialog-pagination">
      <el-pagination
        v-model:current-page="page"
        :page-size="PAGE_SIZE"
        :total="cases.length"
        layout="total, prev, pager, next"
        hide-on-single-page
      />
    </div>
  </el-dialog>
</template>

<style scoped>
.dialog-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0 0 12px;
}

.dialog-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
