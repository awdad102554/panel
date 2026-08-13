<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, ref, watch } from "vue";

import * as api from "@/api/virtualCases";
import type { CatalogItem, SubmitDraft, SubmitSpec } from "@/api/virtualCases";
import {
  buildCascaderOptions,
  catalogItemOf as catalogItemOfCatalog,
  isMultiTemplate,
  needsDatesTemplate,
  needsOtherTemplate,
} from "@/utils/requestCatalog";
import { composeCaseFacts } from "@/utils/factCompose";

const props = defineProps<{
  visible: boolean;
  caseId: string;
  receiptNumber: string;
}>();
const emit = defineEmits<{
  "update:visible": [value: boolean];
  submitted: [];
}>();

const loading = ref(false);
const submitting = ref(false);
const draft = ref<SubmitDraft | null>(null);

// 表单状态(草稿加载后填充,用户确认/修改)
const form = ref({
  apply_at: "",
  town_id: 0,
  case_reason: "",
  is_sign_labor_contract: 1,
  is_pay_social_insurance: 1,
  is_easy: 1,
  company_nature: "私营企业",
  id_type: "居民身份证（户口簿）",
  is_migrant_worker: 0,
  is_three_woman_worker: 0,
  fact_content: "",
});
const mainCauseSelected = ref<string[]>([]);
const mainCauseOther = ref("");
interface RequestRow {
  text: string;
  path: number[]; // cascader 绑定
  option: string | null;
  object: number | null;
  items: { name: string; object: number | null }[]; // 多选项($str 模板)明细
  start_at: string | null; // 期间起(模板含"开始日期"时显示)
  end_at: string | null; // 期间止
  other: string; // $other 模板(其他类请求)的具体内容
  applicant_index: number; // 归属第几个申请人(多申请人时后端给 intro 加"申请人N")
  applicant_name: string; // 归属申请人姓名(卡片展示)
  intro: string | null;
  // intro 为草稿自动预填(用户在预登记改过的文本):改类型/金额/期间时若未手动
  // 编辑过 intro,要清掉让模板按新值重生成,否则旧表述随新数据进内网。
  introAuto: boolean;
  guessed: boolean;
}
const requestRows = ref<RequestRow[]>([]);

const previewVisible = ref(false);
const previewJson = ref("");

// 草稿加载竞态守卫:打开 A 案后立即取消再打开 B 案时,A 的慢响应不得覆盖 B 的表单,
// A 的失败回调也不得误关 B 的对话框。
let loadSeq = 0;

watch(
  // immediate: 父组件 v-if=submitTarget 首次挂载时 visible 已为 true,
  // 没有 immediate 首次打开永远不触发加载,对话框一片空白(关掉重开才好)。
  [() => props.visible, () => props.caseId],
  async ([v]) => {
    if (!v) return;
    const seq = ++loadSeq;
    const caseId = props.caseId;
    loading.value = true;
    draft.value = null;
    try {
      const d = await api.fetchSubmitDraft(caseId);
      if (seq !== loadSeq || !props.visible || props.caseId !== caseId) return;
      draft.value = d;
      form.value = {
        apply_at: d.defaults.apply_at,
        town_id: d.defaults.town_id,
        case_reason: d.defaults.case_reason,
        is_sign_labor_contract: d.defaults.is_sign_labor_contract,
        is_pay_social_insurance: d.defaults.is_pay_social_insurance,
        is_easy: d.defaults.is_easy,
        company_nature: d.defaults.company_nature,
        id_type: d.defaults.id_type,
        is_migrant_worker: d.defaults.is_migrant_worker,
        is_three_woman_worker: d.defaults.is_three_woman_worker,
        fact_content: d.fact_content,
      };
      // 主因预填第一申请人存的值(预设进多选,自定义进"其他"输入框)
      const storedCauses = d.fact_parties[0]?.main_causes ?? [];
      mainCauseSelected.value = storedCauses.filter((c) => d.meta.main_cause_presets.includes(c));
      mainCauseOther.value = storedCauses
        .filter((c) => !d.meta.main_cause_presets.includes(c))
        .join("；");
      requestRows.value = d.requests.map((r) => ({
        text: r.text,
        path: r.path_ids ? [...r.path_ids] : [],
        option: r.option,
        object: r.object,
        // 结构化录入的请求带明细/期间,直接预填(此前丢成空,多选项请求还得重选一遍)。
        items: (r.items ?? []).map((i) => ({ name: i.name, object: i.object })),
        start_at: r.start_at ?? null,
        end_at: r.end_at ?? null,
        other: r.other ?? "",
        applicant_index: r.applicant_index ?? 0,
        applicant_name: r.applicant_name ?? "",
        intro: r.intro,
        introAuto: !!r.intro,
        guessed: r.guessed,
      }));
    } catch (err: unknown) {
      if (seq !== loadSeq || !props.visible || props.caseId !== caseId) return;
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      ElMessage.error(detail ?? "草稿加载失败,请稍后重试");
      emit("update:visible", false);
    } finally {
      if (seq === loadSeq) loading.value = false;
    }
  },
  { immediate: true },
);

