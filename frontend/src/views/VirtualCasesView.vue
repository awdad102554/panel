<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import { onMounted, ref } from "vue";

import * as api from "@/api/virtualCases";
import type { Evidence, Party, VirtualCase } from "@/api/virtualCases";
import PartyAgentsEditor from "@/components/PartyAgentsEditor.vue";
import VirtualCaseSubmitDialog from "@/components/VirtualCaseSubmitDialog.vue";

const cases = ref<VirtualCase[]>([]);
const loading = ref(false);

const submitVisible = ref(false);
const submitTarget = ref<VirtualCase | null>(null);

function openSubmit(row: VirtualCase) {
  submitTarget.value = row;
  submitVisible.value = true;
}

const dialogVisible = ref(false);
const editingId = ref<string | null>(null);
const saving = ref(false);

const form = ref({ note: "" });
const applicants = ref<Party[]>([]);
const respondents = ref<Party[]>([]);
const evidences = ref<Evidence[]>([]);

function emptyApplicant(): Party {
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
    requests: [""],
    facts: null,
    legal_person: null,
    legal_title: null,
    agents: [],
  };
}

function emptyRespondent(): Party {
  return { ...emptyApplicant(), party_type: "company" };
}

function openCreate() {
  editingId.value = null;
  form.value = { note: "" };
  applicants.value = [emptyApplicant()];
  respondents.value = [emptyRespondent()];
  evidences.value = [];
  dialogVisible.value = true;
}

function fillRequests(p: Party): string[] {
  if (p.requests?.length) return [...p.requests];
  // 旧数据的单一 claims 文本兼容为一条请求。
  return p.claims ? [p.claims] : [""];
}

function openEdit(row: VirtualCase) {
  editingId.value = row.id;
  form.value = { note: row.note ?? "" };
  applicants.value = row.applicants.map((p) => ({
    ...emptyApplicant(),
    ...p,
    requests: fillRequests(p),
    agents: (p.agents ?? []).map((a) => ({ ...a })),
  }));
  respondents.value = row.respondents.map((p) => ({
    ...emptyRespondent(),
    ...p,
    agents: (p.agents ?? []).map((a) => ({ ...a })),
  }));
  evidences.value = (row.evidences ?? []).map((e) => ({ ...e }));
  dialogVisible.value = true;
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
  saving.value = true;
  try {
    const applicantsClean = applicants.value.map((p) => ({
      ...p,
      requests: (p.requests ?? []).filter((r) => r.trim()),
    }));
    // 被申请人卡片不展示请求行,清掉继承自申请人结构的空 requests,避免脏数据入库。
    const respondentsClean = respondents.value.map((p) => ({ ...p, requests: [] }));
    const payload = {
      case_reason: null,
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

async function markPending(row: VirtualCase) {
  try {
    await api.updateVirtualCaseStatus(row.id, "pending");
    ElMessage.success(`${row.receipt_number} 已恢复为待录入`);
    await refresh();
  } catch (err) {
    ElMessage.error((await extractErrorDetail(err)) ?? "操作失败,请稍后重试");
  }
}

async function removeCase(row: VirtualCase) {
  try {
    await ElMessageBox.confirm(`确定删除预登记案件 ${row.receipt_number}?`, "删除确认", {
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
        当事人信息可通过身份证号/企业名称(或信用代码)调用内部接口查询自动填充。案件信息完整后可点"提交到内网"直接写入内网收件,无需在内网重复录入。
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
      <el-table-column label="操作" width="420">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="primary" plain @click="downloadApplication(row)">生成申请书</el-button>
          <el-button
            v-if="row.status === 'pending'"
            size="small"
            type="success"
            @click="openSubmit(row)"
          >
            提交到内网
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
          <el-button v-else size="small" text @click="markPending(row)">恢复待录入</el-button>
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
              <div class="field span4">
                <div class="requests-header">
                  <label style="margin-bottom: 0">仲裁请求</label>
                  <el-button size="small" text type="primary" @click="p.requests.push('')">+ 添加请求</el-button>
                </div>
                <div v-for="(_req, reqIdx) in p.requests" :key="reqIdx" class="request-row">
                  <span class="request-no">请求 {{ reqIdx + 1 }}</span>
                  <el-input
                    v-model="p.requests[reqIdx]"
                    type="textarea"
                    :rows="2"
                    placeholder="请具体明确地填写仲裁请求,例如:请求裁决被申请人支付拖欠的工资XXXX元。"
                    style="flex: 1"
                  />
                  <el-button
                    size="small"
                    text
                    type="danger"
                    :disabled="p.requests.length <= 1"
                    @click="p.requests.splice(reqIdx, 1)"
                  >
                    删除
                  </el-button>
                </div>
              </div>
              <div class="field span4">
                <label>事实与理由</label>
                <el-input v-model="p.facts" type="textarea" :rows="3" placeholder="请简明扼要叙述仲裁请求的事实依据和法律理由,包括入职时间、工作地点、工资情况、争议经过等。" />
              </div>
              <div class="field span4">
                <label>代理人(选填,提交内网时随当事人一并提交)</label>
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
                <label>代理人(选填,提交内网时随当事人一并提交)</label>
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

.requests-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.request-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 8px;
}

.request-no {
  font-size: 13px;
  color: var(--el-text-color-regular);
  padding-top: 8px;
  width: 48px;
  flex-shrink: 0;
}

.evidence-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>
