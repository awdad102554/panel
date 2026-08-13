# 架构说明

## 总体结构

智能办案平台是全新一代的劳动人事争议仲裁办案系统，采用前后端分离架构：

- `backend/`：FastAPI 应用，按表现层→业务层→AI 服务层→基础服务层→数据层分层。
- `frontend/`：Vue3 + Vite + TypeScript 单页应用，通过 `/api` 反向代理调用后端。

案件总览驾驶舱、内网案件监控与同步、统计分析、时限设置、预登记案件等模块已上线运行；AI 能力层仍为可插拔的 mock 实现，真实 LLM 接入留待后续迭代。

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
- `app/models/`：`User`/`Case`/`Party`/`Evidence`/`Document`/`CaseTimelineEvent`/`AIOutput`/`ServiceDelivery`/`AIModelConfig`/`SystemSetting`/`InternalCaseTracking`/`CaseTimeLimitOverride`/`SyncVerificationReport`（`CaseServiceConfirmation` 已随结案即终态的设计下线并删表）。
- `app/schemas/`：Pydantic 请求/响应模型，按模块拆分，与 ORM 模型解耦。
- `app/repositories/`：纯数据访问（如 `case_repository.py`），不做状态校验。
- `app/services/`：业务规则，例如 `case_lifecycle.py` 的状态机、`timeline_service.py` 的统一时间线写入、`internal_case_sync.py` 的内网案件全量同步、`internal_case_urgency.py` 的紧急度纯函数。
- `app/integrations/`：外部系统对接，目前只有 `case_system/`（内网案件系统 10.96.10.78:8080 的登录/token 缓存客户端与统计服务）。
- `app/ai/`：AI 能力层，`base.py` 定义统一输出结构 `AIResult` 与 `AICapability` 抽象基类；`client.py` 封装 LLM Provider（当前为 `MockLLMClient`，未来接入真实模型只需替换该文件，上层能力类和业务代码不受影响）。
- `app/api/v1/`：路由层，按模块拆分（`auth`/`dashboard`/`cases`/`case_portrait`/`timeline`/`ai`/`ai_models`/`documents`/`service_delivery`/`stats`/`internal_cases`/`settings`/`virtual_cases`），统一经 `router.py` 汇总。

## 关键设计