// 仲裁请求类型树 → el-cascader 选项(支持两级叶子,确认劳动关系等没有第三层)
const cascaderOptions = computed(() => buildCascaderOptions(draft.value?.meta.catalog ?? []));

function catalogItemOf(path: number[]): CatalogItem | undefined {
  return catalogItemOfCatalog(draft.value?.meta.catalog ?? [], path);
}

function optionsOf(row: RequestRow): string[] {
  return catalogItemOf(row.path)?.options ?? [];
}

// $str 模板(如工伤保险待遇)需要多选项+逐项金额,金额合计自动求和。
function isMulti(row: RequestRow): boolean {
  return isMultiTemplate(catalogItemOf(row.path)?.template ?? "");
}

// 期间类请求(工资/二倍工资等,样例3):模板含 开始日期/结束日期 占位。
function needsDates(row: RequestRow): boolean {
  return needsDatesTemplate(catalogItemOf(row.path)?.template ?? "");
}

// 其他类请求:模板含 $other 占位,需要填具体内容。
function needsOther(row: RequestRow): boolean {
  return needsOtherTemplate(catalogItemOf(row.path)?.template ?? "");
}

function onItemsChange(row: RequestRow, names: string[]) {
  const old = new Map(row.items.map((i) => [i.name, i.object]));
  row.items = names.map((n) => ({ name: n, object: old.get(n) ?? null }));
  onFieldChange(row);
}

function itemsSum(row: RequestRow): number | null {
  if (!row.items.length || row.items.some((i) => i.object == null)) return null;
  return row.items.reduce((acc, i) => acc + (i.object ?? 0), 0);
}

function onPathChange(row: RequestRow) {
  // 换了类型后,原第四级选项/金额/期间/请求表述大概率不再适用,清空重选
  // (陈旧金额或旧类型的 intro 随新类型提交会产生错误数据)。
  const item = catalogItemOf(row.path);
  if (row.option && !(item?.options ?? []).includes(row.option)) {
    row.option = null;
  }
  row.items = [];
  row.object = null;
  row.start_at = null;
  row.end_at = null;
  row.other = "";
  row.intro = null;
  row.introAuto = false;
  // 与内网一致的规律:案由=数组中最后一条有效请求的第二层类型(内网服务端
  // 按末请求定案由,2026-08-12 多类型案件实测);仍可手动改。
  const reasons = draft.value?.meta.case_reasons ?? [];
  const lastReason = [...requestRows.value]
    .reverse()
    .map((r) => catalogItemOf(r.path)?.path[1]?.name)
    .find((n): n is string => !!n && reasons.includes(n));
  if (lastReason) {
    form.value.case_reason = lastReason;
  }
}

/** 选项/金额/期间变化:intro 若是草稿自动预填的(未手动编辑)则清掉,
 * 让后端按新值套模板重生成,避免旧金额表述随新数据进内网。 */
function onFieldChange(row: RequestRow) {
  if (row.introAuto) {
    row.intro = null;
    row.introAuto = false;
  }
}

const canSubmit = computed(
  () =>
    !!draft.value &&
    draft.value.errors.length === 0 &&
    !!form.value.case_reason &&
    !!form.value.apply_at &&
    requestRows.value.length > 0 &&
    requestRows.value.every(
      (r) =>
        // 路径要能在目录里匹配到完整叶子(三级;确认劳动关系等两级叶子为两级)
        !!catalogItemOf(r.path) &&
        // 其他类($other 模板)请求必须填具体内容,否则字面 $other 进内网
        (!needsOther(r) || !!r.other.trim()) &&
        // 期间类请求(工资/二倍工资等)必须有起止日期,否则模板填不出、
        // 请求在无期间字段的情况下进内网(后端 RequestSpec 约定必填但未强制)。
        (!needsDates(r) || (r.start_at && r.end_at)) &&
        // 多选项($str)请求必须每项都有金额,否则总额/明细不一致进内网。
        (!isMulti(r) || (r.items.length > 0 && r.items.every((i) => i.object != null))),
    ),
);

