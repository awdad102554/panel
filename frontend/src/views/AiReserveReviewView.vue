<script setup lang="ts">
import { Check, Close, Document, View, WarningFilled } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";

import * as reserveApi from "@/api/reserveReview";
import ReserveDetailTree from "@/components/ReserveDetailTree.vue";
import type {
  PendingReserve,
  ReserveCaseDetail,
  ReserveReviewResult,
  ReviewCheck,
  ReviewConclusion,
  ReviewStepEvent,
} from "@/types";

interface StepState {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "error";
  detail: string;
}

const BASE_STEPS: { key: string; label: string }[] = [
  { key: "fetch_detail", label: "抓取预约详情" },
  { key: "build_prompt", label: "组装审查提示词" },
  { key: "call_llm", label: "调用 AI 模型" },
  { key: "parse", label: "解析审查结论" },
];

const pending = ref<PendingReserve[]>([]);
const loadingList = ref(false);
const selectedId = ref<string | null>(null);
const reviewing = ref(false);
const steps = ref<StepState[]>([]);
const result = ref<ReserveReviewResult | null>(null);
const showSnapshot = ref(false);
const detailVisible = ref(false);
const detailLoading = ref(false);
const caseDetail = ref<ReserveCaseDetail | null>(null);

const selectedCase = computed(
  () => pending.value.find((p) => p.external_case_id === selectedId.value) ?? null,
);

const CONCLUSION_META: Record<
  ReviewConclusion,
  { label: string; tag: "success" | "warning" | "danger" | "info"; color: string }
> = {
  通过: { label: "通过", tag: "success", color: "var(--accent-green)" },
  补正: { label: "补正", tag: "warning", color: "var(--accent-amber)" },
  驳回: { label: "驳回", tag: "danger", color: "var(--accent-red)" },
  审查失败: { label: "审查失败", tag: "info", color: "var(--el-text-color-secondary)" },
};

const conclusionMeta = computed(() =>
  result.value ? CONCLUSION_META[result.value.conclusion] : null,
);

function resetSteps() {
  steps.value = BASE_STEPS.map((s) => ({ ...s, status: "pending", detail: "" }));
}

function applyEvent(ev: ReviewStepEvent) {
  if (ev.type !== "step") return;
  const idx = steps.value.findIndex((s) => s.key === ev.key);
  if (idx === -1) return;
  const st = steps.value[idx];
  st.status = ev.status ?? "running";
  if (ev.label) st.label = ev.label;
  if (ev.detail) st.detail = ev.detail;
}

async function loadPending() {
  loadingList.value = true;
  try {
    pending.value = await reserveApi.listPendingReserve();
    // 默认选中第一件并展示其最近一次审查内容,方便直接看到审核结果。
    if (pending.value.length && !selectedId.value) {
      const first = pending.value[0];
      selectedId.value = first.external_case_id;
      await loadLatestReview(first);
    }
  } catch {
    ElMessage.error("待审核案件列表加载失败,请稍后重试");
  } finally {
    loadingList.value = false;
  }
}

async function loadLatestReview(row: PendingReserve) {
  // 展示一件案件的最近一次审查留痕(非实时流式)。
  showSnapshot.value = false;
  const id = row.external_case_id;
  if (!row.has_review) {
    result.value = null;
    resetSteps();
    return;
  }
  try {
    const r = await reserveApi.getLatestReview(id);
    if (selectedId.value !== id) return; // 已切换到别的案件,丢弃过期结果
    result.value = r;
    // 已有留痕:流程步骤整体标记为已完成。
    steps.value = BASE_STEPS.map((s) => ({ ...s, status: "done" as const, detail: "" }));
  } catch {
    if (selectedId.value !== id) return;
    result.value = null;
    resetSteps();
  }
}

function selectCase(row: PendingReserve) {
  if (reviewing.value) return;
  selectedId.value = row.external_case_id;
  loadLatestReview(row);
}

async function startReview(row: PendingReserve) {
  if (reviewing.value) return;
  selectedId.value = row.external_case_id;
  reviewing.value = true;
  result.value = null;
  showSnapshot.value = false;
  resetSteps();
  try {
    const final = await reserveApi.reviewReserve(row.external_case_id, applyEvent);
    result.value = final;
    // 审查完成即标记该案件已有结果,按钮即时翻转为「重新审核」,无需刷新列表。
    const idx = pending.value.findIndex((p) => p.external_case_id === row.external_case_id);
    if (idx !== -1) {
      pending.value[idx] = {
        ...pending.value[idx],
        has_review: true,
        latest_conclusion: final.conclusion,
      };
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "审查失败,请稍后重试");
  } finally {
    reviewing.value = false;
  }
}

