<script setup lang="ts">
/** 企业委托代理人数据库查询面板（用于预登记"保存到内网"页右侧）。 */
import { ElMessage } from "element-plus";
import { Search } from "@element-plus/icons-vue";
import { ref, computed, watch } from "vue";

import * as companyAgentApi from "@/api/companyAgent";
import type { AgentInfo, CaseInfo } from "@/api/companyAgent";

type SearchMode = "company" | "agent";

const searchMode = ref<SearchMode>("company");
const searchKeyword = ref("");
const loading = ref(false);

// 自动补全选项
const companyOptions = ref<string[]>([]);
const agentOptions = ref<string[]>([]);
const autocompleteLoading = ref(false);

// 按公司查询结果
const companyAgents = ref<AgentInfo[]>([]);
const companyName = ref("");

// 按代理人查询结果
const agentCases = ref<CaseInfo[]>([]);
const agentName = ref("");

// 监听搜索模式切换，清空输入框和结果
watch(searchMode, () => {
  searchKeyword.value = "";
  companyAgents.value = [];
  agentCases.value = [];
  companyName.value = "";
  agentName.value = "";
});

// 自动补全查询
async function handleAutocomplete(queryString: string, cb: (results: any[]) => void) {
  if (!queryString || queryString.trim().length < 1) {
    cb([]);
    return;
  }

  try {
    autocompleteLoading.value = true;
    let suggestions: string[] = [];

    if (searchMode.value === "company") {
      suggestions = await companyAgentApi.autocompleteCompanies(queryString);
    } else {
      suggestions = await companyAgentApi.autocompleteAgents(queryString);
    }

    cb(suggestions.map((name) => ({ value: name })));
  } catch (err) {
    console.error("自动补全失败:", err);
    cb([]);
  } finally {
    autocompleteLoading.value = false;
  }
}

