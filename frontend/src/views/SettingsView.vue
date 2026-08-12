<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";

import * as settingsApi from "@/api/settings";
import type { TimeLimitItem } from "@/api/settings";

const items = ref<TimeLimitItem[]>([]);
const edited = ref<Record<string, number>>({});
const loading = ref(true);
const saving = ref(false);
const resetting = ref(false);

// 是否有改动/有非默认值(控制按钮可用态)
const dirty = computed(() => items.value.some((i) => edited.value[i.key] !== i.value));
const hasCustom = computed(() => items.value.some((i) => i.value !== i.default));

onMounted(async () => {
  try {
    items.value = await settingsApi.getTimeLimits();
    edited.value = Object.fromEntries(items.value.map((i) => [i.key, i.value]));
  } catch {
    ElMessage.error("时限设置加载失败,请重试");
  } finally {
    loading.value = false;
  }
});

async function save() {
  const updates: Record<string, number> = {};
  for (const i of items.value) {
    if (edited.value[i.key] !== i.value) {
      updates[i.key] = edited.value[i.key];
    }
  }
  saving.value = true;
  try {
    items.value = await settingsApi.updateTimeLimits(updates);
    edited.value = Object.fromEntries(items.value.map((i) => [i.key, i.value]));
    ElMessage.success("时限设置已保存,即时生效");
  } catch {
    ElMessage.error("保存失败,请检查取值范围");
  } finally {
    saving.value = false;
  }
}

async function resetAll() {
  try {
    await ElMessageBox.confirm("确定将全部时限恢复为默认值?", "恢复默认", {
      type: "warning",
      confirmButtonText: "恢复默认",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  resetting.value = true;
  try {
    items.value = await settingsApi.resetTimeLimits();
    edited.value = Object.fromEntries(items.value.map((i) => [i.key, i.value]));
    ElMessage.success("已全部恢复默认值");
  } finally {
    resetting.value = false;
  }
}
</script>

<template>
  <div v-loading="loading" class="settings-view">
    <div class="settings-header">
      <h2>时限设置</h2>
      <p class="settings-sub">调整监控的提醒阈值,保存后即时生效(同步间隔在下轮同步时生效)。法定审限、收件/预约处理时限等业务规则由内网规定,不在此处调整。</p>
    </div>

    <div class="settings-card">
      <div v-for="item in items" :key="item.key" class="limit-row">
        <div class="limit-info">
          <div class="limit-label">
            {{ item.label }}
            <el-tag v-if="item.value !== item.default" size="small" type="warning" effect="plain" class="custom-tag">
              已修改
            </el-tag>
          </div>
          <div class="limit-desc">{{ item.description }}</div>
        </div>
        <div class="limit-input">
          <el-input-number
            v-model="edited[item.key]"
            :min="item.minimum"
            :max="item.maximum"
            :step="1"
            step-strictly
            controls-position="right"
          />
          <span class="limit-default">默认 {{ item.default }}</span>
        </div>
      </div>

      <div class="settings-actions">
        <el-button type="primary" :disabled="!dirty" :loading="saving" @click="save">保存</el-button>
        <el-button :disabled="!hasCustom" :loading="resetting" @click="resetAll">全部恢复默认</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-header {
  margin-bottom: 16px;
}

.settings-header h2 {
  margin: 0 0 4px;
}

.settings-sub {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0;
}

.settings-card {
  background: #fff;
  border-radius: var(--radius-md);
  box-shadow: 0 2px 10px rgba(15, 31, 74, 0.06);
  padding: 8px 24px;
  max-width: 860px;
}

.limit-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.limit-row:last-of-type {
  border-bottom: none;
}

.limit-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.custom-tag {
  font-weight: 400;
}

.limit-desc {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.limit-input {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.limit-default {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  width: 56px;
}

.settings-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 0;
}
</style>
