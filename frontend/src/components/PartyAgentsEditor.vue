<script setup lang="ts">
import { ElMessage } from "element-plus";
import { ref } from "vue";

import * as api from "@/api/virtualCases";
import type { Agent, AgentRecord } from "@/api/virtualCases";

/** 代理人编辑器(当事人卡片内嵌)。常量与内网前端写死的字典一致
 * (后端 case_submit.AGENT_TYPES/AGENT_RELATIONS/AGENT_AUTHS/LAWYER_TYPES)。 */
const props = defineProps<{ modelValue: Agent[] }>();
const emit = defineEmits<{ "update:modelValue": [value: Agent[]] }>();

const AGENT_TYPES = [
  { code: 1, label: "法定代理人" },
  { code: 2, label: "指定代理人" },
  { code: 3, label: "近亲属" },
  { code: 4, label: "有关的社会团体或者当事人所在单位推荐的人" },
  { code: 5, label: "单位工作人员" },
  { code: 6, label: "律师" },
  { code: 7, label: "法律服务工作者" },
];
const RELATIONS = ["配偶", "父亲", "母亲", "儿子", "女儿", "其他"];
const AUTHS = ["一般授权", "特别授权"];
const LAWYER_TYPES = [
  { code: 1, label: "执业律师" },
  { code: 2, label: "实习律师" },
];

function emptyAgent(): Agent {
  return {
    name: "",
    agent_type: 6,
    id_type: "居民身份证（户口簿）",
    id_number: null,
    mobile: null,
    sex: null,
    relation: null,
    select_other_content: null,
    agent_auth: null,
    law_firm_name: null,
    lawer_type: null,
    is_legal_aid: 0,
    lawyer_card_number: null,
    address: null,
    receive_address: null,
    job: null,
  };
}

function isLawyer(a: Agent) {
  return a.agent_type === 6 || a.agent_type === 7;
}

// 手动切换类型时同样清理互斥字段组(与 pick 回填一致)。
function onTypeChange(a: Agent) {
  if (isLawyer(a)) {
    a.relation = null;
    a.select_other_content = null;
  } else {
    a.law_firm_name = null;
    a.lawer_type = null;
    a.is_legal_aid = null;
    a.lawyer_card_number = null;
    a.agent_auth = null;
    a.receive_address = null;
  }
}

function add() {
  emit("update:modelValue", [...props.modelValue, emptyAgent()]);
}

function remove(idx: number) {
  const next = [...props.modelValue];
  next.splice(idx, 1);
  emit("update:modelValue", next);
}

// ---- 系统内查询(cases/Agent) ----

const queryVisible = ref(false);
const queryTarget = ref<Agent | null>(null);
const queryKeyword = ref("");
const queryLoading = ref(false);
const queryResults = ref<AgentRecord[]>([]);

function openQuery(agent: Agent) {
  queryTarget.value = agent;
  queryKeyword.value = agent.name || "";
  queryResults.value = [];
  queryVisible.value = true;
}

async function doQuery() {
  if (!queryKeyword.value.trim()) {
    ElMessage.warning("请输入姓名/身份证号/手机号");
    return;
  }
  queryLoading.value = true;
  try {
    const kw = queryKeyword.value.trim();
    const params = /^(\d{15}|\d{17}[\dXx])$/.test(kw)
      ? { id_number: kw }
      : /^1\d{10}$/.test(kw)
        ? { mobile: kw }
        : { name: kw };
    const body = await api.lookupAgent(params);
    queryResults.value = body?.data ?? [];
    if (!queryResults.value.length) {
      ElMessage.warning("未查到匹配的代理人登记记录");
    }
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail ?? "查询失败,请稍后重试");
  } finally {
    queryLoading.value = false;
  }
}

function agentTypeOf(rec: AgentRecord): number {
  const t = (rec.type ?? []).filter((x): x is number => typeof x === "number");
  return t.length ? t[t.length - 1] : 6;
}

function pick(rec: AgentRecord) {
  const a = queryTarget.value;
  if (!a) return;
  a.name = rec.name || a.name;
  a.agent_type = agentTypeOf(rec);
  a.id_type = rec.id_type || a.id_type;
  a.id_number = rec.id_number || a.id_number;
  a.mobile = rec.mobile || a.mobile;
  a.sex = rec.sex || a.sex;
  a.agent_auth = rec.agent_auth || a.agent_auth;
  a.relation = rec.relation || a.relation;
  a.select_other_content = rec.select_other_content || a.select_other_content;
  a.law_firm_name = rec.law_firm_name || a.law_firm_name;
  a.lawer_type = rec.lawer_type ?? a.lawer_type;
  a.is_legal_aid = rec.is_legal_aid ?? a.is_legal_aid;
  a.lawyer_card_number = rec.lawyer_card_number || a.lawyer_card_number;
  a.address = rec.address || rec.registered_permanent_residence || a.address;
  a.receive_address = rec.receive_address || a.receive_address;
  a.job = rec.job || a.job;
  // 律师类与非法律类的专属字段互斥,清掉不适用组,避免不可见脏数据随提交。
  if (isLawyer(a)) {
    a.relation = null;
    a.select_other_content = null;
  } else {
    a.law_firm_name = null;
    a.lawer_type = null;
    a.is_legal_aid = null;
    a.lawyer_card_number = null;
    a.agent_auth = null;
    a.receive_address = null;
  }
  queryVisible.value = false;
  ElMessage.success(`已回填:${rec.name}`);
}