function formatDate(isoDate: string | null): string {
  if (!isoDate) return "-";
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

async function search() {
  const keyword = searchKeyword.value.trim();
  if (!keyword) {
    ElMessage.warning("请输入搜索关键词");
    return;
  }

  loading.value = true;
  try {
    if (searchMode.value === "company") {
      const res = await companyAgentApi.getAgentsByCompany(keyword);
      companyAgents.value = res.agents;
      companyName.value = res.company_name;
      agentCases.value = [];
      agentName.value = "";
    } else {
      const res = await companyAgentApi.getCasesByAgent(keyword);
      agentCases.value = res.cases;
      agentName.value = res.agent_name;
      companyAgents.value = [];
      companyName.value = "";
    }
  } catch {
    ElMessage.error("查询失败，请稍后重试");
  } finally {
    loading.value = false;
  }
}

function onEnter() {
  search();
}

// 按公司查询时，代理人分组（同一代理人的所有案件合并）
interface AgentGroup {
  agent_name: string;
  agent_type_label: string;
  agent_phone: string | null;
  agent_law_firm: string | null;
  cases: { case_no: string | null; filed_at: string | null; external_case_id: string }[];
}

const groupedAgents = computed(() => {
  const map = new Map<string, AgentGroup>();

  for (const a of companyAgents.value) {
    if (!map.has(a.agent_name)) {
      map.set(a.agent_name, {
        agent_name: a.agent_name,
        agent_type_label: a.agent_type_label,
        agent_phone: a.agent_phone,
        agent_law_firm: a.agent_law_firm,
        cases: [],
      });
    }
    const group = map.get(a.agent_name)!;
    group.cases.push({
      case_no: a.case_no,
      filed_at: a.filed_at,
      external_case_id: a.external_case_id,
    });
  }

  return Array.from(map.values());
});
</script>

<template>
  <div class="company-agent-database-panel">
    <div class="panel-header">
      <h3>企业委托代理人数据库</h3>
    </div>

    <div class="search-section">
      <el-radio-group v-model="searchMode" size="small" style="margin-bottom: 12px">
        <el-radio-button value="company">按公司查询</el-radio-button>
        <el-radio-button value="agent">按代理人查询</el-radio-button>
      </el-radio-group>

      <el-autocomplete
        v-model="searchKeyword"
        :fetch-suggestions="handleAutocomplete"
        :placeholder="searchMode === 'company' ? '输入公司名称' : '输入代理人姓名'"
        :trigger-on-focus="false"
        :debounce="300"
        :teleported="false"
        popper-class="company-agent-autocomplete"
        clearable
        @keyup.enter="onEnter"
        @select="search"
      >
        <template #append>
          <el-button :icon="Search" :loading="loading" @click="search">搜索</el-button>
        </template>
      </el-autocomplete>
    </div>

    <!-- 按公司查询结果 -->
    <div v-if="companyAgents.length > 0" class="results-section">
      <div class="results-header">
        <span class="company-name">{{ companyName }}</span>
        <span class="total-count">共 {{ companyAgents.length }} 条记录</span>
      </div>

      <div v-for="group in groupedAgents" :key="group.agent_name" class="agent-group">
        <div class="agent-info">
          <div class="agent-name">{{ group.agent_name }}</div>
          <div class="agent-detail">
            <span class="agent-type">{{ group.agent_type_label }}</span>
            <span v-if="group.agent_law_firm" class="agent-firm">{{ group.agent_law_firm }}</span>
            <span v-if="group.agent_phone" class="agent-phone">{{ group.agent_phone }}</span>
          </div>
        </div>
        <div class="case-list">
          <div v-for="(c, idx) in group.cases" :key="idx" class="case-item">
            <span class="case-no">{{ c.case_no || "无案号" }}</span>
            <span class="filed-date">{{ formatDate(c.filed_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 按代理人查询结果 -->
    <div v-if="agentCases.length > 0" class="results-section">
      <div class="results-header">
        <span class="agent-name-title">{{ agentName }}</span>
        <span class="total-count">共代理 {{ agentCases.length }} 个案件</span>
      </div>

      <div v-for="(c, idx) in agentCases" :key="idx" class="case-group">
        <div class="company-info">
          <div class="company-name-title">{{ c.company_name }}</div>
          <div class="company-detail">
            <span class="agent-type">{{ c.agent_type_label }}</span>
            <span v-if="c.agent_law_firm" class="agent-firm">{{ c.agent_law_firm }}</span>
          </div>
        </div>
        <div class="case-detail">
          <span class="case-no">{{ c.case_no || "无案号" }}</span>
          <span class="filed-date">{{ formatDate(c.filed_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div
      v-if="
        !loading &&
        companyAgents.length === 0 &&
        agentCases.length === 0 &&
        (companyName || agentName)
      "
      class="empty-state"
    >
      <p>未找到相关记录</p>
    </div>
  </div>
</template>

<style scoped>
.company-agent-database-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.panel-header {
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.search-section {
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
  position: relative;
}

.results-section {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid #3b82f6;
}

.company-name,
.agent-name-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
}

.total-count {
  font-size: 13px;
  color: #6b7280;
}

.agent-group {
  margin-bottom: 20px;
  padding: 12px;
  background: #f9fafb;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}

.agent-info {
  margin-bottom: 8px;
}

.agent-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 4px;
}

.agent-detail {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: #6b7280;
}

.agent-type {
  color: #3b82f6;
}

.agent-firm {
  color: #10b981;
}

.agent-phone {
  color: #6b7280;
}

.case-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.case-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  background: white;
  border-radius: 4px;
  font-size: 13px;
}

.case-no {
  color: #1f2937;
}

.filed-date {
  color: #9ca3af;
}

.case-group {
  margin-bottom: 16px;
  padding: 12px;
  background: #f9fafb;
  border-radius: 6px;
  border-left: 3px solid #10b981;
}

.company-info {
  margin-bottom: 8px;
}

.company-name-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 4px;
  display: block;
}

.company-detail {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: #6b7280;
}

.case-detail {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  background: white;
  border-radius: 4px;
  font-size: 13px;
  margin-top: 8px;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 14px;
}

/* 自动补全下拉菜单样式修正 */
:deep(.el-autocomplete) {
  width: 100%;
}

:deep(.company-agent-autocomplete) {
  width: 100% !important;
}
</style>

