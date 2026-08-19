<script setup lang="ts">
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";

import {
  getTianyanchaConfig,
  lookupCompany,
  lookupCompanyDetails,
  updateTianyanchaConfig,
  type CompanyDetails,
  type TianyanchaCompanyResult,
  type TianyanchaConfig,
} from "@/api/tianyancha";

const query = ref("");
const loading = ref(false);
const result = ref<TianyanchaCompanyResult | null>(null);
const details = ref<CompanyDetails | null>(null);
const detailsLoading = ref(false);
const detailsCompanyName = ref("");

const config = ref<TianyanchaConfig>({
  configured: false,
  api_key_masked: "",
  source: null,
});
const apiKeyInput = ref("");
const savingKey = ref(false);

async function loadConfig() {
  try {
    const body = await getTianyanchaConfig();
    if (body?.data) config.value = body.data;
  } catch {
    // 配置接口失败不阻塞查询
  }
}

async function saveKey() {
  savingKey.value = true;
  try {
    const body = await updateTianyanchaConfig(apiKeyInput.value.trim());
    if (body?.data) config.value = body.data;
    apiKeyInput.value = "";
    ElMessage.success("API Key 已保存");
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response
      ?.data?.detail;
    ElMessage.error(detail || "保存失败，请稍后重试");
  } finally {
    savingKey.value = false;
  }
}

onMounted(loadConfig);

const rawText = computed(() =>
  result.value?.raw == null ? "" : String(result.value.raw),
);

const columns = computed(() => {
  const first = result.value?.fields?.[0];
  return first ? Object.keys(first) : [];
});

// 精确命中:公司名称 / 信用代码直接匹配;其余(股东/历史/关联等)归入关联候选。
const EXACT_MATCH_TYPES = new Set(["公司名称匹配", "信用代码匹配"]);

const hasMatchType = computed(() =>
  result.value?.fields?.some((f) => "匹配类型" in f) ?? false,
);

const exactFields = computed(() => {
  const fields = result.value?.fields ?? [];
  if (!hasMatchType.value) return fields;
  return fields.filter((f) => EXACT_MATCH_TYPES.has(String(f["匹配类型"])));
});

const relatedFields = computed(() => {
  const fields = result.value?.fields ?? [];
  if (!hasMatchType.value) return [];
  return fields.filter((f) => !EXACT_MATCH_TYPES.has(String(f["匹配类型"])));
});

async function doSearch() {
  const kw = query.value.trim();
  if (!kw) {
    ElMessage.warning("请输入企业名称或统一社会信用代码");
    return;
  }
  loading.value = true;
  details.value = null;
  detailsCompanyName.value = "";
  try {
    const body = await lookupCompany(kw);
    result.value = body?.data ?? null;
    if (!result.value || (result.value.fields.length === 0 && result.value.raw == null)) {
      ElMessage.warning("未查到匹配的企业信息");
    }
  } catch (err) {
    result.value = null;
    const detail = (err as { response?: { data?: { detail?: string } } })?.response
      ?.data?.detail;
    ElMessage.error(detail || "查询失败，请稍后重试");
  } finally {
    loading.value = false;
  }
}

async function loadDetails(name: string) {
  const n = (name || "").trim();
  if (!n) {
    ElMessage.warning("未找到可查看的企业名称");
    return;
  }
  detailsLoading.value = true;
  detailsCompanyName.value = n;
  try {
    const body = await lookupCompanyDetails(n);
    details.value = body?.data ?? null;
    if (
      !details.value ||
      (details.value.overview.length === 0 &&
        details.value.details.length === 0 &&
        details.value.raw == null)
    ) {
      ElMessage.warning("未查到企业详情");
    }
  } catch (err) {
    details.value = null;
    const detail = (err as { response?: { data?: { detail?: string } } })?.response
      ?.data?.detail;
    ElMessage.error(detail || "详情查询失败，请稍后重试");
  } finally {
    detailsLoading.value = false;
  }
}
</script>

