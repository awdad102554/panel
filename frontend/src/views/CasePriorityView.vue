<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";

import * as internalCaseApi from "@/api/internalCase";
import type { InternalCase, InternalCaseUrgency, InternalStage } from "@/types";

const STAGE_LABELS: Record<InternalStage, string> = {
  reserve: "线上预约",
  receive: "收件审查",
  handle: "立案在办",
  virtual: "预登记",
};

const STAGE_OPTIONS: { label: string; value: InternalStage }[] = (
  Object.entries(STAGE_LABELS) as [InternalStage, string][]
).map(([value, label]) => ({ label, value }));

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

const URGENCY_OPTIONS: { label: string; value: InternalCaseUrgency }[] = (
  Object.entries(URGENCY_META) as [InternalCaseUrgency, (typeof URGENCY_META)[InternalCaseUrgency]][]
).map(([value, meta]) => ({ label: meta.label, value }));

const cases = ref<InternalCase[]>([]);
const loading = ref(false);
const syncing = ref(false);
const stageFilter = ref<InternalStage | undefined>(undefined);
const urgencyFilter = ref<InternalCaseUrgency | undefined>(undefined);
const includeClosed = ref(false);

// 一致性校验(全量只读对账,验证轻量同步是否有遗漏)
const verifying = ref(false);
const verifyDialogVisible = ref(false);
const verifyReport = ref<internalCaseApi.ConsistencyReport | null>(null);

async function handleVerify() {
  verifying.value = true;
  try {
    verifyReport.value = await internalCaseApi.verifyConsistency();
    verifyDialogVisible.value = true;
  } catch {
    ElMessage.error("一致性校验失败,请稍后重试");
  } finally {
    verifying.value = false;
  }
}

// 设置时效对话框
const overrideDialogVisible = ref(false);
const overrideTarget = ref<InternalCase | null>(null);
const overrideDeadline = ref<string>("");
const overrideNote = ref("");
const overrideSaving = ref(false);

function stageLabel(row: InternalCase) {
  const base = STAGE_LABELS[row.stage] ?? row.stage;
  return row.current_step ? `${base} · ${row.current_step}` : base;
}

