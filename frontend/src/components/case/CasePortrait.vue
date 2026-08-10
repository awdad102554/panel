<script setup lang="ts">
import type { Case } from "@/types";

defineProps<{ caseData: Case }>();
</script>

<template>
  <div class="case-portrait">
    <h3>案件画像</h3>
    <el-descriptions :column="1" border size="small">
      <el-descriptions-item label="案号">{{ caseData.case_no ?? "未编号" }}</el-descriptions-item>
      <el-descriptions-item label="状态">{{ caseData.status }}</el-descriptions-item>
      <el-descriptions-item label="仲裁请求">{{ caseData.claims ?? "-" }}</el-descriptions-item>
      <el-descriptions-item label="时效截止">{{ caseData.statute_deadline ?? "-" }}</el-descriptions-item>
    </el-descriptions>

    <h4>当事人</h4>
    <el-table :data="caseData.parties" size="small">
      <el-table-column prop="party_type" label="类型" width="90" />
      <el-table-column prop="name" label="名称" />
    </el-table>
    <el-empty v-if="!caseData.parties.length" description="暂无当事人信息" />
  </div>
</template>
