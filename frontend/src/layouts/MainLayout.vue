<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { useUserStore } from "@/stores/user";

const route = useRoute();
const userStore = useUserStore();

const nameDialogVisible = ref(false);
const nameInput = ref("");
const savingName = ref(false);

function openNameDialog() {
  nameInput.value = userStore.username ?? "";
  nameDialogVisible.value = true;
}

async function saveName() {
  const name = nameInput.value.trim();
  if (!name) return;
  savingName.value = true;
  try {
    await userStore.bind(name);
    ElMessage.success("用户名已保存");
    nameDialogVisible.value = false;
  } catch {
    ElMessage.error("用户名保存失败,请稍后重试");
  } finally {
    savingName.value = false;
  }
}

onMounted(async () => {
  await userStore.load();
  if (!userStore.isBound) openNameDialog();
});
</script>

<template>
  <el-container class="main-layout bg-tech-grid">
    <el-header class="main-header glass-card">
      <div class="brand">
        <span class="brand-icon">⚖</span>
        <span class="brand-text">智能办案平台</span>
      </div>
      <div class="header-user">
        <el-button text class="user-chip" @click="openNameDialog">
          <span v-if="userStore.isBound" class="user-name">👤 {{ userStore.username }}</span>
          <span v-else class="user-name user-unset">设置用户名</span>
        </el-button>
      </div>
    </el-header>
    <el-container class="main-body">
      <el-aside width="180px" class="main-aside glass-card">
        <el-menu router :default-active="route.path" class="dark-menu">
          <el-menu-item index="/dashboard">案件总览</el-menu-item>
          <el-menu-item index="/priority">办案进度监控</el-menu-item>
          <el-menu-item index="/ai-reserve-review">
            <span>AI 预约审查</span>
          </el-menu-item>
          <el-menu-item index="/virtual-cases">预登记案件</el-menu-item>
          <el-menu-item index="/tianyancha">天眼查</el-menu-item>
          <el-menu-item index="/stats">统计分析</el-menu-item>
          <el-menu-item index="/time-limits">时限设置</el-menu-item>
          <el-menu-item index="/models">模型管理</el-menu-item>
        </el-menu>
        <div class="aside-external">
          <a
            href="https://hailiangjeff.top:5443/handle_query"
            target="_blank"
            rel="noopener"
            class="external-link"
            >立案查询 ↗</a
          >
        </div>
      </el-aside>
      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>

    <el-dialog
      v-model="nameDialogVisible"
      :title="userStore.isBound ? '修改用户名' : '设置用户名'"
      width="380px"
    >
      <p class="name-hint">
        当前设备 IP:{{ userStore.ip || "-" }}。设置后,你在案件记事本中的操作人将显示为此名字。
      </p>
      <el-input
        v-model="nameInput"
        maxlength="32"
        placeholder="请输入你的名字"
        @keyup.enter="saveName"
      />
      <template #footer>
        <el-button @click="nameDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingName" :disabled="!nameInput.trim()" @click="saveName">
          保存
        </el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<style scoped>
.main-layout {
  height: 100vh;
}

.main-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-radius: 0;
  border-width: 0 0 1px 0;
  padding: 0 24px;
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  color: var(--accent-cyan);
  font-size: 20px;
  filter: drop-shadow(0 0 8px rgba(34, 211, 238, 0.5));
}

.brand-text {
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 2px;
}

.header-user {
  display: flex;
  align-items: center;
}

.user-chip {
  padding: 4px 12px;
  font-size: 14px;
}

.user-name {
  color: var(--text-primary);
  font-weight: 600;
}

.user-unset {
  color: var(--accent-cyan);
}

.name-hint {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 0 0 12px;
  line-height: 1.6;
}

.main-body {
  min-height: 0;
}

.main-aside {
  border-radius: 0;
  border-width: 0 1px 0 0;
  padding-top: 8px;
}

.main-content {
  background: #f5f7fb;
  border-top-left-radius: var(--radius-lg);
  overflow-y: auto;
}

.dark-menu {
  background: transparent;
  border-right: none;
}

.dark-menu :deep(.el-menu-item) {
  color: var(--text-secondary);
  border-left: 3px solid transparent;
}

.dark-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

.dark-menu :deep(.el-menu-item.is-active) {
  background: rgba(34, 211, 238, 0.1);
  color: var(--accent-cyan);
  border-left-color: var(--accent-cyan);
}

.aside-external {
  padding: 8px 0 0;
  margin-top: 8px;
  border-top: 1px solid var(--glass-border);
}

.external-link {
  display: block;
  padding: 0 20px;
  height: 44px;
  line-height: 44px;
  font-size: 14px;
  color: var(--text-secondary);
  text-decoration: none;
  border-left: 3px solid transparent;
  transition: color 0.2s ease, background 0.2s ease;
}

.external-link:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--accent-cyan);
}
</style>
