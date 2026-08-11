<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, ref, watch } from "vue";

import * as api from "@/api/virtualCases";
import type { CatalogItem, SubmitDraft, SubmitSpec } from "@/api/virtualCases";

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
  intro: string | null;
  guessed: boolean;
}
const requestRows = ref<RequestRow[]>([]);

const previewVisible = ref(false);
const previewJson = ref("");

watch(
  () => props.visible,
  async (v) => {
    if (!v) return;
    loading.value = true;
    draft.value = null;
    try {
      const d = await api.fetchSubmitDraft(props.caseId);
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
      mainCauseSelected.value = [];
      mainCauseOther.value = "";
      requestRows.value = d.requests.map((r) => ({
        text: r.text,
        path: r.path_ids ? [...r.path_ids] : [],
        option: r.option,
        object: r.object,
        items: [],
        start_at: null,
        end_at: null,
        intro: r.intro,
        guessed: r.guessed,
      }));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      ElMessage.error(detail ?? "草稿加载失败,请稍后重试");
      emit("update:visible", false);
    } finally {
      loading.value = false;
    }
  },
);

// 仲裁请求类型树 → el-cascader 选项(三级)
interface CascaderNode {
  value: number;
  label: string;
  children?: CascaderNode[];
}
const cascaderOptions = computed<CascaderNode[]>(() => {
  const catalog = draft.value?.meta.catalog ?? [];
  const l1map = new Map<number, CascaderNode>();
  const l2map = new Map<string, CascaderNode>();
  for (const item of catalog) {
    const [l1, l2, l3] = item.path;
    if (!l1map.has(l1.id)) l1map.set(l1.id, { value: l1.id, label: l1.name, children: [] });
    const n1 = l1map.get(l1.id)!;
    const key2 = `${l1.id}/${l2.id}`;
    if (!l2map.has(key2)) {
      const n2: CascaderNode = { value: l2.id, label: l2.name, children: [] };
      l2map.set(key2, n2);
      n1.children!.push(n2);
    }
    l2map.get(key2)!.children!.push({ value: l3.id, label: l3.name });
  }
  return [...l1map.values()];
});

function catalogItemOf(path: number[]): CatalogItem | undefined {
  return draft.value?.meta.catalog.find(
    (c) => c.path.length === 3 && c.path.every((n, i) => n.id === path[i]),
  );
}

function optionsOf(row: RequestRow): string[] {
  return catalogItemOf(row.path)?.options ?? [];
}

// $str 模板(如工伤保险待遇)需要多选项+逐项金额,金额合计自动求和。
function isMulti(row: RequestRow): boolean {
  return (catalogItemOf(row.path)?.template ?? "").includes("$str");
}

// 期间类请求(工资/二倍工资等,样例3):模板含 开始日期/结束日期 占位。
function needsDates(row: RequestRow): boolean {
  const tpl = catalogItemOf(row.path)?.template ?? "";
  return tpl.includes("开始日期") || tpl.includes("结束日期");
}

function onItemsChange(row: RequestRow, names: string[]) {
  const old = new Map(row.items.map((i) => [i.name, i.object]));
  row.items = names.map((n) => ({ name: n, object: old.get(n) ?? null }));
}

function itemsSum(row: RequestRow): number | null {
  if (!row.items.length || row.items.some((i) => i.object == null)) return null;
  return row.items.reduce((acc, i) => acc + (i.object ?? 0), 0);
}

function onPathChange(row: RequestRow) {
  // 换了类型后,原第四级选项大概率不再适用,清空重选。
  const item = catalogItemOf(row.path);
  if (row.option && !(item?.options ?? []).includes(row.option)) {
    row.option = null;
  }
  row.items = [];
}

const canSubmit = computed(
  () =>
    !!draft.value &&
    draft.value.errors.length === 0 &&
    !!form.value.case_reason &&
    requestRows.value.length > 0 &&
    requestRows.value.every((r) => r.path.length === 3),
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
        option: multi ? null : r.option || null,
        object: multi ? itemsSum(r) : r.object ?? null,
        items: multi ? r.items : [],
        start_at: needsDates(r) ? r.start_at : null,
        end_at: needsDates(r) ? r.end_at : null,
        intro: r.intro?.trim() || null,
      };
    }),
    force: false,
  };
}

