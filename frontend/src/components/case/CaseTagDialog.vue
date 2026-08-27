<script setup lang="ts">
import { ElMessage } from "element-plus";
import { Plus } from "@element-plus/icons-vue";
import { ref, watch } from "vue";

import * as caseTagApi from "@/api/caseTag";
import type { CaseTag, CaseTagPhrase } from "@/api/caseTag";

const props = defineProps<{
  modelValue: boolean;
  subjectKey: string;
  title: string;
}>();

const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();

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

const tags = ref<CaseTag[]>([]);
const loading = ref(false);
const content = ref("");
const saving = ref(false);

// 快捷内容(所有用户共享,与 InfoWeb 同一张表)
const phrases = ref<CaseTagPhrase[]>([]);
const phraseInputVisible = ref(false);
const newPhrase = ref("");
const phraseSaving = ref(false);

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

function formatTime(iso: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

async function load() {
  loading.value = true;
  try {
    tags.value = await caseTagApi.listCaseTags(props.subjectKey);
  } catch {
    ElMessage.error("记事本加载失败,请稍后重试");
  } finally {
    loading.value = false;
  }
}

async function loadPhrases() {
  try {
    phrases.value = await caseTagApi.listCaseTagPhrases();
  } catch {
    // 快捷内容加载失败不阻断记事本本体
  }
}

// 点击快捷内容填入输入框(可继续编辑,不直接保存)
function applyPhrase(p: CaseTagPhrase) {
  content.value = content.value ? content.value + p.content : p.content;
}

async function addPhrase() {
  const text = newPhrase.value.trim();
  if (!text) return;
  phraseSaving.value = true;
  try {
    await caseTagApi.createCaseTagPhrase(text);
    newPhrase.value = "";
    phraseInputVisible.value = false;
    await loadPhrases();
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    ElMessage.error(status === 409 ? "请先在右上角设置用户名" : "快捷内容保存失败,请稍后重试");
  } finally {
    phraseSaving.value = false;
  }
}

async function removePhrase(p: CaseTagPhrase) {
  try {
    await caseTagApi.deleteCaseTagPhrase(p.id);
    await loadPhrases();
  } catch {
    ElMessage.error("快捷内容删除失败,请稍后重试");
  }
}

async function add() {
  const text = content.value.trim();
  if (!text) return;
  saving.value = true;
  try {
    await caseTagApi.createCaseTag(props.subjectKey, text);
    content.value = "";
    await load();
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    ElMessage.error(status === 409 ? "请先在右上角设置用户名" : "记事保存失败,请稍后重试");
  } finally {
    saving.value = false;
  }
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      content.value = "";
      phraseInputVisible.value = false;
      newPhrase.value = "";
      load();
      loadPhrases();
    }
  },
);
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`记事本 · ${title}`"
    width="640px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="tag-list">
      <el-empty v-if="!loading && tags.length === 0" description="暂无记事" :image-size="60" />
      <div v-for="n in tags" :key="n.id" class="tag-item">
        <div class="tag-meta">
          <span class="tag-time">{{ formatTime(n.created_at) }}</span>
          <el-tag size="small" effect="plain">{{ stageLabel(n.stage) }}</el-tag>
          <span class="tag-sub">{{ n.operator }}</span>
          <span class="tag-sub tag-ip" :title="`设备IP: ${n.client_ip}`">IP {{ n.client_ip || "-" }}</span>
        </div>
        <div class="tag-content">{{ n.content }}</div>
      </div>
    </div>

    <div class="tag-add">
      <div class="phrase-row">
        <el-tag
          v-for="p in phrases"
          :key="p.id"
          class="phrase-chip"
          effect="plain"
          closable
          :disable-transitions="true"
          :title="`点击填入输入框 · 由 ${p.operator || '未知'} 添加`"
          @click="applyPhrase(p)"
          @close="removePhrase(p)"
        >
          {{ p.content }}
        </el-tag>
        <el-button
          class="phrase-add-btn"
          circle
          size="small"
          title="添加快捷内容(所有用户共享)"
          @click="phraseInputVisible = !phraseInputVisible"
        >
          <el-icon><Plus /></el-icon>
        </el-button>
      </div>
      <div v-if="phraseInputVisible" class="phrase-input-row">
        <el-input
          v-model="newPhrase"
          size="small"
          maxlength="100"
          placeholder="输入快捷内容,添加后所有用户共享可点选"
          @keyup.enter="addPhrase"
        />
        <el-button size="small" type="primary" :loading="phraseSaving" :disabled="!newPhrase.trim()" @click="addPhrase">
          添加
        </el-button>
      </div>
      <el-input
        v-model="content"
        type="textarea"
        :rows="3"
        maxlength="2000"
        show-word-limit
        placeholder="输入记事内容…(保存后不可修改)"
      />
      <el-button
        type="primary"
        :loading="saving"
        :disabled="!content.trim()"
        style="margin-top: 8px; align-self: flex-end"
        @click="add"
      >
        添加记事
      </el-button>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tag-list {
  max-height: 320px;
  overflow-y: auto;
  margin-bottom: 12px;
}

.tag-item {
  padding: 10px 12px;
  border-left: 3px solid var(--accent-blue);
  background: #f8fafc;
  border-radius: 0 6px 6px 0;
  margin-bottom: 8px;
}

.tag-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.tag-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.tag-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tag-ip {
  color: var(--el-text-color-placeholder);
}

.tag-content {
  font-size: 14px;
  color: var(--el-text-color-primary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.tag-add {
  display: flex;
  flex-direction: column;
}

.phrase-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.phrase-chip {
  cursor: pointer;
  max-width: 320px;
}

.phrase-chip :deep(.el-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phrase-add-btn {
  flex-shrink: 0;
}

.phrase-input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
</style>
