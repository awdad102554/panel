# 前端设计规范 — 深蓝科技风（Deep Blue Tech）

> 本文档是智能办案平台前端的**统一视觉规范**。新增或改版任何页面**都必须沿用本规范**，不要临时引入其他风格，避免页面之间显得突兀不统一。改前端 UI 前请先读本文档。

## 1. 设计理念

面向劳动人事争议仲裁的办案系统，视觉目标：**光滑、高级、科技感**，同时保留仲裁场景应有的**稳重、专业、权威**。

- 蓝色系传递专业与信任（法律/仲裁行业惯例）。
- 深色渐变 + 细网格纹理 + 毛玻璃（glassmorphism）+ 青蓝高亮，营造科技感。
- 克制：不做花哨动画、不做娱乐化配色、不引入复杂动画库、不引入整站深色模式切换开关。

## 2. 核心架构原则：深壳浅心

**深色只用于"外壳"，浅色用于"内容"。**

| 区域 | 风格 | 说明 |
|------|------|------|
| MainLayout header / sidebar | 深色 | 深色玻璃外壳，青蓝高亮 |
| `el-main` 内容区（案件池/工作台/统计/驾驶舱正文） | 浅色 | 保持 Element Plus 默认浅色，保证数据密集页面的可读性 |

> 系统已免登录（无登录页），深色仅用于 MainLayout 外壳。不要对整站切换 Element Plus dark-mode class。深色仅通过 `.bg-tech-grid` / `.glass-card` 工具类和 scoped 样式，作用在外壳上。

## 3. 设计 Token

全局定义在 `frontend/src/styles/tokens.css`（`:root` CSS 变量），已在 `main.ts` 引入。**新页面直接引用变量，不要另写魔法值。**

```css
/* 背景 */
--bg-deep: #0a1330;
--bg-deep-2: #0f1f4a;
--bg-grid-line: rgba(255, 255, 255, 0.04);

/* 玻璃卡片 */
--glass-bg: rgba(255, 255, 255, 0.06);
--glass-bg-hover: rgba(255, 255, 255, 0.09);
--glass-border: rgba(255, 255, 255, 0.12);
--glass-blur: 16px;

/* 科技高亮色 */
--accent-cyan: #22d3ee;   /* 主高亮 / 待办 / 开庭 */
--accent-blue: #3b82f6;   /* 常规流程 */
--accent-amber: #f59e0b;  /* 风险 / 时效临近 */
--accent-red: #f87171;    /* 超期 / 错误 */
--accent-green: #34d399;  /* 完成 / 通知 */

/* 文字（深色底上） */
--text-primary: #e6ebfa;
--text-secondary: #93a0c4;

/* 圆角 / 阴影 */
--radius-lg: 16px;
--radius-md: 10px;
--shadow-glass: 0 8px 32px rgba(0, 0, 0, 0.35);
```

### 语义色约定

- **主高亮 / 交互焦点**：`--accent-cyan`（青蓝）。聚焦边框、选中态、品牌图标、按钮渐变起点。
- **常规流程指标**：`--accent-blue`。
- **完成 / 通知**：`--accent-green`。
- **风险 / 临近**：`--accent-amber`。
- **超期 / 错误 / 危险**：`--accent-red`。
- 浅色内容页文字沿用 Element Plus 变量（`--el-text-color-primary` / `--el-text-color-secondary`）。

## 4. 工具类

定义在 `frontend/src/styles/global.css`，已全局引入。

### `.bg-tech-grid`
深蓝渐变底 + 两处径向光晕 + 细网格线。用于 MainLayout 外壳背景。

### `.glass-card`
毛玻璃卡片：半透明白底 + `backdrop-filter: blur` + 细边框 + 阴影 + hover 微亮过渡。用于 header、sidebar 等深色外壳元素。

```
background: var(--glass-bg);
backdrop-filter: blur(var(--glass-blur));
border: 1px solid var(--glass-border);
border-radius: var(--radius-lg);
box-shadow: var(--shadow-glass);
```

> 用作 header/sidebar 时按需覆盖 `border-radius: 0` 和单边 `border-width`（见 MainLayout 实现）。

## 5. 组件样式约定

### 品牌标识
⚖ 图标（`--accent-cyan` + `drop-shadow` 光晕）+ "智能办案平台"标题（`font-weight: 700`，字间距加宽），副标题"劳动人事争议仲裁智能办案平台"。

### 深色外壳里的输入框
透明背景 + 浅色文字，聚焦时青蓝内描边：
```
.el-input__wrapper { background: rgba(255,255,255,0.05); box-shadow: 0 0 0 1px var(--glass-border) inset; }
.el-input__wrapper.is-focus { box-shadow: 0 0 0 1px var(--accent-cyan) inset; }
.el-input__inner { color: var(--text-primary); }
```

### 主操作按钮（深色外壳内）
青蓝→蓝色渐变，深色文字，hover 上浮 + 青蓝阴影：
```
background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
color: #06162e; font-weight: 700;
hover: transform: translateY(-1px); box-shadow: 0 8px 20px rgba(34,211,238,0.3);
```

### 深色侧边菜单选中态
`el-menu-item.is-active`：青蓝文字 + 青蓝左边框 + 半透明青蓝底 `rgba(34,211,238,0.1)`。

### 浅色内容页的统计卡片（驾驶舱模式）
白底 + 轻阴影 + **左侧 4px accent 色条**（按语义色区分优先级）+ 左上角图标（accent 色 + 12% 同色半透明底）+ 大字号粗体数字 + hover 上浮。图标用 `@element-plus/icons-vue`。参考 `DashboardView.vue`。

## 6. 参考实现（可直接抄样式的现成文件）

- `frontend/src/layouts/MainLayout.vue` — 深色 header + sidebar 外壳，浅色内容区
- `frontend/src/views/DashboardView.vue` — 浅色内容页里的统计卡片范式

## 7. 依赖

- `@element-plus/icons-vue` — 图标（统计卡片等）。新增图标从此包按需 import。

## 8. 做新页面时的检查清单

- [ ] 是"外壳/入口"页还是"数据内容"页？前者可用深色，后者保持浅色。
- [ ] 颜色、圆角、阴影一律引用 `tokens.css` 变量，不写魔法值。
- [ ] 需要卡片/容器质感时优先用 `.glass-card`（深色）或参考驾驶舱白色统计卡（浅色）。
- [ ] 交互焦点/主按钮用青蓝；风险/超期用琥珀/红；完成/通知用绿。
- [ ] 不引入新的动画库、不切整站 dark mode。
- [ ] 改完跑 `npm run build` 类型检查通过。