<template>
  <div class="tianyancha-page">
    <div class="page-header">
      <h2>天眼查</h2>
      <p class="page-subtitle">按企业名称或统一社会信用代码查询工商基本信息（数据来自天眼查 MCP）。</p>
    </div>

    <el-card shadow="never" class="search-card">
      <div class="config-row">
        <div class="config-info">
          <div class="config-title">
            API Key
            <el-tag v-if="config.configured" size="small" type="success" effect="plain">已配置</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">未配置</el-tag>
          </div>
          <div class="config-sub">
            <template v-if="config.configured">
              当前：{{ config.api_key_masked }}
              <span class="source-tag">（{{ config.source === "db" ? "页面保存" : ".env 配置" }}）</span>
            </template>
            <template v-else>尚未配置 API Key，请填写后保存；未配置时查询会提示「未配置」。</template>
          </div>
        </div>
        <div class="config-input">
          <el-input
            v-model="apiKeyInput"
            type="password"
            show-password
            :placeholder="config.configured ? '留空保存则清除当前配置' : '粘贴天眼查 API Key'"
            @keyup.enter="saveKey"
          />
          <el-button type="primary" :loading="savingKey" @click="saveKey">保存</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <el-input
          v-model="query"
          clearable
          placeholder="输入企业全称或统一社会信用代码，如：乐视网信息技术（北京）股份有限公司"
          class="search-input"
          @keyup.enter="doSearch"
        />
        <el-button type="primary" :loading="loading" @click="doSearch">查询</el-button>
      </div>
    </el-card>

    <template v-if="result">
      <div v-if="result.tool" class="tool-hint">命中工具：{{ result.tool }}</div>

      <el-card v-if="exactFields.length" shadow="never" class="result-card">
        <div class="section-title">精确匹配</div>
        <el-table :data="exactFields" border>
          <el-table-column
            v-for="col in columns"
            :key="col"
            :prop="col"
            :label="col"
            :min-width="col === '企业名称' ? 220 : 120"
            show-overflow-tooltip
          />
          <el-table-column label="操作" width="100" fixed="right" align="center">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                :loading="detailsLoading && detailsCompanyName === row['企业名称']"
                @click="loadDetails(String(row['企业名称']))"
              >查看详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card v-if="details" shadow="never" class="result-card">
        <div class="section-title">
          企业详情
          <span v-if="details.company_name" class="detail-company">{{ details.company_name }}</span>
        </div>
        <el-descriptions v-if="details.overview.length" :column="1" border>
          <el-descriptions-item
            v-for="f in details.overview"
            :key="f['字段']"
            :label="f['字段']"
            label-width="140px"
          >{{ f["值"] }}</el-descriptions-item>
        </el-descriptions>
        <div v-for="t in details.details" :key="t.title" class="detail-section">
          <div class="detail-title">{{ t.title }}</div>
          <el-table :data="t.rows" border>
            <el-table-column
              v-for="h in t.headers"
              :key="h"
              :prop="h"
              :label="h"
              :min-width="h === '联系电话' || h === '来源' ? 140 : 110"
              show-overflow-tooltip
            />
          </el-table>
        </div>
        <el-collapse v-if="details.raw != null" class="detail-raw">
          <el-collapse-item title="原始数据" name="raw">
            <pre class="raw-text">{{ details.raw }}</pre>
          </el-collapse-item>
        </el-collapse>
      </el-card>

      <el-card v-if="relatedFields.length" shadow="never" class="result-card">
        <el-collapse>
          <el-collapse-item :title="`关联候选（${relatedFields.length}）`" name="related">
            <el-table :data="relatedFields" border>
              <el-table-column
                v-for="col in columns"
                :key="col"
                :prop="col"
                :label="col"
                :min-width="col === '企业名称' ? 220 : 120"
                show-overflow-tooltip
              />
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </el-card>

      <el-card v-if="result.raw != null" shadow="never" class="result-card">
        <el-collapse>
          <el-collapse-item title="原始数据" name="raw">
            <pre class="raw-text">{{ rawText }}</pre>
          </el-collapse-item>
        </el-collapse>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
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

.search-card {
  margin-bottom: 16px;
}
.config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}
.config-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.config-sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}
.source-tag {
  color: var(--el-text-color-secondary);
}
.config-input {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 360px;
  flex: 1;
  max-width: 560px;
}
.search-row {
  display: flex;
  gap: 12px;
}
.search-input {
  flex: 1;
}

.tool-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 0 0 8px;
}

.result-card {
  margin-bottom: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
}

.detail-company {
  font-size: 13px;
  font-weight: normal;
  color: var(--el-text-color-secondary);
  margin-left: 8px;
}

.detail-section {
  margin-top: 16px;
}
.detail-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}
.detail-raw {
  margin-top: 16px;
}

.raw-text {
  margin: 0;
  padding: 12px;
  background: #f7f9fc;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  overflow: auto;
  max-height: 360px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
