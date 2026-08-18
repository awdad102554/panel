<script setup lang="ts">
defineOptions({ name: "ReserveDetailTree" });

defineProps<{ data: unknown; depth?: number }>();

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function isArr(v: unknown): v is unknown[] {
  return Array.isArray(v);
}
function isPrimitive(v: unknown): v is string | number | boolean | null {
  return v === null || typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}
function fmt(v: unknown): string {
  if (v === null || v === "") return "—";
  return String(v);
}
</script>

<template>
  <div class="rdt" :style="depth ? { paddingLeft: `${(depth || 0) * 14}px` } : {}">
    <!-- 对象 -->
    <template v-if="isObj(data)">
      <div v-for="(v, k) in data" :key="k" class="rdt-row">
        <template v-if="isPrimitive(v) || (isArr(v) && v.length === 0)">
          <div class="rdt-leaf">
            <span class="rdt-key">{{ k }}</span>
            <span class="rdt-val">{{ fmt(v) }}</span>
          </div>
        </template>
        <template v-else>
          <div class="rdt-group">
            <div class="rdt-group-label">{{ k }}</div>
            <ReserveDetailTree :data="v" :depth="(depth || 0) + 1" />
          </div>
        </template>
      </div>
    </template>

    <!-- 数组 -->
    <template v-else-if="isArr(data)">
      <div v-if="data.length === 0" class="rdt-empty">无</div>
      <template v-else-if="isPrimitive(data[0])">
        <div class="rdt-val">{{ data.map(String).join("、") }}</div>
      </template>
      <template v-else>
        <div v-for="(item, i) in data" :key="i" class="rdt-item">
          <div v-if="data.length > 1" class="rdt-item-index">#{{ i + 1 }}</div>
          <ReserveDetailTree :data="item" :depth="(depth || 0) + 1" />
        </div>
      </template>
    </template>

    <!-- 原始值 -->
    <div v-else class="rdt-val">{{ fmt(data) }}</div>
  </div>
</template>

<style scoped>
.rdt {
  min-width: 0;
}

.rdt-row {
  margin-bottom: 2px;
}

.rdt-leaf {
  display: flex;
  gap: 12px;
  padding: 3px 0;
  line-height: 1.6;
}

.rdt-key {
  flex-shrink: 0;
  min-width: 110px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.rdt-key::after {
  content: "：";
}

.rdt-val {
  color: var(--el-text-color-primary);
  font-size: 13px;
  word-break: break-all;
}

.rdt-group {
  margin: 6px 0 10px;
}

.rdt-group-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--el-text-color-primary);
  padding: 4px 0 4px 8px;
  border-left: 3px solid var(--accent-cyan);
  margin-bottom: 6px;
}

.rdt-item {
  border: 1px solid rgba(15, 31, 74, 0.08);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fff;
}

.rdt-item-index {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-cyan);
  background: rgba(34, 211, 238, 0.12);
  padding: 1px 8px;
  border-radius: 999px;
  margin-bottom: 6px;
}

.rdt-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
