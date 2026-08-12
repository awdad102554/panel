import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: () => import("@/layouts/MainLayout.vue"),
      redirect: "/dashboard",
      children: [
        {
          path: "dashboard",
          name: "dashboard",
          component: () => import("@/views/DashboardView.vue"),
        },
        {
          path: "priority",
          name: "case-priority",
          component: () => import("@/views/CasePriorityView.vue"),
        },
        {
          path: "cases/:id",
          name: "case-workspace",
          component: () => import("@/views/CaseWorkspaceView.vue"),
          props: true,
        },
        {
          path: "stats",
          name: "stats",
          component: () => import("@/views/StatsView.vue"),
        },
        {
          path: "time-limits",
          name: "time-limits",
          component: () => import("@/views/SettingsView.vue"),
        },
        {
          path: "virtual-cases",
          name: "virtual-cases",
          component: () => import("@/views/VirtualCasesView.vue"),
        },
        {
          path: "models",
          name: "model-manage",
          component: () => import("@/views/ModelManageView.vue"),
        },
      ],
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/",
    },
  ],
});

export default router;
