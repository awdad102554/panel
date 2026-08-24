<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import { onMounted, ref } from "vue";

import * as api from "@/api/virtualCases";
import type { CatalogItem, Evidence, Party, VirtualCase } from "@/api/virtualCases";
import PartyAgentsEditor from "@/components/PartyAgentsEditor.vue";
import PartyRequestsEditor, { type ReqRow } from "@/components/PartyRequestsEditor.vue";
import VirtualCaseSubmitDialog from "@/components/VirtualCaseSubmitDialog.vue";
import CaseTagDialog from "@/components/case/CaseTagDialog.vue";
import { catalogItemOf, disambiguateApplicant, isMultiTemplate, pluralizeRespondent } from "@/utils/requestCatalog";
import { composePartyFacts } from "@/utils/factCompose";

// 表单里的当事人:在 Party 基础上带请求编辑器的行状态(保存时拆开,不入库)。
type PartyForm = Party & { reqRows?: ReqRow[]; causeOther?: string };

const cases = ref<VirtualCase[]>([]);
const loading = ref(false);

// 请求类型目录(内网字典)+主因预设:打开新建/编辑对话框时拉一次,失败降级为自由文本录入。
const catalog = ref<CatalogItem[]>([]);
const mainCausePresets = ref<string[]>([]);
let catalogLoading = false;

async function ensureCatalog() {
  if (catalog.value.length || catalogLoading) return;
  catalogLoading = true;
  try {
    const meta = await api.fetchRequestCatalog();
    catalog.value = meta.catalog;
    mainCausePresets.value = meta.main_cause_presets;
  } catch {
    ElMessage.warning("请求类型目录加载失败,可先用自定义文本填写请求");
  } finally {
    catalogLoading = false;
  }
}

const submitVisible = ref(false);
const submitTarget = ref<VirtualCase | null>(null);

function openSubmit(row: VirtualCase) {
  submitTarget.value = row;
  submitVisible.value = true;
}

// 标签对话框
const tagDialogVisible = ref(false);
const tagSubjectKey = ref("");
const tagTitle = ref("");

function openTagDialog(row: VirtualCase) {
  tagSubjectKey.value = `virt:${row.id}`;
  tagTitle.value = row.receipt_number;
  tagDialogVisible.value = true;
}

const dialogVisible = ref(false);
const editingId = ref<string | null>(null);
const saving = ref(false);

const form = ref({ note: "" });
const applicants = ref<PartyForm[]>([]);
const respondents = ref<PartyForm[]>([]);
const evidences = ref<Evidence[]>([]);

function emptyApplicant(): PartyForm {
  return {
    party_type: "natural",
    name: "",
    id_number: null,
    gender: null,
    ethnicity: null,
    birth_date: null,
    address: null,
    phone: null,
    work_place: null,
    position: null,
    entry_date: null,
    monthly_wage: null,
    claims: null,
    requests: [],
    reqRows: [],
    is_sign_labor_contract: 1,
    is_pay_social_insurance: 1,
    main_causes: [],
    facts: null,
    legal_person: null,
    legal_title: null,
    agents: [],
  };
}

function emptyRespondent(): PartyForm {
  return { ...emptyApplicant(), party_type: "company" };
}

function openCreate() {
  editingId.value = null;
  form.value = { note: "" };
  applicants.value = [emptyApplicant()];
  respondents.value = [emptyRespondent()];
  evidences.value = [];
  dialogVisible.value = true;
  ensureCatalog();
}

/** 库里的 requests 文本 + request_specs 结构化数据 → 编辑器行(按索引对齐,
 * 旧数据没有 specs 的行按自由文本行展示)。结构化行 touched 置 false:改金额/
 * 期间等字段时自动重生成文本,避免"文本旧金额、spec 新金额"的不一致入库
 * (用户手动改过文本框才置 true 锁定)。 */
function buildReqRows(p: Party): ReqRow[] {
  const texts = p.requests?.length ? [...p.requests] : p.claims ? [p.claims] : [];
  const specs = p.request_specs ?? [];
  return texts.map((t, i) => {
    const s = specs[i];
    if (s && s.path_ids?.length) {
      return {
        free: false,
        text: t,
        touched: false,
        path: [...s.path_ids],
        path_names: s.path_names ?? [],
        option: s.option ?? null,
        object: s.object ?? null,
        items: (s.items ?? []).map((x) => ({ name: x.name, object: x.object })),
        start_at: s.start_at ?? null,
        end_at: s.end_at ?? null,
        other: s.other ?? "",
      };
    }
    return {
      free: true,
      text: t,
      touched: true,
      path: [],
      option: null,
      object: null,
      items: [],
      start_at: null,
      end_at: null,
      other: "",
    };
  });
}

