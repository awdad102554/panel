<script setup lang="ts">
import { computed, onMounted } from "vue";

import AIAssistantPanel from "@/components/case/AIAssistantPanel.vue";
import CasePortrait from "@/components/case/CasePortrait.vue";
import CaseTimeline from "@/components/case/CaseTimeline.vue";
import DecisionStage from "@/components/case/stage/DecisionStage.vue";
import HearingStage from "@/components/case/stage/HearingStage.vue";
import IntakeStage from "@/components/case/stage/IntakeStage.vue";
import MediationStage from "@/components/case/stage/MediationStage.vue";
import PreHearingStage from "@/components/case/stage/PreHearingStage.vue";
import ServiceStage from "@/components/case/stage/ServiceStage.vue";
import { useCaseStore } from "@/stores/case";
import type { CaseStatus } from "@/types";

const props = defineProps<{ id: string }>();
const caseStore = useCaseStore();

const STAGE_COMPONENTS: Partial<Record<CaseStatus, unknown>> = {
  received: IntakeStage,
  pre_review: IntakeStage,
  mediation: MediationStage,
  filed: PreHearingStage,
  pre_hearing: PreHearingStage,
  hearing: HearingStage,
  post_hearing: HearingStage,
  decision: DecisionStage,
  service: ServiceStage,
  archived: ServiceStage,
};

const currentStageComponent = computed(() => {
  const status = caseStore.currentCase?.status;
  return status ? STAGE_COMPONENTS[status] : null;
});

onMounted(async () => {
  await caseStore.fetchCaseWorkspace(props.id);
});
</script>

<template>
  <div v-if="caseStore.currentCase" class="case-workspace">
    <el-row :gutter="16">
      <el-col :span="6">
        <CasePortrait :case-data="caseStore.currentCase" />
      </el-col>
      <el-col :span="12">
        <component :is="currentStageComponent" :case-data="caseStore.currentCase" v-if="currentStageComponent" />
      </el-col>
      <el-col :span="6">
        <AIAssistantPanel :case-id="props.id" />
      </el-col>
    </el-row>

    <el-divider />

    <h3>案件时间线</h3>
    <CaseTimeline :events="caseStore.currentTimeline" />
  </div>
</template>
