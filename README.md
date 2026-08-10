# 智能办案平台

面向劳动人事争议仲裁的 AI 智能办案平台。需求文档见 `智能办案平台需求/`，架构说明见 `docs/architecture.md`。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL
- 前端：Vue3 + Vite + TypeScript + Pinia + Element Plus

## 快速开始

### 后端

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认通过 Vite 代理访问 `http://localhost:6543` 的后端接口（见 `frontend/vite.config.ts` 与 `docs/architecture.md`）。

## 当前阶段

本仓库目前是可运行的项目框架骨架：核心领域模型、案件状态机、AI 能力可插拔接口（当前为 mock 实现）、四大核心页面（首页驾驶舱/案件工作台/案件画像/案件时间线）骨架均已就位。完整仲裁业务规则和真实 LLM 接入留待后续迭代。