function checkStatus(passed: ReviewCheck["passed"]): "pass" | "fail" | "warn" {
  if (passed === true) return "pass";
  if (passed === false) return "fail";
  return "warn";
}

async function openDetail() {
  if (!selectedId.value) return;
  detailVisible.value = true;
  detailLoading.value = true;
  caseDetail.value = null;
  try {
    caseDetail.value = await reserveApi.getReserveDetail(selectedId.value);
  } catch {
    ElMessage.error("案件信息加载失败,请稍后重试");
  } finally {
    detailLoading.value = false;
  }
}

function timeLimitType(t: string): "danger" | "warning" | "info" {
  if (t.startsWith("超期")) return "danger";
  if (t.endsWith("天")) return "warning";
  return "info";
}

function conclusionTag(c: ReviewConclusion | null): "success" | "warning" | "danger" | "info" {
  return c ? CONCLUSION_META[c].tag : "info";
}

onMounted(loadPending);
</script>

<template>
  <div class="ai-review">
    <div class="page-header">
      <h2>AI 预约审查</h2>
      <p class="page-subtitle">
        对线上预约待审核案件自动审查，产出「通过 / 补正 / 驳回」初筛建议；结论仅供工作人员参考，不写回内网审批。
      </p>
    </div>

    <div class="review-layout">
      <!-- 左栏：待审核案件列表 -->
      <div class="left-panel">
        <div class="panel-head">
          <span class="panel-title">待审核预约案件</span>
          <el-tag type="primary" effect="dark" size="small">{{ pending.length }}</el-tag>
        </div>
        <div v-loading="loadingList" class="case-list">
          <div v-if="!loadingList && pending.length === 0" class="empty-hint">
            暂无待审核的线上预约案件
          </div>
          <div
            v-for="row in pending"
            :key="row.external_case_id"
            class="case-item"
            :class="{ active: row.external_case_id === selectedId }"
            @click="selectCase(row)"
          >
            <div class="case-main">
              <div class="case-parties">
                <span class="party">{{ row.applicant || "?" }}</span>
                <span class="arrow">→</span>
                <span class="party">{{ row.respondent || "?" }}</span>
              </div>
              <div class="case-meta">
                <el-tag v-if="row.case_reason" size="small" type="info">{{ row.case_reason }}</el-tag>
                <el-tag v-if="row.latest_conclusion" size="small" :type="conclusionTag(row.latest_conclusion)">
                  {{ row.latest_conclusion }}
                </el-tag>
                <span class="meta-text">{{ row.reserve_at?.slice(0, 10) ?? "-" }}</span>
                <el-tag v-if="row.reserve_time_limit" size="small" :type="timeLimitType(row.reserve_time_limit)">
                  {{ row.reserve_time_limit }}
                </el-tag>
              </div>
            </div>
            <el-button
              type="primary"
              size="small"
              :loading="reviewing && row.external_case_id === selectedId"
              @click.stop="startReview(row)"
            >
              {{ row.has_review ? "重新审核" : "审查" }}
            </el-button>
          </div>
        </div>
      </div>

      <!-- 右栏：审查工作区 -->
      <div class="right-panel">
        <div v-if="!selectedCase" class="workspace-empty">
          <el-icon class="empty-icon"><Document /></el-icon>
          <p>从左侧选择一件待审核案件开始审查</p>
        </div>

        <template v-else>
          <div class="workspace-head">
            <div class="workspace-head-main">
              <div class="parties">
                <span class="party">{{ selectedCase.applicant || "?" }}</span>
                <span class="arrow">→</span>
                <span class="party">{{ selectedCase.respondent || "?" }}</span>
              </div>
              <div class="head-meta">
                <el-tag v-if="selectedCase.case_reason" size="small" type="info">{{ selectedCase.case_reason }}</el-tag>
                <span class="meta-text">案号 {{ selectedCase.external_case_id }}</span>
              </div>
            </div>
            <el-button type="primary" plain size="small" :loading="detailLoading" @click="openDetail">
              <el-icon><View /></el-icon>
              <span>查看案件</span>
            </el-button>
          </div>

          <!-- 动态流程时间线 -->
          <div class="steps-card">
            <div class="card-title">
              审查流程
              <span v-if="reviewing" class="pulse-badge">AI 审查中…</span>
            </div>
            <div class="steps">
              <div v-for="s in steps" :key="s.key" class="step" :class="s.status">
                <div class="step-indicator" :class="s.status">
                  <el-icon v-if="s.status === 'done'"><Check /></el-icon>
                  <el-icon v-else-if="s.status === 'error'"><Close /></el-icon>
                  <span v-else-if="s.status === 'running'" class="spinner" />
                  <span v-else class="dot" />
                </div>
                <div class="step-body">
                  <div class="step-label">{{ s.label }}</div>
                  <div v-if="s.detail" class="step-detail">{{ s.detail }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 结论卡片 -->
          <div v-if="result" class="result-card">
            <div class="result-head">
              <div class="conclusion" :style="{ color: conclusionMeta?.color, borderColor: conclusionMeta?.color }">
                <span class="conclusion-badge">{{ conclusionMeta?.label }}</span>
              </div>
              <div class="result-model">
                <span class="model-label">模型</span>
                <span class="model-name">{{ result.model_name || "-" }}</span>
              </div>
            </div>

            <div v-if="result.checks.length" class="result-block">
              <div class="block-title">逐项审查</div>
              <div class="checks">
                <div v-for="c in result.checks" :key="c.rule_id" class="check-row" :class="checkStatus(c.passed)">
                  <div class="check-head">
                    <el-icon v-if="c.passed === true" class="check-icon pass"><Check /></el-icon>
                    <el-icon v-else-if="c.passed === false" class="check-icon fail"><Close /></el-icon>
                    <el-icon v-else class="check-icon warn"><WarningFilled /></el-icon>
                    <span class="check-rule">{{ c.rule_name }}</span>
                    <span class="check-status" :class="checkStatus(c.passed)">
                      {{ c.passed === true ? "通过" : c.passed === false ? "不通过" : "需人工核验" }}
                    </span>
                  </div>
                  <div v-if="c.note" class="check-note">{{ c.note }}</div>
                </div>
              </div>
            </div>

            <div class="result-reason">{{ result.reason }}</div>

            <div v-if="result.issues.length" class="result-block">
              <div class="block-title">审查问题点</div>
              <ul class="issue-list">
                <li v-for="(it, i) in result.issues" :key="i">{{ it }}</li>
              </ul>
            </div>

            <div v-if="result.missing_materials.length" class="result-block">
              <div class="block-title">需补充材料</div>
              <ul class="material-list">
                <li v-for="(m, i) in result.missing_materials" :key="i">{{ m }}</li>
              </ul>
            </div>

            <div v-if="result.rule_refs.length" class="result-block">
              <div class="block-title">命中审查规则</div>
              <div class="rule-refs">
                <el-tag v-for="(r, i) in result.rule_refs" :key="i" size="small" effect="plain">
                  规则 {{ r }}
                </el-tag>
              </div>
            </div>

            <div class="result-footer">
              <span>{{ result.created_at?.slice(0, 19).replace("T", " ") }}</span>
              <span class="divider">·</span>
              <span>审查人 {{ result.created_by }}</span>
            </div>
          </div>

          <!-- 可折叠：案件摘要 -->
          <div v-if="result" class="snapshot-card">
            <div class="snapshot-toggle" @click="showSnapshot = !showSnapshot">
              <el-icon><View /></el-icon>
              <span>{{ showSnapshot ? "收起" : "查看" }}送入模型的案件摘要</span>
            </div>
            <pre v-if="showSnapshot" class="snapshot-pre">{{ JSON.stringify(result.case_snapshot, null, 2) }}</pre>
          </div>
        </template>
      </div>
    </div>

    <!-- 查看案件弹窗 -->
    <el-dialog v-model="detailVisible" title="案件信息" width="760px" top="6vh">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="caseDetail">
          <div class="detail-head">
            <div class="detail-parties">
              <span class="detail-party">{{ caseDetail.applicant || "?" }}</span>
              <span class="detail-arrow">→</span>
              <span class="detail-party">{{ caseDetail.respondent || "?" }}</span>
            </div>
            <div class="detail-meta">
              <el-tag v-if="caseDetail.case_reason" size="small" type="info">{{ caseDetail.case_reason }}</el-tag>
              <span class="detail-meta-text">案号 {{ caseDetail.external_case_id }}</span>
              <span v-if="caseDetail.reserve_at" class="detail-meta-text">申请 {{ caseDetail.reserve_at }}</span>
            </div>
          </div>
          <ReserveDetailTree :data="caseDetail.detail" />
        </template>
        <div v-else-if="!detailLoading" class="detail-empty">暂无案件信息</div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.ai-review {
  padding: 4px;
}

.page-header {
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0 0 4px;
}

.page-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0;
}

