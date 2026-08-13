# 智能办案平台

面向劳动人事争议仲裁的 AI 智能办案平台。架构说明见 `docs/architecture.md`，前端视觉规范见 `docs/design-guide.md`。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL（预登记案件独立用 SQLite）
- 前端：Vue3 + Vite + TypeScript + Pinia + Element Plus + ECharts
- 部署：systemd（`deploy/panel.service`）+ nginx HTTPS 反代（`deploy/https.md`）

## 主要功能

- **案件总览驾驶舱**：时效提醒、待办案件、在办案件、待调解、已开庭待裁决、今日立案/结案、近日开庭等统计卡片，支持点击钻取明细；年度数据区 + 四张趋势图表。
- **办案进度监控**：对接内网案件系统（`app/integrations/case_system/`），后台定时轻量同步形成快照，按环节/紧急度筛选，支持人工时效覆盖与一致性校验对账。
- **统计分析**：KPI（收件/立案/在办/结案、调解率、平均审理时长、超审限）+ 仲裁员办案量 + 审理时长分桶，统一钻取明细弹窗。
- **时限设置**：提醒类阈值（时效临近、中止过久、调解超时、同步间隔）存库实时生效。
- **预登记案件**：暂不录入内网的案件登记跟踪，独立 SQLite 库存储，支持查自然人/查企业（内网数据共享接口）、生成仲裁申请书，并可**一键保存到内网收件**（`POST /virtual-cases/{id}/submit`，自动组装 receive/add 复杂请求体）。
- **案件工作台**：案件画像 + 阶段工作区 + AI 助手 + 时间线四区块组合；AI 能力层为可插拔接口（当前 mock 实现，落库待人工确认）。

> 系统已免登录（内网环境），打开即主页，写操作留痕为 admin。详见 `docs/architecture.md`「免登录」一节。

## 目录结构

```text
├── backend/            FastAPI 后端（api / services / ai / repositories / models 分层）
│   ├── alembic/        数据库迁移
│   └── tests/          pytest 测试
├── frontend/           Vue3 前端（views / components / api / stores / styles）
├── deploy/             systemd unit 与 HTTPS 部署说明
└── docs/               架构说明、前端设计规范
```

## 快速开始

### 后端

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # 按需修改 DATABASE_URL / 内网系统账号等
alembic upgrade head
uvicorn app.main:app --reload
```

验证：`curl localhost:8000/api/v1/health`；运行测试 `pytest`。

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认通过 Vite 代理访问 `http://localhost:6543` 的后端接口（见 `frontend/vite.config.ts`），前后端需同时启动。生产构建 `npm run build`（含 `vue-tsc` 类型检查）。

## 文档

- `docs/architecture.md` — 后端分层、关键设计（状态机、内网同步、紧急度、超审限判定等）、前端结构、运行方式
- `docs/design-guide.md` — 前端统一视觉规范（深蓝科技风，改 UI 前必读）
- `deploy/https.md` — 生产 HTTPS 部署步骤