function openEdit(row: VirtualCase) {
  editingId.value = row.id;
  form.value = { note: row.note ?? "" };
  applicants.value = row.applicants.map((p) => {
    // 自定义主因(不在预设里的)归入"其他主因"输入框;预设未加载时全部留在多选里。
    const causes = p.main_causes ?? [];
    const customs = mainCausePresets.value.length
      ? causes.filter((x) => !mainCausePresets.value.includes(x))
      : [];
    return {
      ...emptyApplicant(),
      ...p,
      main_causes: mainCausePresets.value.length
        ? causes.filter((x) => mainCausePresets.value.includes(x))
        : [...causes],
      causeOther: customs.join("；"),
      requests: p.requests?.length ? [...p.requests] : [],
      reqRows: buildReqRows(p),
      agents: (p.agents ?? []).map((a) => ({ ...a })),
    };
  });
  respondents.value = row.respondents.map((p) => ({
    ...emptyRespondent(),
    ...p,
    agents: (p.agents ?? []).map((a) => ({ ...a })),
  }));
  evidences.value = (row.evidences ?? []).map((e) => ({ ...e }));
  dialogVisible.value = true;
  ensureCatalog();
}

function addItem<T>(list: T[], item: T) {
  list.push(item);
}

function removeItem<T>(list: T[], index: number) {
  list.splice(index, 1);
}

const queryingKey = ref<string | null>(null);

async function lookup(party: Party, key: string) {
  queryingKey.value = key;
  try {
    if (party.party_type === "natural") {
      if (!party.id_number) {
        ElMessage.warning("请先填写身份证号再查询");
        return;
      }
      const body = await api.lookupPerson(party.id_number);
      const data = body?.data;
      if (!data || !data["姓名"]) {
        ElMessage.warning("未查到该身份证对应的自然人信息");
        return;
      }
      party.name = data["姓名"];
      party.gender = data["性别"] ?? party.gender;
      party.ethnicity = data["民族"] ?? party.ethnicity;
      party.birth_date = data["出生日期"] ?? party.birth_date;
      party.address = data["户籍地址"] ?? party.address;
      party.id_number = data["身份证号码"] ?? party.id_number;
      ElMessage.success(`查询成功:${data["姓名"]}`);
    } else {
      if (!party.name && !party.id_number) {
        ElMessage.warning("请先填写企业名称或统一社会信用代码再查询");
        return;
      }
      // 先按名称查;查不到且填了信用代码时自动改用信用代码再查一次。
      let body = party.name ? await api.lookupCompany(party.name) : null;
      if (!body?.data?.length && party.id_number) {
        body = await api.lookupCompany(party.id_number);
      }
      const first = body?.data?.[0];
      if (!first) {
        ElMessage.warning("未查到匹配的企业(名称需完整,或用 18 位信用代码)");
        return;
      }
      party.name = first["企业名称"] ?? party.name;
      party.id_number = first["统一社会信用代码"] ?? party.id_number;
      party.address = first["注册地址"] ?? first["实际经营地址"] ?? party.address;
      party.phone = first["公司电话"] ?? party.phone;
      party.legal_person = first["法人姓名"] ?? party.legal_person;
      ElMessage.success(`查询成功:${party.name}`);
    }
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail ?? "查询失败或未查到对应信息");
  } finally {
    queryingKey.value = null;
  }
}

