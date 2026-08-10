<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="stage-panel">
    <h4>庭前准备阶段</h4>
    <p>整理证据材料、确定争议焦点，可触发"案件理解 AI"与"法律分析 AI"辅助梳理。</p>
  </div>
</template>