function buildSpec(): SubmitSpec {
  return {
    apply_at: form.value.apply_at,
    town_id: form.value.town_id,
    case_reason: form.value.case_reason,
    is_sign_labor_contract: form.value.is_sign_labor_contract,
    is_pay_social_insurance: form.value.is_pay_social_insurance,
    is_easy: form.value.is_easy,
    company_nature: form.value.company_nature,
    id_type: form.value.id_type,
    is_migrant_worker: form.value.is_migrant_worker,
    is_three_woman_worker: form.value.is_three_woman_worker,
    main_causes: [
      ...mainCauseSelected.value,
      ...(mainCauseOther.value.trim() ? [mainCauseOther.value.trim()] : []),
    ],
    fact_content: form.value.fact_content.trim() || null,
    requests: requestRows.value.map((r) => {
      const multi = isMulti(r);
      return {
        text: r.text,
        path_ids: r.path,
        applicant_index: r.applicant_index,
        option: multi ? null : r.option || null,
        object: multi ? itemsSum(r) : r.object ?? null,
        items: multi ? r.items : [],
        start_at: needsDates(r) ? r.start_at : null,
        end_at: needsDates(r) ? r.end_at : null,
        other: r.other.trim() || null,
        intro: r.intro?.trim() || null,
      };
    }),
    force: false,
  };
}

// 事实理由自动生成(共享 utils/factCompose,与后端 compose_case_facts 同规则;
// 主因以勾选区为准——已预填存量值,改了勾选重新生成即生效)。
function composeFacts() {
  const parties = draft.value?.fact_parties ?? [];
  if (!parties.length) return;
  const caseCauses = [
    ...mainCauseSelected.value,
    ...(mainCauseOther.value.trim() ? [mainCauseOther.value.trim()] : []),
  ];
  form.value.fact_content = composeCaseFacts(parties, {
    sign: form.value.is_sign_labor_contract,
    ins: form.value.is_pay_social_insurance,
    caseCauses,
  });
}

async function openPreview() {
  try {
    const payload = await api.submitPreview(props.caseId, buildSpec());
    previewJson.value = JSON.stringify(payload, null, 2);
    previewVisible.value = true;
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail ?? "预览生成失败");
  }
}

async function doSubmit() {
  // 确认框弹出期间禁止重复触发,避免双击开出两个确认框都提交。
  if (submitting.value) return;
  submitting.value = true;
  try {
    try {
      await ElMessageBox.confirm(
        `确认将 ${props.receiptNumber} 保存到内网收件?保存后内网将生成正式收件记录。`,
        "保存确认",
        { type: "warning", confirmButtonText: "确认保存", cancelButtonText: "再检查一下" },
      );
    } catch {
      return;
    }
    await submitWithSpec(buildSpec());
  } finally {
    submitting.value = false;
  }
}

async function submitWithSpec(spec: SubmitSpec) {
  submitting.value = true;
  try {
    const res = await api.submitToInternal(props.caseId, spec);
    // 内网已建案但本地状态落库失败时后端带 warning:必须提示人工核对,
    // 只弹成功会让用户看到"待录入"再次提交,造成内网重复建案。
    if (res.warning) {
      ElMessage.warning(res.warning);
    } else {
      ElMessage.success(`${props.receiptNumber} 已保存到内网收件`);
    }
    emit("update:visible", false);
    emit("submitted");
  } catch (err: unknown) {
    const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
    // 内网提示疑似重复案件:让用户确认后带 force 重试(与内网前端流程一致)。
    if (resp?.status === 409 && resp.data?.detail && !spec.force) {
      try {
        await ElMessageBox.confirm(resp.data.detail, "内网提示", {
          type: "warning",
          confirmButtonText: "仍要保存",
          cancelButtonText: "取消",
        });
      } catch {
        return;
      }
      await submitWithSpec({ ...spec, force: true });
      return;
    }
    ElMessage.error(resp?.data?.detail ?? "保存失败,请稍后重试");
  } finally {
    submitting.value = false;
  }
}

const companyFillText = computed(() => {
  const fills = draft.value?.company_fills ?? [];
  const found = fills.filter((f) => f.found);
  if (!found.length) return "";
  return found
    .map((f) => `${f.name}${f.registered_capital ? `(注册资本 ${f.registered_capital} 万元)` : ""}`)
    .join("、");
});

