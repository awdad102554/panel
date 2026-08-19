<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, reactive, ref } from "vue";

import * as modelApi from "@/api/aiModel";
import type { AIModelConfig } from "@/types";
import { DEFAULT_MAX_TOKENS, lookupModelMaxTokens } from "@/utils/modelPresets";

const models = ref<AIModelConfig[]>([]);
const activeModel = ref<AIModelConfig | null>(null);
const loading = ref(false);

const dialogVisible = ref(false);
const editingId = ref<string | null>(null);
const submitting = ref(false);

const providerOptions = [
  { label: "OpenAI", value: "openai" },
  { label: "通义千问 Qwen", value: "qwen" },
  { label: "DeepSeek", value: "deepseek" },
  { label: "Azure OpenAI", value: "azure_openai" },
  { label: "自定义 Custom", value: "custom" },
];

const form = reactive({
  name: "",
  provider: "openai",
  base_url: "",
  api_key: "",
  model_name: "",
  temperature: 0.2 as number | null,
  max_tokens: DEFAULT_MAX_TOKENS as number | null,
  supports_vision: false,
  remark: "",
});

/** 用户手动改过最大输出后,不再随模型名自动覆盖。 */
const maxTokensTouched = ref(false);

function onModelNameInput() {
  if (maxTokensTouched.value) return;
  const preset = lookupModelMaxTokens(form.model_name);
  if (preset !== null) form.max_tokens = preset;
}

function resetForm() {
  form.name = "";
  form.provider = "openai";
  form.base_url = "";
  form.api_key = "";
  form.model_name = "";
  form.temperature = 0.2;
  form.max_tokens = DEFAULT_MAX_TOKENS;
  form.supports_vision = false;
  form.remark = "";
  maxTokensTouched.value = false;
}

async function refresh() {
  loading.value = true;
  try {
    [models.value, activeModel.value] = await Promise.all([
      modelApi.listModels(),
      modelApi.getActiveModel(),
    ]);
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: AIModelConfig) {
  editingId.value = row.id;
  form.name = row.name;
  form.provider = row.provider;
  form.base_url = row.base_url;
  form.api_key = "";
  form.model_name = row.model_name;
  form.temperature = row.temperature;
  form.max_tokens = row.max_tokens ?? DEFAULT_MAX_TOKENS;
  form.supports_vision = row.supports_vision;
  form.remark = row.remark ?? "";
  // 编辑已有配置:保留已存的上限,不随模型名重新触发自动填入。
  maxTokensTouched.value = true;
  dialogVisible.value = true;
}

async function handleSubmit() {
  submitting.value = true;
  try {
    if (editingId.value) {
      const payload: modelApi.AIModelPayload = { ...form };
      if (!payload.api_key) delete payload.api_key;
      await modelApi.updateModel(editingId.value, payload);
      ElMessage.success("已更新模型配置");
    } else {
      await modelApi.createModel({ ...form });
      ElMessage.success("已新增模型配置");
    }
    dialogVisible.value = false;
    await refresh();
  } catch {
    ElMessage.error("保存失败,请重试");
  } finally {
    submitting.value = false;
  }
}

async function handleEnable(row: AIModelConfig) {
  try {
    await modelApi.enableModel(row.id);
    ElMessage.success(`已启用「${row.name}」`);
    await refresh();
  } catch {
    ElMessage.error("启用失败,请重试");
  }
}

async function handleDelete(row: AIModelConfig) {
  try {
    await modelApi.deleteModel(row.id);
    ElMessage.success("已删除");
    await refresh();
  } catch {
    ElMessage.error("删除失败,请重试");
  }
}

onMounted(refresh);
</script>

<template>
  <div class="model-manage">
    <div class="page-header">
      <h2>模型管理</h2>
      <p class="page-subtitle">配置 AI 模型接入信息（供应商 / 接口地址 / 密钥 / 模型名），同一时刻仅一个配置生效。</p>
    </div>

    <div class="active-bar">
      <span class="active-label">当前生效模型：</span>
      <el-tag v-if="activeModel" type="primary" effect="dark" class="active-tag">
        {{ activeModel.name }}（{{ activeModel.model_name }}）
      </el-tag>
      <span v-else class="active-empty">未配置生效模型，AI 能力当前使用占位（mock）输出</span>
    </div>

    <div class="toolbar">
      <el-button type="primary" @click="openCreate">新增模型</el-button>
    </div>

    <el-table v-loading="loading" :data="models">
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="provider" label="供应商" width="130" />
      <el-table-column prop="model_name" label="模型名" width="150" />
      <el-table-column label="最大输出" width="110">
        <template #default="{ row }">
          {{ row.max_tokens?.toLocaleString() ?? "-" }}
        </template>
      </el-table-column>
      <el-table-column label="图片识别" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.supports_vision" type="success" effect="plain">支持</el-tag>
          <el-tag v-else type="info">不支持</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
      <el-table-column prop="api_key_masked" label="密钥" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.is_enabled" type="primary" effect="dark">启用中</el-tag>
          <el-tag v-else type="info">未启用</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button
            v-if="!row.is_enabled"
            link
            type="primary"
            @click="handleEnable(row)"
          >
            启用
          </el-button>
          <el-button link @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确认删除该模型配置？" @confirm="handleDelete(row)">
            <template #reference>
              <el-button link type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑模型配置' : '新增模型配置'"
      width="520px"
    >
      <el-form :model="form" label-width="96px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：通义千问-生产" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-select v-model="form.provider" style="width: 100%">
            <el-option
              v-for="opt in providerOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="https://.../v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editingId ? '留空则不修改密钥' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input
            v-model="form.model_name"
            placeholder="如：deepseek-v4-pro / qwen3.7-max"
            @input="onModelNameInput"
          />
        </el-form-item>
        <el-form-item label="最大输出">
          <el-input-number
            v-model="form.max_tokens"
            :min="1"
            :max="1048576"
            :step="1024"
            @change="maxTokensTouched = true"
          />
          <span class="field-hint">token；按模型名自动带入主流上限，可手动调整</span>
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="图片识别">
          <el-switch v-model="form.supports_vision" />
          <span class="field-hint">开启后预约审查会发给模型看证件照片核对；关闭则只看照片是否上传</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
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
.active-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fff;
  border-radius: var(--radius-md);
  border-left: 4px solid var(--accent-cyan);
  box-shadow: 0 2px 10px rgba(15, 31, 74, 0.06);
  margin-bottom: 16px;
}
.active-label {
  font-weight: 600;
}
.active-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.toolbar {
  margin-bottom: 16px;
}
.field-hint {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
