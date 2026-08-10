import { defineStore } from "pinia";

import * as caseApi from "@/api/case";
import type { Case, CaseStatus, TimelineEvent } from "@/types";

interface CaseState {
  currentCase: Case | null;
  currentTimeline: TimelineEvent[];
}

export const useCaseStore = defineStore("case", {
  state: (): CaseState => ({
    currentCase: null,
    currentTimeline: [],
  }),
  actions: {
    async fetchCaseWorkspace(caseId: string) {
      this.currentCase = await caseApi.getCase(caseId);
      this.currentTimeline = await caseApi.getCaseTimeline(caseId);
    },
    async transition(caseId: string, targetStatus: CaseStatus) {
      this.currentCase = await caseApi.transitionCase(caseId, targetStatus);
      this.currentTimeline = await caseApi.getCaseTimeline(caseId);
    },
  },
});