// 多申请人时请求卡片标注归属申请人(intro 会带"申请人N",卡片给人看姓名更直观)。
const hasMultiApplicants = computed(
  () => new Set(requestRows.value.map((r) => r.applicant_index)).size > 1,
);
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="保存到内网收件"
    width="980px"
    top="3vh"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-loading="loading" class="submit-body">
      <template v-if="draft">
        <el-alert v-if="draft.errors.length" type="error" :closable="false" class="mb">
          <div v-for="(e, i) in draft.errors" :key="i">✕ {{ e }}(请返回编辑补齐后再保存)</div>
        </el-alert>
        <el-alert v-if="draft.warnings.length" type="warning" :closable="false" class="mb">
          <div v-for="(w, i) in draft.warnings" :key="i">⚠ {{ w }}</div>
        </el-alert>
        <el-alert v-if="companyFillText" type="success" :closable="false" class="mb">
          已通过查企业接口回填:{{ companyFillText }}
        </el-alert>

        <div class="section-title">基本信息</div>
        <div class="field-grid">
          <div class="field">
            <label>申请日期</label>
            <el-date-picker v-model="form.apply_at" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 100%" />
          </div>
          <div class="field">
            <label>乡镇街道</label>
            <el-select v-model="form.town_id" filterable>
              <el-option
                v-for="t in draft.meta.towns"
                :key="t.town_id"
                :label="t.town_name"
                :value="t.town_id"
              />
            </el-select>
          </div>
          <div class="field">
            <label>案由 *</label>
            <el-select v-model="form.case_reason" filterable placeholder="请选择案由">
              <el-option v-for="r in draft.meta.case_reasons" :key="r" :label="r" :value="r" />
            </el-select>
          </div>
          <div class="field">
            <label>企业性质</label>
            <el-select v-model="form.company_nature" filterable>
              <el-option v-for="n in draft.meta.company_natures" :key="n" :label="n" :value="n" />
            </el-select>
          </div>
          <div class="field">
            <label>申请人证件类型</label>
            <el-select v-model="form.id_type" filterable>
              <el-option v-for="t in draft.meta.worker_id_types" :key="t" :label="t" :value="t" />
            </el-select>
          </div>
          <div class="field">
            <label>签订劳动合同</label>
            <el-switch
              v-model="form.is_sign_labor_contract"
              :active-value="1"
              :inactive-value="0"
              active-text="是"
              inactive-text="否"
            />
          </div>
          <div class="field">
            <label>缴纳社保</label>
            <el-switch
              v-model="form.is_pay_social_insurance"
              :active-value="1"
              :inactive-value="0"
              active-text="是"
              inactive-text="否"
            />
          </div>
          <div class="field">
            <label>简易案件</label>
            <el-switch
              v-model="form.is_easy"
              :active-value="1"
              :inactive-value="0"
              active-text="是"
              inactive-text="否"
            />
          </div>
          <div class="field">
            <label>农民工(申请人)</label>
            <el-switch
              v-model="form.is_migrant_worker"
              :active-value="1"
              :inactive-value="0"
              active-text="是"
              inactive-text="否"
            />
          </div>
          <div class="field">
            <label>三期女职工(申请人)</label>
            <el-switch
              v-model="form.is_three_woman_worker"
              :active-value="1"
              :inactive-value="0"
              active-text="是"
              inactive-text="否"
            />
          </div>
        </div>

        <div class="section-title">仲裁请求(自动匹配的类型请逐条确认)</div>
        <div v-for="(r, idx) in requestRows" :key="idx" class="request-card">
          <div class="request-text">
            <el-tag v-if="hasMultiApplicants" size="small" type="info" effect="plain">
              {{ r.applicant_name || `申请人${r.applicant_index + 1}` }}
            </el-tag>
            <el-tag v-if="r.guessed" size="small" type="success" effect="plain">已自动匹配</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">需人工选择</el-tag>
            {{ r.text }}
          </div>
          <div class="request-fields">
            <el-cascader
              v-model="r.path"
              :options="cascaderOptions"
              placeholder="请求类型(确认劳动关系等为两级)"
              style="width: 340px"
              @change="onPathChange(r)"
            />
            <template v-if="isMulti(r)">
              <el-select
                :model-value="r.items.map((i) => i.name)"
                multiple
                filterable
                placeholder="费用项(可多选)"
                style="width: 320px"
                @update:model-value="onItemsChange(r, $event)"
              >
                <el-option v-for="o in optionsOf(r)" :key="o" :label="o" :value="o" />
              </el-select>
              <span class="sum-hint">合计: {{ itemsSum(r) ?? "—" }} 元</span>
            </template>
            <template v-else>
              <el-select
                v-model="r.option"
                clearable
                filterable
                placeholder="第四级选项"
                style="width: 260px"
                :disabled="!optionsOf(r).length"
                @change="onFieldChange(r)"
              >
                <el-option v-for="o in optionsOf(r)" :key="o" :label="o" :value="o" />
              </el-select>
              <el-input-number
                v-model="r.object"
                :min="0"
                :precision="2"
                :controls="false"
                placeholder="金额(元)"
                style="width: 140px"
                @change="onFieldChange(r)"
              />
            </template>
          </div>
          <div v-if="needsDates(r)" class="request-dates">
            <el-date-picker
              v-model="r.start_at"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="期间起(开始日期)"
              style="width: 200px"
              @change="onFieldChange(r)"
            />
            <el-date-picker
              v-model="r.end_at"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="期间止(结束日期)"
              style="width: 200px"
              @change="onFieldChange(r)"
            />
          </div>
          <div v-if="needsOther(r)" class="request-dates">
            <el-input
              v-model="r.other"
              placeholder="其他类请求的具体内容,如:未缴纳住房公积金损失"
              style="width: 400px"
              @input="onFieldChange(r)"
            />
          </div>
          <div v-if="isMulti(r) && r.items.length" class="items-amounts">
            <div v-for="(it, iIdx) in r.items" :key="it.name" class="item-amount">
              <span class="item-name">{{ iIdx + 1 }}. {{ it.name }}</span>
              <el-input-number
                v-model="it.object"
                :min="0"
                :precision="2"
                :controls="false"
                placeholder="金额(元)"
                style="width: 140px"
                @change="onFieldChange(r)"
              />
            </div>
          </div>
          <el-input
            v-model="r.intro"
            placeholder="请求表述:留空按内网模板自动生成,生成不了用上方原文"
            class="intro-input"
            @input="r.introAuto = false"
          />
        </div>

        <div class="section-title">事实理由(与内网相同的自动生成,可编辑)</div>
        <div class="fact-section">
          <div class="fact-cause">
            <label>本次申请劳动仲裁的最主要原因(填入"因…"段,可多选)</label>
            <el-checkbox-group v-model="mainCauseSelected">
              <el-checkbox
                v-for="p in draft.meta.main_cause_presets"
                :key="p"
                :value="p"
                class="cause-checkbox"
              >
                {{ p }}
              </el-checkbox>
            </el-checkbox-group>
            <div class="cause-other">
              <span class="cause-other-label">其他</span>
              <el-input v-model="mainCauseOther" placeholder="选填,自定义主要原因" />
            </div>
          </div>
          <div class="fact-editor">
            <el-input v-model="form.fact_content" type="textarea" :rows="4" />
            <el-button size="small" class="compose-btn" @click="composeFacts">自动生成</el-button>
          </div>
        </div>

        <p class="hint">
          区域固定为 福建省 / 三明市 / 永安市;证据材料暂不随保存上传,可在内网补充。
          保存前可点"预览请求体"核对最终发往内网的数据。
        </p>
      </template>
    </div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button :disabled="!canSubmit" @click="openPreview">预览请求体</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit || submitting" @click="doSubmit">
        确认保存
      </el-button>
    </template>

    <el-dialog v-model="previewVisible" title="发往内网的请求体" width="760px" append-to-body>
      <pre class="preview-json">{{ previewJson }}</pre>
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.submit-body {
  min-height: 200px;
}

.mb {
  margin-bottom: 10px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  margin: 14px 0 10px;
  padding-left: 8px;
  border-left: 3px solid var(--accent-blue);
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px 14px;
}

.field label {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.request-card {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.request-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
}

.request-fields {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.intro-input {
  font-size: 13px;
}

.sum-hint {
  font-size: 13px;
  color: var(--el-text-color-regular);
  align-self: center;
}

.request-dates {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.items-amounts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 16px;
  margin-bottom: 8px;
}

.item-amount {
  display: flex;
  align-items: center;
  gap: 8px;
}

.item-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  flex: 1;
}

.fact-cause {
  margin-bottom: 8px;
}

.fact-cause label {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.cause-checkbox {
  display: flex;
  margin-right: 0;
  height: auto;
  white-space: normal;
  align-items: flex-start;
  padding: 2px 0;
}

.cause-other {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.cause-other-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
  flex-shrink: 0;
}

.fact-editor {
  position: relative;
}

.compose-btn {
  position: absolute;
  right: 8px;
  bottom: 8px;
}

.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 8px 0 0;
}

.preview-json {
  max-height: 60vh;
  overflow: auto;
  font-size: 12px;
  background: #f8fafc;
  padding: 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
