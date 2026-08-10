<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="stage-panel">
    <h4>调解阶段</h4>
    <p>记录调解过程与双方意见，生成调解协议书草稿（待接入文书生成 AI）。</p>
  </div>
</template>