.review-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 16px;
  align-items: start;
}

.left-panel,
.right-panel {
  background: #fff;
  border-radius: var(--radius-lg);
  box-shadow: 0 2px 12px rgba(15, 31, 74, 0.06);
  border: 1px solid rgba(15, 31, 74, 0.04);
  min-height: 420px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(15, 31, 74, 0.06);
}

.panel-title {
  font-weight: 700;
  font-size: 14px;
}

.case-list {
  padding: 8px;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}

.empty-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}

.case-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.2s ease, box-shadow 0.2s ease;
  border: 1px solid transparent;
}

.case-item:hover {
  background: #f5f7fb;
}

.case-item.active {
  background: rgba(34, 211, 238, 0.08);
  border-color: var(--accent-cyan);
}

.case-main {
  min-width: 0;
  flex: 1;
}

.case-parties,
.parties {
  font-size: 14px;
  line-height: 1.4;
}

.party {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.arrow {
  color: var(--accent-cyan);
  margin: 0 6px;
  font-weight: 700;
}

.case-meta,
.head-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.meta-text {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

/* 右栏工作区 */
.workspace-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 420px;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  font-size: 42px;
  margin-bottom: 12px;
  color: rgba(34, 211, 238, 0.5);
}

.workspace-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(15, 31, 74, 0.06);
}