// 事实理由自动生成(与后端 compose_facts 同模板,内网"自动生成"按钮的复刻)。
function composeFacts() {
  const parts = draft.value?.fact_parts;
  if (!parts) return;
  const fmtAmount = (v: string | null) => {
    const n = parseFloat(String(v ?? "").replace(",", ""));
    return Number.isFinite(n) ? String(n) : null;
  };
  const segs: string[] = [];
  if (parts.entry_date) {
    const [y, m, d] = parts.entry_date.slice(0, 10).split("-").map(Number);
    let seg = `本人于${y}年${m}月${d}日入职被申请人处`;
    const tail: string[] = [];
    if (parts.work_place) tail.push(`实际工作地点${parts.work_place}`);
    if (parts.position) tail.push(`工作岗位为${parts.position}`);
    const wage = fmtAmount(parts.monthly_wage);
    if (wage) tail.push(`月工资标准为${wage}元`);
    if (tail.length) seg += ", " + tail.join("，");
    segs.push(seg + "。");
  }
  const sign = form.value.is_sign_labor_contract === 1 ? "有" : "没有";
  const ins = form.value.is_pay_social_insurance === 1 ? "有" : "没有";
  let seg2 = `本人入职后，被申请人${sign}与本人签订书面劳动合同,${ins}为本人缴纳社会保险费`;
  const causes = [
    ...mainCauseSelected.value,
    ...(mainCauseOther.value.trim() ? [mainCauseOther.value.trim()] : []),
  ];
  seg2 += causes.length ? `;因${causes.join("，")}。` : "。";
  segs.push(seg2);
  segs.push("为维护本人合法权益，特提出申请，望裁如所请。");
  form.value.fact_content = segs.join("");
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
  try {
    await ElMessageBox.confirm(
      `确认将 ${props.receiptNumber} 提交到内网收件?提交后内网将生成正式收件记录。`,
      "提交确认",
      { type: "warning", confirmButtonText: "确认提交", cancelButtonText: "再检查一下" },
    );
  } catch {
    return;
  }
  await submitWithSpec(buildSpec());
}

async function submitWithSpec(spec: SubmitSpec) {
  submitting.value = true;
  try {
    await api.submitToInternal(props.caseId, spec);
    ElMessage.success(`${props.receiptNumber} 已提交到内网收件`);
    emit("update:visible", false);
    emit("submitted");
  } catch (err: unknown) {
    const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
    // 内网提示疑似重复案件:让用户确认后带 force 重试(与内网前端流程一致)。
    if (resp?.status === 409 && resp.data?.detail) {
      try {
        await ElMessageBox.confirm(resp.data.detail, "内网提示", {
          type: "warning",
          confirmButtonText: "仍要提交",
          cancelButtonText: "取消",
        });
      } catch {
        return;
      }
      await submitWithSpec({ ...spec, force: true });
      return;
    }
    ElMessage.error(resp?.data?.detail ?? "提交失败,请稍后重试");
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
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="提交到内网收件"
    width="980px"
    top="3vh"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-loading="loading" class="submit-body">
      <template v-if="draft">
        <el-alert v-if="draft.errors.length" type="error" :closable="false" class="mb">
          <div v-for="(e, i) in draft.errors" :key="i">✕ {{ e }}(请返回编辑补齐后再提交)</div>
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
            <el-date-picker v-model="form.apply_at" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
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
            <el-tag v-if="r.guessed" size="small" type="success" effect="plain">已自动匹配</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">需人工选择</el-tag>
            {{ r.text }}
          </div>
          <div class="request-fields">
            <el-cascader
              v-model="r.path"
              :options="cascaderOptions"
              placeholder="请求类型(三级)"
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
            />
            <el-date-picker
              v-model="r.end_at"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="期间止(结束日期)"
              style="width: 200px"
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
              />
            </div>
          </div>
          <el-input
            v-model="r.intro"
            placeholder="请求表述:留空按内网模板自动生成,生成不了用上方原文"
            class="intro-input"
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
          区域固定为 福建省 / 三明市 / 永安市;证据材料暂不随提交上传,可在内网补充。
          提交前可点"预览请求体"核对最终发往内网的数据。
        </p>
      </template>
    </div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button :disabled="!canSubmit" @click="openPreview">预览请求体</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="doSubmit">
        确认提交
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
