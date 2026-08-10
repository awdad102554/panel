<script setup lang="ts">
import type { TimelineEvent } from "@/types";

defineProps<{ events: TimelineEvent[] }>();
</script>

<template>
  <el-timeline>
    <el-timeline-item
      v-for="event in events"
      :key="event.id"
      :timestamp="event.created_at"
    >
      <div>{{ event.summary }}</div>
      <div v-if="event.created_by" class="operator">操作人：{{ event.created_by }}</div>
    </el-timeline-item>
    <el-empty v-if="!events.length" description="暂无时间线记录" />
  </el-timeline>
</template>

<style scoped>
.operator {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
