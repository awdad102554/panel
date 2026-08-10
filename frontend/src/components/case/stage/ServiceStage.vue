<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="stage-panel">
    <h4>送达阶段</h4>
    <p>登记文书送达方式（自取/邮寄）与送达状态，更新送达回执。</p>
  </div>
</template>