- **案件状态机**：`services/case_lifecycle.py` 用 `CaseStatus` 枚举 + `ALLOWED_TRANSITIONS` 合法迁移表实现，禁止非法跳变；每次迁移都调用 `timeline_service.add_timeline_event` 落一条可追溯记录。
- **AI 与业务解耦**：`api/v1/ai.py` 只做"读取案件数据 → 调用 AI Capability → 落库为待确认的 `AIOutput` → 返回结构化结果"，不直接改业务字段；仲裁员调用 `/confirm` 接口后才写入 `confirmed_at`/`confirmed_by`，对应人机协同确认原则。
- **统一输出格式**：`ai/base.py` 的 `AIResult{summary, issues, risks, suggestions, references, extra}`，各 Capability（收件预审/案件理解/法律分析/裁决书生成）继承并按需扩展 `extra` 字段，前端 `AIAssistantPanel.vue` 按统一结构渲染。
- **免登录**：2026-07-31 起系统取消登录（内网环境、无账号体系），`api/deps.py` 的 `get_current_user` 直接返回内置管理员用户，写操作留痕 username 为 admin；前端登录页/路由守卫/token 拦截器已移除，打开即是主页。`core/permissions.py` 的 Role × Action 模型保留但默认用户为管理员全部放行；如需恢复登录，还原 `deps.py` 并恢复前端登录流程。注意 `/auth/login` 路由仍注册可用（免登录后是无防护的令牌签发口，内网环境可接受；如需彻底关闭应摘除该路由）。
- **权限模型**：`core/permissions.py` 用 `Role`（仲裁员/书记员/调解员/管理员）× `Action`（查看/编辑/删除/AI调用/文书生成/审核确认）组合，路由通过 `Depends(require_permission(...))` 声明式校验。
- **一次录入全程复用**：案件核心字段（当事人、仲裁请求）只存在 `Case`/`Party` 表，AI 能力和文书生成均通过 `case_id` 外键引用而非复制数据。
- **近日开庭**：`services/internal_hearing.py` 实时调内网 `getAllHoldCourt`（按年月查询，跨月自动合并），过滤出"今日 ~ 下周日"的排期，当事人从 `calendar_text` 正则解析；不落库（单月个位数，量小且变动频繁）。`GET /dashboard/hearings` 返回明细，`/dashboard/summary` 的 `hearings_upcoming` 是同一范围的场次数。
- **预登记案件**：暂不录入内网的案件可在"预登记案件"页登记（记录信息与进度，之后再录内网），数据存独立 SQLite 文件库（`backend/data/virtual_cases.db`，`app/db/virtual.py`，与主库 PG 分离、启动自动建表/补列）；自动编号"预登[YYYY]NNN号"（取当年最大序号+1）；删除仅删本地记录，不联动内网已生成的收件；状态 pending（待录入）/recorded（已录入，终态不可恢复——已录入后修改直接在内网进行，防恢复后重复建案）；**待录入的预登记案件计入总览"待办案件"卡片并混入明细（stage=virtual，紧急度按登记后自然日数分档，阈值见时限设置"预登记临近/紧急阈值"，默认 30/60 天）**；查自然人/查企业直连内网数据共享接口（`services/datashare_lookup.py`，与 InfoWeb 同一上游，认证复用 CaseSystemClient，不依赖 InfoWeb 在线；查企支持全名/统一社会信用代码，查人按身份证号，未命中返回 404）。可生成仲裁申请书（`services/application_doc.py`，与 InfoWeb 同模板同拼接格式）。**保存到内网收件**（`services/case_submit.py`，2026-08-11 上线；2026-08-13 起界面称呼统一为"保存到内网"）：按内网 receive/add 抓包样例组装请求体——当事人直接映射（含**代理人 agents 数组**：挂在当事人下，类型码取 type 末元素 1法定/2指定/3近亲属/4团体推荐/5单位工作人员/6律师/7法律服务工作者，内网前端写死；律师类带律所/委托权限/法律援助，法定/近亲属带与当事人关系；查代理人回填走 `cases/Agent`，`lookup_agent`）；case_info 常量默认 + 区域锁定福建/三明/永安、乡镇可选；企业注册资本/信用代码/法人/地址提交时自动调查企业接口回填（草稿展示与正式提交共用 `_fill_company_info`，草稿不落库）；仲裁请求在新建/编辑表单即**结构化录入**（`components/PartyRequestsEditor.vue`：选三级类型+第四级选项+金额/多选项明细/期间，按内网模板自动生成请求文本且可手动编辑，"自动生成"可复位；旧数据的自由文本行保留兼容），随当事人存 `request_specs`（与 requests 文本按索引对齐，`utils/requestCatalog.ts` 的模板填充与后端 `_fill_template` 逐条对齐）；提交草稿优先用存的结构化数据（`_draft_from_spec`，目录改版导致类型失效时退回文本猜测并提示），不再依赖"关键词自动猜"（`guess_request`/`guess_amount` 仅兜底旧数据），用户改过的请求文本自动带进 intro；申请书合计金额优先取结构化 object/items（`build_total_amount`），无结构化数据行退回文本正则；intro 按内网模板生成（`选项1`/`标的`/`开始日期`/`结束日期` 占位替换；`$str` 模板为多选项请求，如工伤保险待遇各费用项，`items` 逐项金额、object 自动求和、intro 按"（N）选项金额元、"枚举拼接，格式对齐内网样例）；案由默认跟随**最后一条**请求的第二层类型（案由字典=请求树第二层名称集合；内网服务端按末请求覆盖案由，2026-08-12 多类型案件实测——单请求时首末一致）；**多申请人时请求归属按 `applicant_index` 贯穿草稿→提交→申请书，生成文本里泛指的"申请人"自动加编号（"申请人N"，正则幂等、不伤"被申请人"），与工作人员手动加编号的习惯一致**；多被申请人时支付类表述自动改"各被申请人共同"（样本 308623 工作人员手改习惯，幂等）**；fact_reason 含 actual_workplace/job（映射预登记 work_place/position），is_easy 默认 1、提交界面可开关（规则经确认 2026-08-12）；**事实理由与请求表述均为"自动生成 + 可编辑"**（与内网一致）：事实理由按 2026-08-13 内网审核通过案件样本总结的**四段式逐申请人拼接**（`compose_party_facts`/`compose_case_facts`：入职段〔空/0 片段省略〕+合同社保段+补充事实+因主因段+固定结尾，多申请人主体"申请人N"、合同社保段沿用"本人"防佶屈，案件级主因只并入第一段；纯旧数据〔无结构化字段、facts 为整段叙述〕直接沿用叙述原文，不虚构合同社保段与之矛盾），申请人结构化要素（签合同/缴社保/主因/补充事实）存预登记库，草稿/提交载荷/申请书三处共用同一拼接器；前端拼接镜像统一在 `utils/factCompose.ts`（表单每申请人卡片有实时生成预览，对话框"自动生成"同函数），工资金额去尾零用 toFixed+parseFloat（正则去尾零会把 4000 压成 4）；界面有"自动生成"按钮与主因预设多选+其他输入；**疑似重复案件**（"已提交过相关案件"等三类提示）返回 409，前端弹确认后带 `force=true` 重试，重试时附加 `is_passed=1/is_more_than_three=1` 放行标志（内网前端同款流程）。字典全部从内网实时拉取并进程内缓存 6 小时：仲裁请求类型树+叶子模板（`norm/arbRequest`，**含两级叶子**——确认劳动关系争议/其他劳动争议等 7 个二级节点本身即叶子；**$other 占位的其他类模板**需用户填具体内容，组装进 `other={"name":..,"value":..}`，未填拒绝提交防字面 `$other` 进内网；有叶子拉取失败时不写缓存下次重试）、通用字典（`norm/byType?type=` 案由/企业性质/民族/行业等）、乡镇（`common/get_structure_towns`）、行政区划（`common/area/{层级}/{父Id}`）。接口：`GET /virtual-cases/meta/request-catalog`（请求类型目录，供表单结构化录入）、`POST /virtual-cases/{id}/submit-draft`（草稿：结构化请求+猜测兜底+回填+校验+字典）、`/submit-preview`（预览请求体不发内网）、`/submit`（正式提交，成功置 recorded 并防重复提交 409）。经确认不做：打印预览、机关单位/代理人查询。
- **时限设置**：提醒类阈值（时效临近 5、中止过久 15、调解超时 30、同步间隔 60 分钟、**预登记临近 30 / 紧急 60 天**——按登记后自然日数分档）存 `system_settings` 表，`services/time_limits.py` 读取带 30 秒缓存、`effective_settings()` 覆盖进 Settings 副本供紧急度计算；法定审限、收件/预约处理时限为业务规则定值不开放设置。`GET/PUT /settings/time-limits` + 恢复默认，前端"时限设置"页（`SettingsView.vue`）实时生效。
- **统计分析页**：`GET /stats/overview` 与总览同源（内网同步快照 + `compute_urgency`），产出 KPI（累计收件/立案、在办、已结案、调解率、平均审理时长、当前超期）及各图表聚合；页面展示 KPI 行 + 仲裁员办案量 + 审理时长分桶（法定审限 45 天：≤45/46-60/61-90/>90）两张图（趋势、结案方式与总览重复，只在总览展示），图表钻取复用 `/dashboard/chart-cases`（含 `arbitrator`、`duration_bucket` 两个维度），明细弹窗为通用组件 `components/InternalCaseDialog.vue`（总览卡片/图表、统计页共用）。
- **案件总览卡片口径**：`/dashboard/summary` 全部从内网同步快照聚合（`dashboard.py::_snapshot_stats`，开庭场次实时取庭审日历）。卡片：时效提醒（已超期+紧急+临近）、待办案件（收件环节待审核、未立案，注意与"时效提醒"含义不同，勿混用）、在办案件（立案未结案）、待调解、已开庭待裁决、中止过久、今日立案、今日结案、近日开庭。紧急度与办案进度监控页共用同一套 `compute_urgency`，两页数字一致。除"近日开庭"外的卡片点开走 `GET /dashboard/card-cases?key=...`，明细过滤与卡片计数共用 `_row_in_card` 判定。总览年度数据区为 `components/YearlyStatsPanel.vue`，下方四张图表走 `GET /dashboard/charts`；前端用 echarts 渲染（`components/DashboardCharts.vue`）。
- **内网案件监控**：`main.py` 的 lifespan 里跑 `asyncio` 后台循环，按 `case_sync_interval_minutes`（默认 60 分钟，时限设置页可改）做**轻量同步**——内网接口实测支持筛选（`receive?status=0` 只回待审核、`handle?status=未结案` 只回在办），已结案不再变动的 2100+ 件历史案件不重复拉取；另按 `application_date` 补抓今天+昨天的新收件/新立案（捕获"快速流转""立案当天即结案"的案件）；对"上轮还在办、本轮消失"的案件按案号单点补拉（捕获结案/退回翻转；receive 已处理的会再探一次 handle，防快照冻结在收件环节）；**receive 无案号案件**（"保存未审批"的收件案号字段是哈希串，案号探测无效）退到"申请日期 ±1 天 + case_id"定点探测：找到=已处理/已修改（更新快照，如保存后正式提交获得正式收字号），窗口内找不到=内网已删除（删除快照行，误删可用全量同步恢复），探测失败保留原值下轮重试。同一案件多环节归并按 reserve→receive→handle 优先级取最靠后环节（不靠写入顺序）。`phase_entered_at` 锚点在环节/子状态/**中止标志**任一变化时重置，"已中止XX天"从进入中止算起。- **一致性校验**：`POST /internal-cases/verify-consistency` 全量只读对账（比对内网全量与快照的环节/子状态/结案字段，receive 环节加比内网 status——"保存未审批"被退回/处理只有 status 变化；不修正数据），结果落库到 `sync_verification_reports`（统计 + 完整差异明细，供排查轻量同步问题），`GET /internal-cases/verify-reports` 查历史；监控页"一致性校验"按钮触发。全量翻页仅作手工恢复手段（`POST /internal-cases/sync?full=true`），日常不跑；**全量模式会顺手清理幽灵快照**（receive/handle 全量历史比对，快照多出=内网已删除，删除并连带清理同 id 人工时效覆盖；任一环节拉取失败则跳过清理防误删；reserve 接口只回不通过记录、不是全量，不参与）。快照表 `internal_case_trackings` 按 `external_case_id` upsert（receive/reserve 返回全量历史）。紧急度不落库，读取时由 `internal_case_urgency.compute_urgency` 按"人工时效覆盖 > 环节原生倒计时/超期信号 > 进入环节天数估算"实时计算；已结案/已归档为终态，优先于人工覆盖，直接隐藏（2026-07-30 起取消结案后的送达跟踪，结案即最后阶段）；reserve 接口只返回审核不通过/退回补正的记录（status 枚举：0 待审核按天数监控、1/3 通过不告警、2/4 不通过单列 rejected），不算超期、默认隐藏；单案件时效可用 `/override` 人工覆盖（终态案件拒绝设置）。
- **中止天数回填**：列表接口不提供中止/恢复时间，但案件详情接口（`POST case/caseData`，与 InfoWeb 立案详情同源）返回 `review_matter` 审理事项记录，`services/internal_case_pause.py` 用"中止审理/恢复审理"的审批通过时间配对算出累计中止天数，由 `_pause_backfill_loop` 对已结案案件增量回填、对在办案件每轮重算（暂停仍在累计，ongoing 区间计到当天）；统计页/钻取的审理时长 = 结案日 - 立案日 - 中止天数。**超审限判定**（`_is_over_statutory_limit`）：经过天数 > 45 天法定审限 + `extension_days` 批准延期；经过天数从立案日起算，若 `review_matter` 中有变更/增加仲裁请求、反申请、追加当事人（审限依法重新起算）则从最近一次重启日（`clock_reset_at`）起算且只扣重启后中止（`paused_after_reset_days`）；结案案件算到结案日，在办算到今天。统计页 KPI 有"在办超审限/结案超审限"，钻取走 `/dashboard/chart-cases?kind=over_limit_open|over_limit_closed`。

## 前端结构

```text
frontend/src/
├── main.ts / App.vue         应用入口
├── router/index.ts           路由：/dashboard /priority /cases/:id /stats /time-limits /virtual-cases /models（免登录，无 /login）
├── stores/                   Pinia：case.ts（案件工作台状态）
├── api/                      axios 封装，按模块拆分（auth/dashboard/case/internalCase/ai/aiModel/stats/settings/virtualCases）
├── layouts/MainLayout.vue    顶部信息栏 + 侧边导航
├── views/
│   ├── DashboardView.vue     首页驾驶舱：待办案件/近日开庭/风险提醒等统计卡片（近日开庭卡片可点开看明细）
│   ├── CasePriorityView.vue  办案进度监控：内网案件监控（环节/紧急度筛选、时效覆盖、一致性校验）
│   ├── CaseWorkspaceView.vue 案件工作台：左画像/中当前阶段工作区/右 AI 助手/底部时间线
│   ├── StatsView.vue         统计分析
│   ├── SettingsView.vue      时限设置
│   ├── VirtualCasesView.vue  预登记案件
│   └── ModelManageView.vue   AI 模型配置管理
└── components/
    ├── DashboardCharts.vue   总览四张图表（echarts）
    ├── InternalCaseDialog.vue 案件明细弹窗（总览卡片/图表、统计页共用）
    ├── YearlyStatsPanel.vue  总览年度数据区
    └── case/
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
