# 架构说明

## 总体结构

智能办案平台是全新一代的劳动人事争议仲裁办案系统，采用前后端分离架构：

- `backend/`：FastAPI 应用，按表现层→业务层→AI 服务层→基础服务层→数据层分层。
- `frontend/`：Vue3 + Vite + TypeScript 单页应用，通过 `/api` 反向代理调用后端。

需求来源见 `智能办案平台需求/`（01～10 号文档），本仓库是其中 07 号《技术沟通说明》所要求分层架构的落地实现。当前阶段只搭建可运行的框架骨架：核心领域模型、案件状态机、AI 能力可插拔接口、四大核心页面骨架均已就位，完整仲裁业务规则和真实 LLM 接入留待后续迭代。

## 后端分层

```text
浏览器 / 前端 SPA
  -> app/api/v1/*          表现层：HTTP 路由、参数校验、权限依赖
  -> app/services/*        业务层：案件生命周期、时间线、送达等业务规则
  -> app/ai/*               AI 服务层：与业务层解耦，只接收/返回结构化数据
  -> app/repositories/*     基础服务层：纯 CRUD，不含业务规则
  -> app/models/*  (SQLAlchemy)  数据层：PostgreSQL
```

主要边界：

- `app/main.py`：FastAPI 应用入口，注册 CORS 中间件和 `api_router`。
- `app/core/`：配置（`config.py`，pydantic-settings）、JWT/密码哈希（`security.py`）、RBAC 权限依赖（`permissions.py`）。
- `app/db/`：`base.py`（Declarative Base）、`session.py`（异步引擎/会话，`get_db` 依赖）。
- `app/models/`：`User`/`Case`/`Party`/`Evidence`/`Document`/`CaseTimelineEvent`/`AIOutput`/`ServiceDelivery`/`AIModelConfig`/`InternalCaseTracking`（+`CaseTimeLimitOverride`/`CaseServiceConfirmation`）。
- `app/schemas/`：Pydantic 请求/响应模型，按模块拆分，与 ORM 模型解耦。
- `app/repositories/`：纯数据访问（如 `case_repository.py`），不做状态校验。
- `app/services/`：业务规则，例如 `case_lifecycle.py` 的状态机、`timeline_service.py` 的统一时间线写入、`internal_case_sync.py` 的内网案件全量同步、`internal_case_urgency.py` 的紧急度纯函数。
- `app/integrations/`：外部系统对接，目前只有 `case_system/`（内网案件系统 10.96.10.78:8080 的登录/token 缓存客户端与统计服务）。
- `app/ai/`：AI 能力层，`base.py` 定义统一输出结构 `AIResult` 与 `AICapability` 抽象基类；`client.py` 封装 LLM Provider（当前为 `MockLLMClient`，未来接入真实模型只需替换该文件，上层能力类和业务代码不受影响）。
- `app/api/v1/`：路由层，按模块拆分（`auth`/`dashboard`/`cases`/`case_portrait`/`timeline`/`ai`/`documents`/`service_delivery`/`stats`），统一经 `router.py` 汇总。

## 关键设计