async function save() {
  if (applicants.value.length === 0 || respondents.value.length === 0) {
    ElMessage.warning("申请人和被申请人至少各一名");
    return;
  }
  const all = [...applicants.value, ...respondents.value];
  if (all.some((p) => !p.name.trim())) {
    ElMessage.warning("当事人姓名/单位名称不能为空");
    return;
  }
  if (all.some((p) => (p.agents ?? []).some((a) => !a.name.trim()))) {
    ElMessage.warning("代理人姓名不能为空(或删除该代理人)");
    return;
  }
  // 结构化行已选类型但文本为空(期间/金额/具体内容没填,模板没生成出来):
  // 保存会被 filter 静默丢弃,必须拦下让用户补齐或删行。
  const emptyStructured = applicants.value.some((p) =>
    (p.reqRows ?? []).some((r) => !r.free && r.path.length > 0 && !r.text.trim()),
  );
  if (emptyStructured) {
    ElMessage.warning('有仲裁请求已选类型但未生成文本:请补齐金额/期间/具体内容(或点"自动生成"),不需要的请删除该行');
    return;
  }
  // 等目录就绪再组装 specs:目录冷拉取(数秒)未完成时直接保存会把结构化数据
  // 整列覆盖成 null(数据丢失)。
  await ensureCatalog();
  saving.value = true;
  try {
    const applicantsClean = applicants.value.map((p, ai) => {
      const { reqRows, causeOther, ...rest } = p;
      const rows = (reqRows ?? []).filter((r) => r.text.trim());
      // 多申请人:文本里泛指的"申请人"统一加编号(申请人N),提交内网/申请书同一口径;
      // 多被申请人:支付类表述改"各被申请人共同"。两个规则都幂等,编辑器已处理的不重复加。
      const multi = applicants.value.length > 1;
      const pluralResp = respondents.value.length > 1;
      return {
        ...rest,
        name: p.name.trim(),
        claims: null, // claims 已迁移进 requests(buildReqRows),清掉避免数据重复残留
        // 预设多选 + 其他自定义合并入库(后端按内网结构区分预设/[None,自定义])
        main_causes: [
          ...(p.main_causes ?? []),
          ...(causeOther?.trim() ? [causeOther.trim()] : []),
        ],
        requests: rows.map((r) => {
          let t = r.text.trim();
          // 先剥离旧的"申请人N"编号再按当前位置重标:删除/换序申请人后不留陈旧编号
          // (\d{1,2}(?!\d) 限定编号位数,不误伤"申请人2025年…"这类叙述)。
          t = t.replace(/(^|[^被])申请人\d{1,2}(?!\d)/g, "$1申请人");
          if (multi) t = disambiguateApplicant(t, ai + 1);
          if (pluralResp) t = pluralizeRespondent(t);
          return t;
        }),
        // 与 requests 按索引对齐的结构化数据:自由文本行/未选类型的行存 null。
        // 提交内网用它免猜类型,申请书合计金额取 object/items 不依赖文本正则。
        request_specs: rows.map((r) => {
          if (r.free || !r.path.length) return null;
          const item = catalogItemOf(catalog.value, r.path);
          // 目录拉取失败或路径已失效:原样保留结构化数据(后端能识别失效类型并
          // 提示重选),不静默存 null——结构化信息丢了不可恢复。
          if (!item) {
            return {
              path_ids: r.path,
              path_names: r.path_names ?? [],
              option: r.option,
              object: r.object,
              items: r.items.filter((i) => i.name),
              start_at: r.start_at,
              end_at: r.end_at,
              other: r.other.trim() || null,
            };
          }
          const multi = isMultiTemplate(item.template ?? "");
          // 多选项请求 object 与 items 求和保持一致(缺额则置空,不留陈旧金额),
          // 申请书合计与提交内网都按 object 优先取,口径统一。
          const complete = r.items.length > 0 && r.items.every((i) => i.object != null);
          return {
            path_ids: r.path,
            path_names: item.path.map((n) => n.name),
            option: multi ? null : r.option,
            object: multi
              ? complete
                ? r.items.reduce((acc, i) => acc + (i.object ?? 0), 0)
                : null
              : r.object,
            items: r.items.filter((i) => i.name),
            start_at: r.start_at,
            end_at: r.end_at,
            other: r.other.trim() || null,
          };
        }),
      };
    });
    // 被申请人卡片不展示请求/事实要素,清掉继承自申请人结构的字段,避免脏数据入库。
    const respondentsClean = respondents.value.map((p) => {
      const { reqRows, causeOther, ...rest } = p;
      return {
        ...rest,
        name: p.name.trim(),
        requests: [],
        request_specs: [],
        is_sign_labor_contract: null,
        is_pay_social_insurance: null,
        main_causes: [],
      };
    });
    const payload = {
      // 编辑表单没有案由字段:编辑时保留原值,不静默清掉。
      case_reason: editingId.value
        ? (cases.value.find((c) => c.id === editingId.value)?.case_reason ?? null)
        : null,
      claims: null,
      note: form.value.note || null,
      applicants: applicantsClean,
      respondents: respondentsClean,
      evidences: evidences.value.filter((e) => e.name.trim()),
    };
    if (editingId.value) {
      await api.updateVirtualCase(editingId.value, payload);
      ElMessage.success("已保存");
    } else {
      const created = await api.createVirtualCase(payload);
      ElMessage.success(`已登记:${created.receipt_number}`);
    }
    dialogVisible.value = false;
    await refresh();
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail ?? "保存失败,请稍后重试");
  } finally {
    saving.value = false;
  }
}