.workspace-head-main {
  min-width: 0;
}

.workspace-head .parties {
  font-size: 16px;
}

.steps-card,
.result-card,
.snapshot-card {
  margin: 12px 16px;
  padding: 14px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(15, 31, 74, 0.06);
  background: #fbfcfe;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 14px;
}

.pulse-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-cyan);
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.step-indicator {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 14px;
}

.step-indicator.pending {
  border: 2px solid rgba(15, 31, 74, 0.15);
  color: transparent;
}

.step-indicator.done {
  background: var(--accent-green);
  color: #fff;
}

.step-indicator.error {
  background: var(--accent-red);
  color: #fff;
}

.step-indicator.running {
  background: rgba(34, 211, 238, 0.12);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(15, 31, 74, 0.15);
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(34, 211, 238, 0.3);
  border-top-color: var(--accent-cyan);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.step-body {
  min-width: 0;
}

.step-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 24px;
}

.step.running .step-label {
  color: var(--accent-cyan);
}

.step-detail {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

/* 结论卡片 */
.result-card {
  background: #fff;
  border-top: 3px solid transparent;
}

.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.conclusion {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: 2px;
  border-bottom: 2px solid;
  padding-bottom: 2px;
}

.result-model {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.model-label {
  margin-right: 6px;
}

.model-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.result-reason {
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
  border-radius: var(--radius-md);
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
}

.result-block {
  margin-top: 14px;
}

.block-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.issue-list,
.material-list {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.8;
}

.rule-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.checks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.check-row {
  border: 1px solid rgba(15, 31, 74, 0.08);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  background: #fff;
}

.check-row.fail {
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(248, 113, 113, 0.04);
}

.check-row.warn {
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.04);
}

.check-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.check-icon {
  font-size: 16px;
}

.check-icon.pass {
  color: var(--accent-green);
}

.check-icon.fail {
  color: var(--accent-red);
}

.check-icon.warn {
  color: var(--accent-amber);
}

.check-rule {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.check-status {
  margin-left: auto;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
}

.check-status.pass {
  color: var(--accent-green);
  background: rgba(52, 211, 153, 0.12);
}

.check-status.fail {
  color: var(--accent-red);
  background: rgba(248, 113, 113, 0.12);
}

.check-status.warn {
  color: var(--accent-amber);
  background: rgba(245, 158, 11, 0.12);
}

.check-note {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

.result-footer {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid rgba(15, 31, 74, 0.06);
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.divider {
  color: rgba(15, 31, 74, 0.2);
}

.snapshot-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--accent-blue);
  font-weight: 600;
}

.snapshot-pre {
  margin-top: 10px;
  padding: 12px;
  background: #f8fafc;
  border-radius: var(--radius-md);
  font-size: 12px;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

<style>
/* 「查看案件」弹窗内容(el-dialog 渲染到 body,需全局样式) */
.detail-body {
  max-height: 70vh;
  overflow-y: auto;
}

.detail-head {
  padding: 4px 2px 14px;
  border-bottom: 1px solid rgba(15, 31, 74, 0.06);
  margin-bottom: 14px;
}

.detail-parties {
  font-size: 16px;
  line-height: 1.4;
}

.detail-party {
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.detail-arrow {
  color: var(--accent-cyan);
  margin: 0 8px;
  font-weight: 700;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.detail-meta-text {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.detail-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}
</style>