- **案件状态机**：`services/case_lifecycle.py` 用 `CaseStatus` 枚举 + `ALLOWED_TRANSITIONS` 合法迁移表实现，禁止非法跳变；每次迁移都调用 `timeline_service.add_timeline_event` 落一条可追溯记录。
- **AI 与业务解耦**：`api/v1/ai.py` 只做"读取案件数据 → 调用 AI Capability → 落库为待确认的 `AIOutput` → 返回结构化结果"，不直接改业务字段；仲裁员调用 `/confirm` 接口后才写入 `confirmed_at`/`confirmed_by`，对应人机协同确认原则。
- **统一输出格式**：`ai/base.py` 的 `AIResult{summary, issues, risks, suggestions, references, extra}`，各 Capability（收件预审/案件理解/法律分析/裁决书生成）继承并按需扩展 `extra` 字段，前端 `AIAssistantPanel.vue` 按统一结构渲染。
- **免登录**：2026-07-31 起系统取消登录（内网环境、无账号体系），`api/deps.py` 的 `get_current_user` 直接返回内置管理员用户，写操作留痕 username 为 admin；前端登录页/路由守卫/token 拦截器已移除，打开即是主页。`core/permissions.py` 的 Role × Action 模型保留但默认用户为管理员全部放行；如需恢复登录，还原 `deps.py` 并恢复前端登录流程。
- **权限模型**：`core/permissions.py` 用 `Role`（仲裁员/书记员/调解员/管理员）× `Action`（查看/编辑/删除/AI调用/文书生成/审核确认）组合，路由通过 `Depends(require_permission(...))` 声明式校验。
- **一次录入全程复用**：案件核心字段（当事人、仲裁请求）只存在 `Case`/`Party` 表，AI 能力和文书生成均通过 `case_id` 外键引用而非复制数据。
- **近日开庭**：`services/internal_hearing.py` 实时调内网 `getAllHoldCourt`（按年月查询，跨月自动合并），过滤出"今日 ~ 下周日"的排期，当事人从 `calendar_text` 正则解析；不落库（单月个位数，量小且变动频繁）。`GET /dashboard/hearings` 返回明细，`/dashboard/summary` 的 `hearings_upcoming` 是同一范围的场次数。
- **预登记案件**：暂不录入内网的案件可在"预登记案件"页登记（记录信息与进度，之后再录内网），数据存独立 SQLite 文件库（`backend/data/virtual_cases.db`，`app/db/virtual.py`，与主库 PG 分离、启动自动建表/补列）；自动编号"预登[YYYY]NNN号"（取当年最大序号+1）；状态 pending（待录入）/recorded（已录入）可切换，**待录入的预登记案件计入总览"待办案件"卡片并混入明细（stage=virtual，按收件时限估算紧急度）**；查自然人/查企业直连内网数据共享接口（`services/datashare_lookup.py`，与 InfoWeb 同一上游，认证复用 CaseSystemClient，不依赖 InfoWeb 在线；查企支持全名/统一社会信用代码，查人按身份证号，未命中返回 404）。可生成仲裁申请书（`services/application_doc.py`，与 InfoWeb 同模板同拼接格式）。经确认不做：打印预览、机关单位/代理人查询。
- **时限设置**：提醒类阈值（时效临近 5、中止过久 15、调解超时 30、同步间隔 60 分钟）存 `system_settings` 表，`services/time_limits.py` 读取带 30 秒缓存、`effective_settings()` 覆盖进 Settings 副本供紧急度计算；法定审限、收件/预约处理时限为业务规则定值不开放设置。`GET/PUT /settings/time-limits` + 恢复默认，前端"时限设置"页（`SettingsView.vue`）实时生效。
- **统计分析页**：`GET /stats/overview` 与总览同源（内网同步快照 + `compute_urgency`），产出 KPI（累计收件/立案、在办、已结案、调解率、平均审理时长、当前超期）及各图表聚合；页面展示 KPI 行 + 仲裁员办案量 + 审理时长分桶（法定审限 45 天：≤45/46-60/61-90/>90）两张图（趋势、结案方式与总览重复，只在总览展示），图表钻取复用 `/dashboard/chart-cases`（含 `arbitrator`、`duration_bucket` 两个维度），明细弹窗为通用组件 `components/InternalCaseDialog.vue`（总览卡片/图表、统计页共用）。
- **案件总览卡片口径**：`/dashboard/summary` 全部从内网同步快照聚合（`dashboard.py::_snapshot_stats`，开庭场次实时取庭审日历）。卡片：时效提醒（已超期+紧急+临近）、待办案件（收件环节待审核、未立案，注意与"时效提醒"含义不同，勿混用）、在办案件（立案未结案）、待调解、已开庭待裁决、中止过久、今日立案、今日结案、近日开庭。紧急度与办案进度监控页共用同一套 `compute_urgency`，两页数字一致。除"近日开庭"外的卡片点开走 `GET /dashboard/card-cases?key=...`，明细过滤与卡片计数共用 `_row_in_card` 判定。总览年度数据区为 `components/YearlyStatsPanel.vue`，下方四张图表走 `GET /dashboard/charts`；前端用 echarts 渲染（`components/DashboardCharts.vue`）。
- **内网案件监控**：`main.py` 的 lifespan 里跑 `asyncio` 后台循环，按 `case_sync_interval_minutes`（默认 20 分钟）做**轻量同步**——内网接口实测支持筛选（`receive?status=0` 只回待审核、`handle?status=未结案` 只回在办、`handle?status=已结案` 首页按时间倒序补最新结案，捕获"立案当天即结案"的案件），已结案不再变动的 2100+ 件历史案件不重复拉取；对"上轮还在办、本轮消失"的案件按案号单点补拉（捕获结案/退回翻转）。- **一致性校验**：`POST /internal-cases/verify-consistency` 全量只读对账（比对内网全量与快照的环节/子状态/结案字段，不修正数据），结果落库到 `sync_verification_reports`（统计 + 完整差异明细，供排查轻量同步问题），`GET /internal-cases/verify-reports` 查历史；监控页"一致性校验"按钮触发。全量翻页仅作手工恢复手段（`POST /internal-cases/sync?full=true`），日常不跑。快照表 `internal_case_trackings` 按 `external_case_id` upsert（receive/reserve 返回全量历史，同步按 reserve→receive→handle 顺序，后写覆盖，stage 反映最靠后环节）。紧急度不落库，读取时由 `internal_case_urgency.compute_urgency` 按"人工时效覆盖 > 环节原生倒计时/超期信号 > 进入环节天数估算"实时计算；已结案/已归档为终态，直接隐藏（2026-07-30 起取消结案后的送达跟踪，结案即最后阶段）；reserve 接口只返回审核不通过/退回补正的记录（status 枚举：0 待审核按天数监控、1/3 通过不告警、2/4 不通过单列 rejected），不算超期、默认隐藏；单案件时效可用 `/override` 人工覆盖。
- **中止天数回填**：列表接口不提供中止/恢复时间，但案件详情接口（`POST case/caseData`，与 InfoWeb 立案详情同源）返回 `review_matter` 审理事项记录，`services/internal_case_pause.py` 用"中止审理/恢复审理"的审批通过时间配对算出累计中止天数，由 `_pause_backfill_loop` 对已结案案件增量回填、对在办案件每轮重算（暂停仍在累计，ongoing 区间计到当天）；统计页/钻取的审理时长 = 结案日 - 立案日 - 中止天数。**超审限判定**（`_is_over_statutory_limit`）：经过天数 > 45 天法定审限 + `extension_days` 批准延期；经过天数从立案日起算，若 `review_matter` 中有变更/增加仲裁请求、反申请、追加当事人（审限依法重新起算）则从最近一次重启日（`clock_reset_at`）起算且只扣重启后中止（`paused_after_reset_days`）；结案案件算到结案日，在办算到今天。统计页 KPI 有"在办超审限/结案超审限"，钻取走 `/dashboard/chart-cases?kind=over_limit_open|over_limit_closed`。