// 统一提取后端错误 detail;blob 响应(下载类接口)的错误体需要异步解析。
async function extractErrorDetail(err: unknown): Promise<string | undefined> {
  const data = (err as { response?: { data?: unknown } })?.response?.data;
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : undefined;
  }
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { detail?: unknown };
      return typeof parsed.detail === "string" ? parsed.detail : undefined;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

async function downloadApplication(row: VirtualCase) {
  try {
    const res = await api.downloadApplication(row.id);
    // 文件名以后端 Content-Disposition 为准(含日期、格式统一)。
    const disposition = String(res.headers["content-disposition"] ?? "");
    const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
    const filename = match
      ? decodeURIComponent(match[1])
      : `仲裁申请书-${row.applicants[0]?.name ?? row.receipt_number}.docx`;
    const url = URL.createObjectURL(new Blob([res.data]));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    // 延迟释放:部分浏览器立即 revoke 会导致下载失败。
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    ElMessage.error((await extractErrorDetail(err)) ?? "生成失败,请稍后重试");
  }
}

async function markRecorded(row: VirtualCase) {
  try {
    await api.updateVirtualCaseStatus(row.id, "recorded");
    ElMessage.success(`${row.receipt_number} 已标记为已录入内网`);
    await refresh();
  } catch (err) {
    ElMessage.error((await extractErrorDetail(err)) ?? "操作失败,请稍后重试");
  }
}

