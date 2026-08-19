<script setup lang="ts">
import { useRoute } from "vue-router";

const route = useRoute();
</script>

<template>
  <el-container class="main-layout bg-tech-grid">
    <el-header class="main-header glass-card">
      <div class="brand">
        <span class="brand-icon">⚖</span>
        <span class="brand-text">智能办案平台</span>
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
