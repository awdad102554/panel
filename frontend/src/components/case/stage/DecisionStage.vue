<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="stage-panel">
    <h4>裁决阶段</h4>
    <p>触发"裁决书生成 AI"生成草稿，经仲裁员确认后归档为正式文书。</p>
  </div>
</template>
