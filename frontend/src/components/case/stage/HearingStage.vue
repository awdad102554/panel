<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="stage-panel">
    <h4>开庭阶段</h4>
    <p>记录庭审笔录要点，标记质证与辩论过程（待接入语音转写/庭审辅助能力）。</p>
  </div>
</template>