## 前端结构

```text
frontend/src/
├── main.ts / App.vue         应用入口
├── router/index.ts           路由：/login /dashboard /priority /cases/:id /stats /models
├── stores/                   Pinia：case.ts（案件工作台状态）
├── api/                      axios 封装，按模块拆分（auth/dashboard/case/internalCase/ai/aiModel/stats）
├── layouts/MainLayout.vue    顶部信息栏 + 侧边导航
├── views/
│   ├── LoginView.vue
│   ├── DashboardView.vue     首页驾驶舱：待办案件/近日开庭/风险提醒等统计卡片（近日开庭卡片可点开看明细）
│   ├── CasePriorityView.vue  办案进度监控：内网案件监控（环节/紧急度筛选、确认送达、时效覆盖）
│   ├── CaseWorkspaceView.vue 案件工作台：左画像/中当前阶段工作区/右 AI 助手/底部时间线
│   ├── StatsView.vue         统计分析
│   └── ModelManageView.vue   AI 模型配置管理
└── components/case/
    ├── CasePortrait.vue      案件画像
    ├── CaseTimeline.vue      案件时间线
    ├── AIAssistantPanel.vue  AI 助手（触发能力、展示结构化建议、人工确认）
    └── stage/*.vue           收件/调解/庭前/庭审/裁决/送达 各阶段工作区骨架
```

`CaseWorkspaceView.vue` 根据案件当前 `status` 动态选择 `stage/` 下对应阶段组件渲染，四大核心区块（画像/阶段工作区/AI 助手/时间线）在同一页面组合展示。

## 运行方式

### 后端

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 按需修改 DATABASE_URL / JWT_SECRET_KEY
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

默认通过 Vite 的 `/api` 代理转发到 `http://localhost:6543`（见 `vite.config.ts`），因此前后端需同时启动。

生产访问走 nginx（HTTPS + 域名，见 `deploy/https.md`）：https://hailiangjeff.top:5444 ，前端改动需 `npm run build` 后生效。

## 测试和验证

- 后端：`pytest backend/tests`（当前含健康检查测试）；亦可手工跑一遍最小闭环——创建案件 → 触发"收件预审 AI" → 确认输出 → 查看时间线，验证各层是否正确联动。
- 前端：`npm run build`（`vue-tsc` 类型检查 + Vite 构建）；`npm run dev` 后在浏览器中人工走查案件总览、办案进度监控、统计分析、时限设置等页面。
