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

function open(dialogTitle: string, dialogHint: string, loader: () => Promise<InternalCase[]>) {
  title.value = dialogTitle;
  hint.value = dialogHint;
  cases.value = [];
  page.value = 1;
  visible.value = true;
  loading.value = true;
  loader()
    .then((items) => {
      cases.value = items;
    })
    .catch(() => {
      ElMessage.error("案件明细加载失败,请稍后重试");
    })
    .finally(() => {
      loading.value = false;
    });
}

defineExpose({ open });

function stageLabel(row: InternalCase) {
  const base = STAGE_LABELS[row.stage] ?? row.stage;
  return row.current_step ? `${base} · ${row.current_step}` : base;
}

function caseTitle(row: InternalCase) {
  // 收件阶段案号可能为空或是编码,用当事人做标题更易辨识(与监控页一致)。
  if (row.stage === "receive" || !row.case_no) {
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

function urgencyLabel(row: InternalCase) {
  if (row.urgency === "paused" || row.urgency === "paused_overdue") {
    return row.days_remaining === null ? "已中止" : `中止${row.days_remaining}天`;
  }
  return URGENCY_META[row.urgency as InternalCaseUrgency].label;
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
            :type="URGENCY_META[row.urgency as InternalCaseUrgency].tagType ?? ''"
            :color="URGENCY_META[row.urgency as InternalCaseUrgency].color"
            :style="URGENCY_META[row.urgency as InternalCaseUrgency].color ? 'color: #fff; border: none' : ''"
            effect="light"
          >
            {{ urgencyLabel(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="剩余时间" width="120">
        <template #default="{ row }">{{ remainingLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="结案方式" width="90">
        <template #default="{ row }">{{ row.end_way ?? "-" }}</template>
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
