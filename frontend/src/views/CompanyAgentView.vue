<script setup lang="ts">
import CompanyAgentDatabasePanel from "@/components/CompanyAgentDatabasePanel.vue";
</script>

<template>
  <div class="company-agent-view">
    <CompanyAgentDatabasePanel />
  </div>
</template>

<style scoped>
.company-agent-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
}
</style>