function typeLabel(code: number) {
  return AGENT_TYPES.find((t) => t.code === code)?.label ?? String(code);
}
</script>

<template>
  <div class="agents-editor">
    <div v-for="(a, idx) in modelValue" :key="idx" class="agent-card">
      <div class="agent-card-header">
        <span>代理人 {{ idx + 1 }}<template v-if="a.name">:{{ a.name }}</template></span>
        <div>
          <el-button size="small" text type="primary" @click="openQuery(a)">系统内查询</el-button>
          <el-button size="small" text type="danger" @click="remove(idx)">删除</el-button>
        </div>
      </div>
      <div class="agent-grid">
        <div class="field">
          <label>代理人类型 *</label>
          <el-select v-model="a.agent_type" @change="onTypeChange(a)">
            <el-option v-for="t in AGENT_TYPES" :key="t.code" :label="t.label" :value="t.code" />
          </el-select>
        </div>
        <div class="field">
          <label>姓名 *</label>
          <el-input v-model="a.name" placeholder="代理人姓名" />
        </div>
        <div class="field">
          <label>性别</label>
          <el-select v-model="a.sex" clearable placeholder="选择">
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </div>
        <div class="field">
          <label>联系方式</label>
          <el-input v-model="a.mobile" placeholder="手机号" />
        </div>
        <div class="field">
          <label>证件类型</label>
          <el-input v-model="a.id_type" placeholder="居民身份证（户口簿）" />
        </div>
        <div class="field">
          <label>证件号码</label>
          <el-input v-model="a.id_number" placeholder="证件号码" />
        </div>
        <div class="field span2">
          <label>住址</label>
          <el-input v-model="a.address" placeholder="住址" />
        </div>
        <template v-if="!isLawyer(a)">
          <div class="field">
            <label>与当事人关系</label>
            <el-select v-model="a.relation" clearable placeholder="选择">
              <el-option v-for="r in RELATIONS" :key="r" :label="r" :value="r" />
            </el-select>
          </div>
          <div v-if="a.relation === '其他'" class="field">
            <label>关系说明</label>
            <el-input v-model="a.select_other_content" placeholder="如:员工" />
          </div>
        </template>
        <template v-if="isLawyer(a)">
          <div class="field">
            <label>委托权限</label>
            <el-select v-model="a.agent_auth" clearable placeholder="选择">
              <el-option v-for="t in AUTHS" :key="t" :label="t" :value="t" />
            </el-select>
          </div>
          <div class="field">
            <label>律师类型</label>
            <el-select v-model="a.lawer_type" clearable placeholder="选择">
              <el-option v-for="t in LAWYER_TYPES" :key="t.code" :label="t.label" :value="t.code" />
            </el-select>
          </div>
          <div class="field span2">
            <label>律师事务所名称</label>
            <el-input v-model="a.law_firm_name" placeholder="律所全称" />
          </div>
          <div class="field">
            <label>执业证号</label>
            <el-input v-model="a.lawyer_card_number" placeholder="选填" />
          </div>
          <div class="field">
            <label>法律援助</label>
            <el-switch
              :model-value="a.is_legal_aid === 1"
              active-text="是"
              inactive-text="否"
              @update:model-value="a.is_legal_aid = $event ? 1 : 0"
            />
          </div>
          <div class="field span2">
            <label>送达地址</label>
            <el-input v-model="a.receive_address" placeholder="选填" />
          </div>
        </template>
      </div>
    </div>
    <el-button size="small" text type="primary" @click="add">+ 添加代理人</el-button>

    <el-dialog v-model="queryVisible" title="系统内查询代理人" width="640px" append-to-body>
      <div class="query-bar">
        <el-input
          v-model="queryKeyword"
          placeholder="姓名 / 身份证号 / 手机号"
          clearable
          @keyup.enter="doQuery"
        />
        <el-button type="primary" :loading="queryLoading" @click="doQuery">查询</el-button>
      </div>
      <el-table v-loading="queryLoading" :data="queryResults" empty-text="输入关键词查询" max-height="320">
        <el-table-column label="姓名" prop="name" width="90" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ typeLabel(agentTypeOf(row)) }}</template>
        </el-table-column>
        <el-table-column label="律所/关系" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.law_firm_name || row.relation || "-" }}</template>
        </el-table-column>
        <el-table-column label="手机号" prop="mobile" width="120" />
        <el-table-column label="委托权限" prop="agent_auth" width="90" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="pick(row)">选择</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.agent-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.agent-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px 12px;
}

.field label {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.field.span2 {
  grid-column: span 2;
}

.query-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
</style>