async function removeCase(row: VirtualCase) {
  try {
    await ElMessageBox.confirm(
      `确定删除预登记案件 ${row.receipt_number}?仅删除本系统的登记记录,不影响内网已生成的收件。`,
      "删除确认",
      {
        type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await api.deleteVirtualCase(row.id);
    ElMessage.success("已删除");
    await refresh();
  } catch (err) {
    ElMessage.error((await extractErrorDetail(err)) ?? "删除失败,请稍后重试");
  }
}

function partiesText(parties: Party[]) {
  return parties.map((p) => p.name).join("、") || "-";
}

/** 事实理由自动生成预览(与保存到内网/申请书同一拼接规则;含"其他主因"输入框内容)。 */
function factsPreview(p: PartyForm, idx: number): string {
  return composePartyFacts(
    {
      ...p,
      main_causes: [
        ...(p.main_causes ?? []),
        ...(p.causeOther?.trim() ? [p.causeOther.trim()] : []),
      ],
    },
    idx + 1,
    applicants.value.length,
  );
}

async function refresh() {
  loading.value = true;
  try {
    cases.value = await api.listVirtualCases();
  } catch {
    ElMessage.error("列表加载失败,请稍后重试");
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <div class="virtual-cases">
    <div class="vc-header">
      <h2>预登记案件</h2>
      <p class="hint">
        暂不录入内网系统的案件可在此预登记,记录案件信息与进度,数据仅保存在本系统的独立文件数据库(SQLite),不与内网同步。待录入的案件会计入案件总览的"待办案件"卡片,录入内网后点"标记已录入"退出待办。
        当事人信息可通过身份证号/企业名称(或信用代码)调用内部接口查询自动填充。案件信息完整后可点"保存到内网"直接写入内网收件,无需在内网重复录入。
      </p>
    </div>

    <div class="toolbar">
      <el-button type="primary" @click="openCreate">新建预登记</el-button>
      <el-button :loading="loading" @click="refresh">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="cases" empty-text="暂无预登记案件">
      <el-table-column label="收件编号" prop="receipt_number" width="170" />
      <el-table-column label="申请人" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ partiesText(row.applicants) }}</template>
      </el-table-column>
      <el-table-column label="被申请人" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ partiesText(row.respondents) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="row.status === 'recorded' ? 'success' : 'warning'" effect="light">
            {{ row.status === 'recorded' ? "已录入内网" : "待录入" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="登记时间" width="110">
        <template #default="{ row }">{{ row.created_at?.slice(0, 10) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="480">
        <template #default="{ row }">
          <el-button size="small" @click="openTagDialog(row)">标签</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="primary" plain @click="downloadApplication(row)">生成申请书</el-button>
          <el-button
            v-if="row.status === 'pending'"
            size="small"
            type="success"
            @click="openSubmit(row)"
          >
            保存到内网
          </el-button>
          <el-button
            v-if="row.status === 'pending'"
            size="small"
            type="success"
            plain
            @click="markRecorded(row)"
          >
            标记已录入
          </el-button>
          <el-button size="small" text type="danger" @click="removeCase(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <VirtualCaseSubmitDialog
      v-if="submitTarget"
      v-model:visible="submitVisible"
      :case-id="submitTarget.id"
      :receipt-number="submitTarget.receipt_number"
      @submitted="refresh"
    />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑预登记' : '新建预登记'"
      width="1020px"
      top="3vh"
    >
      <el-form label-width="0">
        <div class="form-section">
          <div class="section-title">申请人(每位申请人有独立的仲裁请求和事实理由)</div>
          <div v-for="(p, idx) in applicants" :key="idx" class="party-card">
            <div class="party-card-header">
              <span>申请人 {{ idx + 1 }}</span>
              <el-button size="small" text type="danger" :disabled="applicants.length <= 1" @click="removeItem(applicants, idx)">
                删除
              </el-button>
            </div>
            <div class="field-grid">
              <div class="field">
                <label>姓名 *</label>
                <el-input v-model="p.name" placeholder="请输入姓名" />
              </div>
              <div class="field">
                <label>性别</label>
                <el-select v-model="p.gender" clearable placeholder="选择">
                  <el-option label="男" value="男" />
                  <el-option label="女" value="女" />
                </el-select>
              </div>
              <div class="field">
                <label>民族</label>
                <el-input v-model="p.ethnicity" placeholder="请输入民族" />
              </div>
              <div class="field">
                <label>出生日期</label>
                <el-date-picker v-model="p.birth_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
              </div>
              <div class="field span2 with-action">
                <label>身份证号码</label>
                <div class="inline-input">
                  <el-input v-model="p.id_number" placeholder="请输入身份证号码" />
                  <el-button
                    size="small"
                    :loading="queryingKey === `a-${idx}`"
                    title="按身份证号查询自然人信息并自动填充"
                    @click="lookup(p, `a-${idx}`)"
                  >
                    查询
                  </el-button>
                </div>
              </div>
              <div class="field">
                <label>联系电话</label>
                <el-input v-model="p.phone" placeholder="请输入联系电话" />
              </div>
              <div class="field span2">
                <label>住址</label>
                <el-input v-model="p.address" placeholder="请输入详细住址" />
              </div>
              <div class="field">
                <label>工作地点(公司)</label>
                <el-input v-model="p.work_place" placeholder="请输入工作地点" />
              </div>
              <div class="field">
                <label>岗位</label>
                <el-input v-model="p.position" placeholder="如:电工、技术员等" />
              </div>
              <div class="field">
                <label>入职时间</label>
                <el-date-picker v-model="p.entry_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
              </div>
              <div class="field">
                <label>月工资(元)</label>
                <el-input v-model="p.monthly_wage" placeholder="请输入数额,如:5000" />
              </div>
              <div class="field">
                <label>签订劳动合同</label>
                <el-switch
                  v-model="p.is_sign_labor_contract"
                  :active-value="1"
                  :inactive-value="0"
                  active-text="是"
                  inactive-text="否"
                />
              </div>
              <div class="field">
                <label>缴纳社保</label>
                <el-switch
                  v-model="p.is_pay_social_insurance"
                  :active-value="1"
                  :inactive-value="0"
                  active-text="是"
                  inactive-text="否"
                />
              </div>
              <div class="field span4">
                <label>仲裁请求(选类型+金额自动生成文本,可编辑;申请书/保存内网按结构化数据提取)</label>
                <PartyRequestsEditor
                  :rows="p.reqRows!"
                  :catalog="catalog"
                  :applicant-seq="idx + 1"
                  :applicant-count="applicants.length"
                  :respondent-count="respondents.length"
                />
              </div>
              <div class="field span4">
                <label>事实理由要素(与入职/地点/岗位/工资/合同/社保一起按内网规则自动拼接)</label>
                <el-checkbox-group v-model="p.main_causes">
                  <el-checkbox
                    v-for="c in mainCausePresets"
                    :key="c"
                    :value="c"
                    class="cause-checkbox"
                  >
                    {{ c }}
                  </el-checkbox>
                </el-checkbox-group>
                <div class="cause-other">
                  <span class="cause-other-label">其他主因</span>
                  <el-input v-model="p.causeOther" placeholder="选填,自定义主要原因" />
                </div>
                <el-input
                  v-model="p.facts"
                  type="textarea"
                  :rows="2"
                  placeholder="补充事实(选填),如受伤/离职经过等;拼接在自动生成文本的合同社保段之后"
                  style="margin-top: 6px"
                />
                <div class="facts-preview">
                  <span class="facts-preview-label">自动生成预览(保存内网/申请书按此拼接,提交时可再编辑):</span>
                  {{ factsPreview(p, idx) }}
                </div>
              </div>
              <div class="field span4">
                <label>代理人(选填,保存内网时随当事人一并保存)</label>
                <PartyAgentsEditor v-model="p.agents" />
              </div>
            </div>
          </div>
          <el-button size="small" text type="primary" @click="addItem(applicants, emptyApplicant())">+ 添加申请人</el-button>
        </div>

        <div class="form-section">
          <div class="section-title">被申请人(用人单位)</div>
          <div v-for="(p, idx) in respondents" :key="idx" class="party-card">
            <div class="party-card-header">
              <span>被申请人 {{ idx + 1 }}</span>
              <el-button size="small" text type="danger" :disabled="respondents.length <= 1" @click="removeItem(respondents, idx)">
                删除
              </el-button>
            </div>
            <div class="field-grid">
              <div class="field span2 with-action">
                <label>单位名称 *</label>
                <div class="inline-input">
                  <el-input v-model="p.name" placeholder="请输入用人单位全称" />
                  <el-button
                    size="small"
                    :loading="queryingKey === `r-${idx}`"
                    title="按企业全名或统一社会信用代码查询并自动填充"
                    @click="lookup(p, `r-${idx}`)"
                  >
                    查询
                  </el-button>
                </div>
              </div>
              <div class="field span2">
                <label>统一社会信用代码</label>
                <el-input v-model="p.id_number" placeholder="请输入统一社会信用代码" />
              </div>
              <div class="field">
                <label>法定代表人</label>
                <el-input v-model="p.legal_person" placeholder="请输入法定代表人姓名" />
              </div>
              <div class="field">
                <label>职务</label>
                <el-input v-model="p.legal_title" placeholder="请输入法定代表人职务" />
              </div>
              <div class="field span2">
                <label>住所</label>
                <el-input v-model="p.address" placeholder="请输入用人单位地址" />
              </div>
              <div class="field">
                <label>联系电话</label>
                <el-input v-model="p.phone" placeholder="请输入用人单位联系电话" />
              </div>
              <div class="field span4">
                <label>代理人(选填,保存内网时随当事人一并保存)</label>
                <PartyAgentsEditor v-model="p.agents" />
              </div>
            </div>
          </div>
          <el-button size="small" text type="primary" @click="addItem(respondents, emptyRespondent())">+ 添加被申请人</el-button>
        </div>

        <div class="form-section">
          <div class="section-title">证据清单</div>
          <div v-for="(e, idx) in evidences" :key="idx" class="evidence-row">
            <el-input v-model="e.name" placeholder="证据名称,如:劳动合同" style="width: 220px" />
            <el-input v-model="e.content" placeholder="证明内容,如:证明劳动关系" style="flex: 1" />
            <el-input v-model="e.pages" placeholder="页码" style="width: 90px" />
            <el-button size="small" text type="danger" @click="removeItem(evidences, idx)">删除</el-button>
          </div>
          <el-button size="small" text type="primary" @click="addItem(evidences, { name: '', content: null, pages: null })">
            + 添加证据
          </el-button>
        </div>

        <div class="form-section">
          <div class="section-title">备注</div>
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="其他需要记录的信息" />
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <CaseTagDialog v-model="tagDialogVisible" :subject-key="tagSubjectKey" :title="tagTitle" />
  </div>
</template>

<style scoped>
.vc-header h2 {
  margin: 0 0 4px;
}

.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0 0 16px;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.form-section {
  margin-bottom: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
  padding-left: 8px;
  border-left: 3px solid var(--accent-blue);
}

.party-card {
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
}

.party-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px 12px;
}

.field label {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.field.span2 {
  grid-column: span 2;
}

.field.span4 {
  grid-column: span 4;
}

.inline-input {
  display: flex;
  gap: 6px;
}

.evidence-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
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

.facts-preview {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  background: #f8fafc;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 8px 10px;
  white-space: pre-wrap;
}

.facts-preview-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
