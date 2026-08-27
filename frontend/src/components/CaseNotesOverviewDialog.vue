<script setup lang="ts">
/** 记事本总览弹窗:近 N 天有记事的案件,按最近记事时间倒序。
 * 案号/当事人取案件当前口径(收件转立案后显示立案案号,由后端解析)。
 * 天数默认取"时限设置"的 tag_overview_days(默认 30),弹窗内可临时切换。 */
import { ElMessage } from "element-plus";
import { computed, ref } from "vue";

import { getCaseNotesOverview, type CaseNoteOverviewItem } from "@/api/caseTag";
import { getTimeLimits } from "@/api/settings";
import CaseTagDialog from "@/components/case/CaseTagDialog.vue";

const STAGE_LABELS: Record<string, string> = {
  reserve: "线上预约",
  receive: "收件审查",
  pre_mediation: "收件审查 · 案前调解",
  handle: "立案在办",
  paused: "立案在办 · 审理中止",
  mediation: "立案在办 · 组织调解",
  deciding: "立案在办 · 仲裁裁决中",
  pending_hearing: "立案在办 · 待开庭安排",
  pending_trial: "立案在办 · 待开庭审理",
  in_progress: "立案在办 · 审理事项进行中",
  closed: "已结案",
  archived: "已归档",
  virtual: "预登记",
};

const visible = ref(false);
const loading = ref(false);
const items = ref<CaseNoteOverviewItem[]>([]);
const days = ref(30);
const defaultDays = ref(30);

// 预设范围 + 设置里的默认值(不在预设时补进选项)
const dayOptions = computed(() => {
  const presets = [7, 30, 90, 365];
  const all = presets.includes(defaultDays.value) ? presets : [...presets, defaultDays.value];
  return [...new Set(all)].sort((a, b) => a - b);
});

const tagDialogVisible = ref(false);
const tagSubjectKey = ref("");
const tagTitle = ref("");

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage ?? "";
}

function caseTitle(item: CaseNoteOverviewItem): string {
  if (!item.exists) return "案件已删除/未同步";
  return item.case_no || `${item.applicant ?? "?"} → ${item.respondent ?? "?"}`;
}

function formatTime(iso: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function load() {
  loading.value = true;
  try {
    const res = await getCaseNotesOverview(days.value);
    items.value = res.items;
  } catch {
    ElMessage.error("记事本总览加载失败,请稍后重试");
  } finally {
    loading.value = false;
  }
}

function onDaysChange() {
  load();
}

function openCase(item: CaseNoteOverviewItem) {
  tagSubjectKey.value = item.subject_key;
  tagTitle.value = caseTitle(item);
  tagDialogVisible.value = true;
}

async function open() {
  visible.value = true;
  // 默认范围取"时限设置"的记事本总览天数;读失败就用 30 天
  try {
    const limits = await getTimeLimits();
    const item = limits.find((l) => l.key === "tag_overview_days");
    defaultDays.value = item?.value ?? 30;
  } catch {
    defaultDays.value = 30;
  }
  days.value = defaultDays.value;
  await load();
}

defineExpose({ open });
</script>

<template>
  <el-dialog v-model="visible" title="记事本总览" width="900px" top="4vh">
    <div class="overview-toolbar">
      <span class="range-label">统计范围:</span>
      <el-radio-group v-model="days" @change="onDaysChange">
        <el-radio-button v-for="d in dayOptions" :key="d" :value="d">近{{ d }}天</el-radio-button>
      </el-radio-group>
      <span class="total-text">共 {{ items.length }} 个案件有记事</span>
    </div>
    <p class="dialog-hint">默认范围为「设置 → 时限设置 → 记事本总览天数」;案号取案件当前口径(收件转立案后显示立案案号)。点击案件查看完整记事。</p>

    <div v-loading="loading" class="notes-list">
      <el-empty v-if="!loading && items.length === 0" :description="`近 ${days} 天暂无案件记事`" />
      <div
        v-for="item in items"
        :key="item.subject_key"
        class="note-case-card"
        :class="{ 'case-gone': !item.exists }"
        @click="openCase(item)"
      >
        <div class="card-head">
          <span class="case-no">{{ caseTitle(item) }}</span>
          <el-tag v-if="item.exists && item.stage" size="small" effect="plain" class="stage-tag">
            {{ stageLabel(item.stage) }}
          </el-tag>
          <span class="tag-count">{{ item.tag_count }} 条记事</span>
        </div>
        <div v-if="item.exists && (item.applicant || item.respondent)" class="card-parties">
          {{ item.applicant ?? "?" }} <span class="arrow">→</span> {{ item.respondent ?? "?" }}
        </div>
        <div class="card-last">
          <span class="last-content">{{ item.last_content }}</span>
          <span class="last-meta">{{ item.last_operator }} · {{ formatTime(item.last_at) }}</span>
        </div>
      </div>
    </div>

    <CaseTagDialog v-model="tagDialogVisible" :subject-key="tagSubjectKey" :title="tagTitle" />
  </el-dialog>
</template>

<style scoped>
.overview-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.range-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.total-text {
  margin-left: auto;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.dialog-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 0 0 12px;
}

.notes-list {
  max-height: 62vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.note-case-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

.note-case-card:hover {
  border-color: var(--accent-blue);
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.12);
}

.note-case-card.case-gone {
  opacity: 0.65;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.case-no {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.stage-tag {
  flex-shrink: 0;
}

.tag-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--accent-blue);
  background: rgba(59, 130, 246, 0.08);
  border-radius: 10px;
  padding: 1px 8px;
  flex-shrink: 0;
}

.card-parties {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.card-parties .arrow {
  color: var(--el-text-color-secondary);
  margin: 0 2px;
}

.card-last {
  margin-top: 6px;
  background: #f8fafc;
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.last-content {
  font-size: 13px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  flex: 1;
  min-width: 0;
}

.last-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
</style>
