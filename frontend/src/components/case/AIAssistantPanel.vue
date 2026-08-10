<script setup lang="ts">
import { ref } from "vue";

import * as aiApi from "@/api/ai";
import type { AICapability } from "@/api/ai";
import type { AIOutput } from "@/types";

const props = defineProps<{ caseId: string }>();

const capabilities: { label: string; value: AICapability }[] = [
  { label: "收件预审 AI", value: "intake_review" },
  { label: "案件理解 AI", value: "case_understanding" },
  { label: "法律分析 AI", value: "legal_analysis" },
  { label: "裁决书生成 AI", value: "decision_draft" },
];

const outputs = ref<AIOutput[]>([]);
const invoking = ref<AICapability | null>(null);

async function invoke(capability: AICapability) {
  invoking.value = capability;
  try {
    const output = await aiApi.invokeAICapability(props.caseId, capability);
    outputs.value.unshift(output);
  } finally {
    invoking.value = null;
  }
}

async function confirm(output: AIOutput) {
  const confirmed = await aiApi.confirmAIOutput(props.caseId, output.id);
  const idx = outputs.value.findIndex((item) => item.id === confirmed.id);
  if (idx !== -1) {
    outputs.value[idx] = confirmed;
  }
}
</script>

<template>
  <div class="ai-panel">
    <h3>AI 助手</h3>
    <div class="capability-list">
      <el-button
        v-for="cap in capabilities"
        :key="cap.value"
        size="small"
        :loading="invoking === cap.value"
        @click="invoke(cap.value)"
      >
        {{ cap.label }}
      </el-button>
    </div>

    <el-empty v-if="!outputs.length" description="尚未触发任何 AI 能力" />

    <el-card v-for="output in outputs" :key="output.id" class="output-card" shadow="never">
      <template #header>
        <div class="output-header">
          <span>{{ output.capability }}</span>
          <el-tag v-if="output.confirmed_at" type="success" size="small">已确认</el-tag>
          <el-button v-else size="small" type="primary" @click="confirm(output)">确认</el-button>
        </div>
      </template>
      <p>{{ output.result.summary }}</p>
      <div v-if="output.result.issues?.length">
        <strong>问题：</strong>
        <ul>
          <li v-for="issue in output.result.issues" :key="issue">{{ issue }}</li>
        </ul>
      </div>
      <div v-if="output.result.suggestions?.length">
        <strong>建议：</strong>
        <ul>
          <li v-for="s in output.result.suggestions" :key="s">{{ s }}</li>
        </ul>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.output-card {
  margin-bottom: 12px;
}
.output-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
