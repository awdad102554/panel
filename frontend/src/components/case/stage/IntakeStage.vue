<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="stage-panel">
    <h4>收件阶段</h4>
    <p>核对当事人信息、仲裁请求与提交材料是否齐全，可触发左侧"收件预审 AI"辅助判断。</p>
  </div>
</template>