function caseTitle(row: InternalCase) {
  // 收件阶段案号是编码,不易辨识,改用申请人/被申请人展示。
  if (row.stage === "receive") {
    const applicant = row.applicant ?? "?";
    const respondent = row.respondent ?? "?";
    return `${applicant} → ${respondent}`;
  }
  return row.case_no ?? row.external_case_id;
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

async function refresh() {
  loading.value = true;
  try {
    cases.value = await internalCaseApi.listInternalCases({
      stage: stageFilter.value,
      urgency: urgencyFilter.value,
      includeClosed: includeClosed.value,
    });
  } finally {
    loading.value = false;
  }
}

async function handleSync(full: boolean) {
  syncing.value = true;
  try {
    const result = await internalCaseApi.triggerSync(full);
    if (full) {
      ElMessage.success(
        `全量同步完成:预约 ${result.counts.reserve ?? 0} / 收件 ${result.counts.receive ?? 0} / 在办 ${result.counts.handle ?? 0} / 清理已删除 ${result.counts.deleted ?? 0} 条`,
      );
    } else {
      ElMessage.success(
        `同步完成(轻量):在办 ${result.counts.handle ?? 0} / 收件待审核 ${result.counts.receive ?? 0} / 预约 ${result.counts.reserve ?? 0} / 日期补抓 ${(result.counts.receive_recent ?? 0) + (result.counts.handle_recent ?? 0)} / 补拉 ${result.counts.refetched ?? 0} / 清理已删除 ${result.counts.deleted ?? 0} 条`,
      );
    }
    await refresh();
  } catch {
    ElMessage.error("同步失败,请稍后重试");
  } finally {
    syncing.value = false;
  }
}

function openOverrideDialog(row: InternalCase) {
  overrideTarget.value = row;
  overrideDeadline.value = row.override_deadline ?? "";
  overrideNote.value = "";
  overrideDialogVisible.value = true;
}

async function saveOverride() {
  if (!overrideTarget.value || !overrideDeadline.value) return;
  overrideSaving.value = true;
  try {
    await internalCaseApi.upsertOverride(
      overrideTarget.value.external_case_id,
      overrideDeadline.value,
      overrideNote.value || undefined,
    );
    ElMessage.success("时效覆盖已保存");
    overrideDialogVisible.value = false;
    await refresh();
  } finally {
    overrideSaving.value = false;
  }
}

async function clearOverride(row: InternalCase) {
  await internalCaseApi.deleteOverride(row.external_case_id);
  ElMessage.success("已清除时效覆盖");
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <div class="case-priority">
    <h2>办案进度监控</h2>
    <p class="hint">
      数据来自内网案件系统(后台定时同步),按紧急程度自动排序;已结案/已归档为终态默认隐藏,已退回的预约记录默认隐藏。
    </p>

    <div class="toolbar">
      <el-select
        v-model="stageFilter"
        placeholder="按环节筛选"
        clearable
        style="width: 150px"
        @change="refresh"
      >
        <el-option v-for="opt in STAGE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>

      <el-select
        v-model="urgencyFilter"
        placeholder="按紧急度筛选"
        clearable
        style="width: 150px"
        @change="refresh"
      >
        <el-option v-for="opt in URGENCY_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>

      <el-checkbox v-model="includeClosed" label="显示已结案/已退回" @change="refresh" />

      <el-button :loading="loading" @click="refresh">刷新</el-button>
      <el-button type="primary" :loading="syncing" title="轻量同步:只拉在办/待审核案件,秒级完成" @click="handleSync(false)">
        同步内网数据
      </el-button>
      <el-button :loading="syncing" title="全量同步:翻页拉取全部历史案件(含 2100+ 已结案),约需几分钟,仅作恢复手段" @click="handleSync(true)">
        全量同步
      </el-button>
      <el-button :loading="verifying" title="全量只读对账:比对内网全量数据与本地快照,不写库,用于验证轻量同步是否有遗漏" @click="handleVerify">
        一致性校验
      </el-button>
    </div>

    <el-table v-loading="loading" :data="cases">
      <el-table-column label="案号 / 当事人" width="220">
        <template #default="{ row }">{{ caseTitle(row) }}</template>
      </el-table-column>
      <el-table-column label="环节" width="200">
        <template #default="{ row }">{{ stageLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="剩余时间" width="160">
        <template #default="{ row }">
          {{ remainingLabel(row) }}
          <span
            v-if="row.extension_days > 0 && remainingLabel(row) !== '-'"
            class="extension-mark"
            title="已批准延期,已计入剩余天数"
          >
            (含延期{{ row.extension_days }}天)
          </span>
          <span v-if="row.has_override" class="override-mark" title="人工设置时效">(人工)</span>
        </template>
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
      <el-table-column label="结案方式" width="110">
        <template #default="{ row }">{{ row.end_way ?? "-" }}</template>
      </el-table-column>
      <el-table-column label="进入当前环节" width="130">
        <template #default="{ row }">{{ row.phase_entered_at?.slice(0, 10) ?? "-" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" @click="openOverrideDialog(row)">设置时效</el-button>
          <el-button v-if="row.has_override" size="small" text type="danger" @click="clearOverride(row)">
            清除覆盖
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="overrideDialogVisible" title="设置时效覆盖" width="420px">
      <p class="dialog-hint">
        案件 {{ overrideTarget?.case_no ?? overrideTarget?.external_case_id }}
        :设置截止日期后以此为准,不再走默认阈值。
      </p>
      <el-form label-width="80px">
        <el-form-item label="截止日期">
          <el-date-picker
            v-model="overrideDeadline"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择截止日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="overrideNote" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="overrideDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="overrideSaving" :disabled="!overrideDeadline" @click="saveOverride">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="verifyDialogVisible" title="一致性校验结果" width="860px">
      <template v-if="verifyReport">
        <p class="dialog-hint">
          共比对内网全量 {{ verifyReport.checked }} 件;快照多出
          {{ verifyReport.only_in_snapshot }} 件(内网全量未返回,预约历史等,通常无害)。
        </p>
        <el-alert
          v-if="verifyReport.missing_total === 0 && verifyReport.mismatch_total === 0"
          type="success"
          :closable="false"
          title="轻量同步无遗漏:快照与内网全量数据一致"
          style="margin-bottom: 12px"
        />
        <template v-if="verifyReport.missing_total > 0">
          <h4>内网有、快照缺失({{ verifyReport.missing_total }} 件,轻量同步漏同步)</h4>
          <el-table :data="verifyReport.missing_in_snapshot" size="small" max-height="240">
            <el-table-column label="案号" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">{{ row.case_no ?? "-" }}</template>
            </el-table-column>
            <el-table-column prop="stage" label="环节" width="100" />
            <el-table-column label="子状态" width="140">
              <template #default="{ row }">{{ row.current_step ?? "-" }}</template>
            </el-table-column>
          </el-table>
        </template>
        <template v-if="verifyReport.mismatch_total > 0">
          <h4>字段不一致({{ verifyReport.mismatch_total }} 处,轻量同步没跟上)</h4>
          <el-table :data="verifyReport.field_mismatches" size="small" max-height="240">
            <el-table-column label="案号" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.case_no ?? "-" }}</template>
            </el-table-column>
            <el-table-column prop="field" label="字段" width="120" />
            <el-table-column label="快照值" width="140">
              <template #default="{ row }">{{ row.snapshot ?? "-" }}</template>
            </el-table-column>
            <el-table-column label="内网值" width="140">
              <template #default="{ row }">{{ row.intranet ?? "-" }}</template>
            </el-table-column>
          </el-table>
        </template>
        <p v-if="verifyReport.missing_total > 0 || verifyReport.mismatch_total > 0" class="dialog-hint" style="margin-top: 12px">
          本次差异明细已保存到校验报告(历史记录见 GET /internal-cases/verify-reports),供排查轻量同步问题;数据本身不做自动修正。
        </p>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.case-priority h2 {
  margin: 0 0 4px;
}

.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0 0 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.override-mark {
  color: var(--el-color-warning);
  font-size: 12px;
}

.extension-mark {
  color: var(--el-color-info);
  font-size: 12px;
}

.dialog-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0 0 12px;
}
</style>
