# 架构说明

## 总体结构

智能办案平台是全新一代的劳动人事争议仲裁办案系统，采用前后端分离架构：

- `backend/`：FastAPI 应用，按表现层→业务层→AI 服务层→基础服务层→数据层分层。
- `frontend/`：Vue3 + Vite + TypeScript 单页应用，通过 `/api` 反向代理调用后端。

案件总览驾驶舱、内网案件监控与同步、统计分析、时限设置、预登记案件、天眼查、AI 预约审查等模块已上线运行；案件工作台的 AI 能力层仍为可插拔的 mock 实现，AI 预约审查已接入真实 LLM（OpenAI 兼容，见下方「AI 预约审查」）。

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
- `app/models/`：`User`/`Case`/`Party`/`Evidence`/`Document`/`CaseTimelineEvent`/`AIOutput`/`ServiceDelivery`/`AIModelConfig`/`SystemSetting`/`InternalCaseTracking`/`CaseTimeLimitOverride`/`SyncVerificationReport`/`ReserveAIReview`/`ReserveReviewDecision`/`PreMediationBinding`（`CaseServiceConfirmation` 已随结案即终态的设计下线并删表）；另有 MySQL 共享表 `CaseTag`/`UserIpBinding`（`app/db/mysql.py` 的 `MysqlBase`，与 InfoWeb 共库，见「案件记事本 + IP→用户名绑定」）。
- `app/schemas/`：Pydantic 请求/响应模型，按模块拆分，与 ORM 模型解耦。
- `app/repositories/`：纯数据访问（如 `case_repository.py`），不做状态校验。
- `app/services/`：业务规则，例如 `case_lifecycle.py` 的状态机、`timeline_service.py` 的统一时间线写入、`internal_case_sync.py` 的内网案件全量同步、`internal_case_urgency.py` 的紧急度纯函数、`case_tags.py` 的案件记事本 subject_key 构造/环节解析/IP→用户名绑定、`pre_mediation_binding.py` 的案前调解→立案绑定与记事转移。
- `app/integrations/`：外部系统对接，`case_system/`（内网案件系统 10.96.10.78:8080 的登录/token 缓存客户端与统计服务）+ `tianyancha/`（天眼查 MCP 客户端，裸 httpx 自实现 Streamable HTTP + JSON-RPC 2.0）。
- `app/ai/`：AI 能力层，`base.py` 定义统一输出结构 `AIResult` 与 `AICapability` 抽象基类；`client.py` 封装 LLM Provider（当前为 `MockLLMClient`，未来接入真实模型只需替换该文件，上层能力类和业务代码不受影响）。另新增 `llm.py` 提供真实 OpenAI 兼容的 `chat_completion`（`POST {base_url}/chat/completions`、`response_format=json_object`，失败时把响应体里的 `error.message` 抠出抛 `LLMCallError`，便于排障），仅 AI 预约审查使用，案件工作台 mock 不受影响；`vision.py` 拉取内网材料图片/PDF 并编码为 OpenAI 兼容的 `image_url` data URI（PDF 用系统 Ghostscript 转 PNG，零第三方依赖，供视觉模型看图核对）。模型管理（`ai_models` 路由 + `AIModelConfig` 表）持久化供应商/base_url/密钥/模型名/temperature/`max_tokens`（单次最大输出 token，前端按主流模型上限预设自动填入，见 `utils/modelPresets.ts`，供真实 Provider 发请求时使用）与 `supports_vision`（是否支持图片输入，预约审查据此切换视觉/纯文本流程）。
- `app/api/v1/`：路由层，按模块拆分（`auth`/`dashboard`/`cases`/`case_portrait`/`timeline`/`ai`/`ai_models`/`documents`/`service_delivery`/`stats`/`internal_cases`/`settings`/`virtual_cases`/`reserve_review`/`tianyancha`/`case_tags`/`user_bindings`），统一经 `router.py` 汇总。

## 关键设计

- **案件状态机**：`services/case_lifecycle.py` 用 `CaseStatus` 枚举 + `ALLOWED_TRANSITIONS` 合法迁移表实现，禁止非法跳变；每次迁移都调用 `timeline_service.add_timeline_event` 落一条可追溯记录。
- **AI 与业务解耦**：`api/v1/ai.py` 只做"读取案件数据 → 调用 AI Capability → 落库为待确认的 `AIOutput` → 返回结构化结果"，不直接改业务字段；仲裁员调用 `/confirm` 接口后才写入 `confirmed_at`/`confirmed_by`，对应人机协同确认原则。
- **统一输出格式**：`ai/base.py` 的 `AIResult{summary, issues, risks, suggestions, references, extra}`，各 Capability（收件预审/案件理解/法律分析/裁决书生成）继承并按需扩展 `extra` 字段，前端 `AIAssistantPanel.vue` 按统一结构渲染。
- **免登录**：2026-07-31 起系统取消登录（内网环境、无账号体系），`api/deps.py` 的 `get_current_user` 直接返回内置管理员用户，写操作留痕 username 为 admin；前端登录页/路由守卫/token 拦截器已移除，打开即是主页。`core/permissions.py` 的 Role × Action 模型保留但默认用户为管理员全部放行；如需恢复登录，还原 `deps.py` 并恢复前端登录流程。注意 `/auth/login` 路由仍注册可用（免登录后是无防护的令牌签发口，内网环境可接受；如需彻底关闭应摘除该路由）。
- **权限模型**：`core/permissions.py` 用 `Role`（仲裁员/书记员/调解员/管理员）× `Action`（查看/编辑/删除/AI调用/文书生成/审核确认）组合，路由通过 `Depends(require_permission(...))` 声明式校验。
- **一次录入全程复用**：案件核心字段（当事人、仲裁请求）只存在 `Case`/`Party` 表，AI 能力和文书生成均通过 `case_id` 外键引用而非复制数据。
- **近日开庭**：`services/internal_hearing.py` 实时调内网 `getAllHoldCourt`（按年月查询，跨月自动合并），过滤出"今日 ~ 下周日"的排期，当事人从 `calendar_text` 正则解析；不落库（单月个位数，量小且变动频繁）。`GET /dashboard/hearings` 返回明细，`/dashboard/summary` 的 `hearings_upcoming` 是同一范围的场次数。
- **预登记案件**：暂不录入内网的案件可在"预登记案件"页登记（记录信息与进度，之后再录内网），数据存独立 SQLite 文件库（`backend/data/virtual_cases.db`，`app/db/virtual.py`，与主库 PG 分离、启动自动建表/补列）；自动编号"预登[YYYY]NNN号"（取当年最大序号+1）；删除仅删本地记录，不联动内网已生成的收件；状态 pending（待录入）/recorded（已录入，终态不可恢复——已录入后修改直接在内网进行，防恢复后重复建案）；**待录入的预登记案件计入总览"待办案件"卡片并混入明细（stage=virtual，紧急度按登记后自然日数分档，阈值见时限设置"预登记临近/紧急阈值"，默认 30/60 天）**；查自然人/查企业直连内网数据共享接口（`services/datashare_lookup.py`，与 InfoWeb 同一上游，认证复用 CaseSystemClient，不依赖 InfoWeb 在线；查企支持全名/统一社会信用代码，查人按身份证号，未命中返回 404）。可生成仲裁申请书（`services/application_doc.py`，与 InfoWeb 同模板同拼接格式）。**保存到内网收件**（`services/case_submit.py`，2026-08-11 上线；2026-08-13 起界面称呼统一为"保存到内网"）：按内网 receive/add 抓包样例组装请求体——当事人直接映射（含**代理人 agents 数组**：挂在当事人下，类型码取 type 末元素 1法定/2指定/3近亲属/4团体推荐/5单位工作人员/6律师/7法律服务工作者，内网前端写死；律师类带律所/委托权限/法律援助，法定/近亲属带与当事人关系；查代理人回填走 `cases/Agent`，`lookup_agent`）；case_info 常量默认 + 区域锁定福建/三明/永安、乡镇可选；企业注册资本/信用代码/法人/地址提交时自动调查企业接口回填（草稿展示与正式提交共用 `_fill_company_info`，草稿不落库）；仲裁请求在新建/编辑表单即**结构化录入**（`components/PartyRequestsEditor.vue`：选三级类型+第四级选项+金额/多选项明细/期间，按内网模板自动生成请求文本且可手动编辑，"自动生成"可复位；旧数据的自由文本行保留兼容），随当事人存 `request_specs`（与 requests 文本按索引对齐，`utils/requestCatalog.ts` 的模板填充与后端 `_fill_template` 逐条对齐）；提交草稿优先用存的结构化数据（`_draft_from_spec`，目录改版导致类型失效时退回文本猜测并提示），不再依赖"关键词自动猜"（`guess_request`/`guess_amount` 仅兜底旧数据），用户改过的请求文本自动带进 intro；申请书合计金额优先取结构化 object/items（`build_total_amount`），无结构化数据行退回文本正则；intro 按内网模板生成（`选项1`/`标的`/`开始日期`/`结束日期` 占位替换；`$str` 模板为多选项请求，如工伤保险待遇各费用项，`items` 逐项金额、object 自动求和、intro 按"（N）选项金额元、"枚举拼接，格式对齐内网样例）；案由默认跟随**最后一条**请求的第二层类型（案由字典=请求树第二层名称集合；内网服务端按末请求覆盖案由，2026-08-12 多类型案件实测——单请求时首末一致）；**多申请人时请求归属按 `applicant_index` 贯穿草稿→提交→申请书，生成文本里泛指的"申请人"自动加编号（"申请人N"，正则幂等、不伤"被申请人"），与工作人员手动加编号的习惯一致**；多被申请人时支付类表述自动改"各被申请人共同"（样本 308623 工作人员手改习惯，幂等）**；fact_reason 含 actual_workplace/job（映射预登记 work_place/position），is_easy 默认 1、提交界面可开关（规则经确认 2026-08-12）；**事实理由与请求表述均为"自动生成 + 可编辑"**（与内网一致）：事实理由按 2026-08-13 内网审核通过案件样本总结的**四段式逐申请人拼接**（`compose_party_facts`/`compose_case_facts`：入职段〔空/0 片段省略〕+合同社保段+补充事实+因主因段+固定结尾，多申请人主体"申请人N"、合同社保段沿用"本人"防佶屈，案件级主因只并入第一段；纯旧数据〔无结构化字段、facts 为整段叙述〕直接沿用叙述原文，不虚构合同社保段与之矛盾），申请人结构化要素（签合同/缴社保/主因/补充事实）存预登记库，草稿/提交载荷/申请书三处共用同一拼接器；前端拼接镜像统一在 `utils/factCompose.ts`（表单每申请人卡片有实时生成预览，对话框"自动生成"同函数），工资金额去尾零用 toFixed+parseFloat（正则去尾零会把 4000 压成 4）；界面有"自动生成"按钮与主因预设多选+其他输入；**疑似重复案件**（"已提交过相关案件"等三类提示）返回 409，前端弹确认后带 `force=true` 重试，重试时附加 `is_passed=1/is_more_than_three=1` 放行标志（内网前端同款流程）。字典全部从内网实时拉取并进程内缓存 6 小时：仲裁请求类型树+叶子模板（`norm/arbRequest`，**含两级叶子**——确认劳动关系争议/其他劳动争议等 7 个二级节点本身即叶子；**$other 占位的其他类模板**需用户填具体内容，组装进 `other={"name":..,"value":..}`，未填拒绝提交防字面 `$other` 进内网；有叶子拉取失败时不写缓存下次重试）、通用字典（`norm/byType?type=` 案由/企业性质/民族/行业等）、乡镇（`common/get_structure_towns`）、行政区划（`common/area/{层级}/{父Id}`）。接口：`GET /virtual-cases/meta/request-catalog`（请求类型目录，供表单结构化录入）、`POST /virtual-cases/{id}/submit-draft`（草稿：结构化请求+猜测兜底+回填+校验+字典）、`/submit-preview`（预览请求体不发内网）、`/submit`（正式提交，成功置 recorded 并防重复提交 409）。经确认不做：打印预览、机关单位/代理人查询。
- **时限设置**：提醒类阈值（时效临近 5、中止过久 15、调解超时 30、**案前调解临近 30 / 紧急 45 天**、同步间隔 60 分钟、**预登记临近 30 / 紧急 60 天**——按登记后自然日数分档）存 `system_settings` 表，`services/time_limits.py` 读取带 30 秒缓存、`effective_settings()` 覆盖进 Settings 副本供紧急度计算；法定审限、收件/预约处理时限为业务规则定值不开放设置。`GET/PUT /settings/time-limits` + 恢复默认，前端"时限设置"页（`SettingsView.vue`）实时生效。
- **统计分析页**：`GET /stats/overview` 与总览同源（内网同步快照 + `compute_urgency`），产出 KPI（累计收件/立案、在办、已结案、调解率、调撤率、平均审理时长、当前超期）及各图表聚合；页面展示 KPI 行 + 仲裁员办案量 + 审理时长分桶（法定审限 45 天：≤45/46-60/61-90/>90）两张图（趋势、结案方式与总览重复，只在总览展示），图表钻取复用 `/dashboard/chart-cases`（含 `arbitrator`、`duration_bucket` 两个维度），明细弹窗为通用组件 `components/InternalCaseDialog.vue`（总览卡片/图表、统计页共用）。
- **案件总览卡片口径**：`/dashboard/summary` 全部从内网同步快照聚合（`dashboard.py::_snapshot_stats`，开庭场次实时取庭审日历）。卡片：时效提醒（已超期+紧急+临近，案前调解不计入）、待办案件（收件环节/线上预约待审核、未立案，2026-08-17 起并入预约待审核；注意与"时效提醒"含义不同，勿混用）、案前调解（收件环节 next_step=3 进入调解，卡片右上角分档「临近/紧急」计数）、在办案件（立案未结案）、待调解、已开庭待裁决、中止过久、今日立案、今日结案、近日开庭。紧急度与办案进度监控页共用同一套 `compute_urgency`，两页数字一致。除"近日开庭"外的卡片点开走 `GET /dashboard/card-cases?key=...`，明细过滤与卡片计数共用 `_row_in_card` 判定。总览年度数据区为 `components/YearlyStatsPanel.vue`（并列展示「统计年度（12-10~次年12-10）」与「自然年度」两行，统计年度在上；立案、平均审理时长单显数值，结案/调解/调撤/一裁终局四框同显「数量 + 比率」——结案数+结案率、调解数+调解率、调撤数(调解+撤回)+调撤率、一裁终局数+一裁终局率，字段见 `schemas/stats.py::YearStats/YearlyStatsOut`，端点 `GET /stats/yearly`），下方四张图表走 `GET /dashboard/charts`；前端用 echarts 渲染（`components/DashboardCharts.vue`）。
- **AI 预约审查**（2026-08-17 上线）：对线上预约待审核案件（快照 `stage=reserve` 且 `raw_payload.status==0`）**逐件**自动审查，产出「通过/补正/驳回」初筛建议，**结论仅展示、不写回内网审批**（人机分工）。审查规则提示词取自 `docs/reserve-ai-review-prompt.md`（基于 32 条历史驳回记录总结的审查规则 1-5 + 三结论 + JSON 输出，见 `app/services/reserve_review.py` 的 `RESERVE_REVIEW_SYSTEM_PROMPT`）。流程：`GET /reserve-reviews/pending` 列待审核案件 → `POST /reserve-reviews/{external_case_id}/review` 用 `StreamingResponse`（`application/x-ndjson`，`X-Accel-Buffering: no`）逐步 yield 四步事件（fetch_detail 抓预约详情 → build_prompt 组装提示词+案件结构化摘要 → call_llm 调启用模型 → parse 解析结论），驱动前端动态时间线；每步可失败降级为「审查失败」结论。审查留痕落 `reserve_ai_reviews` 表（结论/问题点/缺材料/命中规则/逐项 `checks`/送入模型的 `case_snapshot`/`raw_result`，供校准回溯）。真实 LLM 走 `app/ai/llm.py`，复用 `ai_models` 已启用模型（当前 deepseek-v4-pro）；无启用模型/调用失败/输出非法时兜底「审查失败」不伪造结论。`GET /reserve-reviews/{id}` 取该案件最近一次留痕；`GET /reserve-reviews/{id}/detail` 实时拉内网详情并结构化返回（供右上角「查看案件」弹窗）。前端 `AiReserveReviewView.vue`：左栏待审核列表 + 右栏「审查流程动态时间线 + 结论卡片（通过=绿/补正=琥珀/驳回=红/失败=灰）+ **逐项审查清单**（5 条规则逐项通过/不通过/需核验，模型输出 `checks`，缺失时按 `rule_refs` 兜底；`passed` 为三态 true=通过 / false=不通过 / null=需人工核验，当模型在 note 里列了缺陷却仍标「通过」时，后端按 `_note_has_problem` 关键词兜底降级为「需人工核验」，避免漏看问题项）+ 可折叠案件摘要」，用 `fetch` + `ReadableStream` 消费 NDJSON 逐事件推进；页面右上角「查看案件」按钮弹 `el-dialog`，用通用递归组件 `ReserveDetailTree.vue` 渲染结构化案件详情（当事人/请求/事实理由/证据材料/证件照片状态）。案件摘要中 0/1 布尔字段（是否签订劳动合同/是否缴纳社保/是否涉及劳务派遣/是否主要争议）由 `build_case_payload` 统一归一为「是/否」再展示给模型与弹窗（`_yesno`，空值留空前端显示「—」），避免 `1/0` 歧义。2026-08-18 起新预约案件**自动审核一次**：`app/services/reserve_review_runner.py` 抽出非流式编排 `run_review`（复用 `reserve_review` 纯函数：抓详情→组装→读启用模型→调 LLM→解析→落库）与 `auto_review_pending`（仅对「历史无有效结论」的案件逐件审查，单案失败不中断整轮），供手动流式端点与后台自动审核复用；`app/main.py` 新增第三个后台循环 `_auto_review_loop`（约 120s，`case_system_enabled` 且同步锁空闲时跑，端到端延迟 ≈ 同步间隔 + 120s）；`GET /reserve-reviews/pending` 每案附 `has_review` / `latest_conclusion`，前端按钮由「审查」翻转为「重新审核」并显示最近结论标签，选中/首次加载时自动拉取并展示最近一次审查留痕。自动审核 `created_by="系统"`，`is_valid_conclusion` 以「通过/补正/驳回」判已审出结果，仅「审查失败」下一轮重试。2026-08-18 起新增**人工审核结果**：AI 在同一次调用里自动归类「同意/不同意」及 8 选 1 不同意理由（`decision`/`reject_reason`/`reject_detail`，见 `_normalize_decision`——decision 由结论确定性派生、不信任模型自相矛盾的 decision 字段；理由漏给/给错时兜底 补正→请补正、驳回→其他），前端结论卡片下方「审核结果」卡片由工作人员编辑确认后提交内网：`POST /reserve-reviews/{id}/decision` 组装请求体并 POST 内网 `POST /v1/api/admin/arb/{id}/reserve/preAudit`（`app/services/reserve_decision_submit.py`：同意→`{"reason":"","status":1}`，不同意→`{"reason":"理由[:明细]","status":2}`，status 1 通过/2 不通过，「请补正」「其他」带逐条明细、其余长句理由原文），提交成功后落 `reserve_review_decisions` 表并写回 `submitted_at`/`submitted_by`/`internal_status`/`internal_reason`（追加式留痕、最新一条生效、`created_by=当前用户`）；同一案件重复提交 409，提交失败不落库、返回 502 可重试。`GET /reserve-reviews/pending` 每案附 `submitted` 标记，前端左栏加「已提交」标签、卡片顶部加「已提交内网」标签并禁用表单/按钮（改「已提交」）。2026-08-19 起支持**视觉审查**：`AIModelConfig.supports_vision` 开启且启用模型支持图片时，`run_review` 走 `collect_material_images`（只收集身份证/证照正反面照片，证据材料仍只看字段）+ `fetch_material_images`（拉取失败/超限/PDF 转图失败静默跳过）+ `build_vision_messages`（system 追加 `VISION_INSTRUCTIONS` 图片核对指令、user 内容为「文本摘要 + 多张 image_url」）；PDF 经 Ghostscript 转 PNG 后送审（`word_url` 里的 PDF 当前仅作测试）；未开启则维持原纯文本流程（只看照片上传标记 + 字段）。
- **天眼查**（2026-08-19 上线）：接入天眼查 MCP（`https://mcp.tianyancha.com/mcp`），后端作为 MCP 客户端用裸 httpx 自实现 Streamable HTTP + JSON-RPC 2.0（`app/integrations/tianyancha/client.py`：协议版本协商 2025-06-18→2025-03-26→2024-11-05、`Mcp-Session-Id` 回带、SSE/JSON 两种响应解析、工具列表进程内缓存），鉴权用请求头 `Authorization: Bearer <key>`。编排在 `app/services/tianyancha_lookup.py`：`search_company` 调 `search_companies`（入参 `query`）解析 Markdown 候选表；`get_company_details` 调 `get_company_basic_profile` 解析基础画像为「概览字段（固定顺序白名单，丢弃分页/冗余/空值，`profile` 改名企业简介）+ 明细表（联系电话明细/曾用名明细等，笼统标题补二级章节名）」，并调 `get_company_people` 抽「主要人员」表——法定代表人职位合并进「法定代表人」字段（形如「曾毓群（董事长；总经理）」）、主要人员明细置于明细表首位；人员拉取失败（额度/无数据）降级为不展示、不阻断基础详情。API Key 可页面配置（存 `system_settings`，`services/tianyancha_settings.py`，`GET/PUT /tianyancha/config` 返回脱敏后四位；换 key 动态重建客户端并关闭旧连接池），也回落 `.env` 的 `TIANYANCHA_API_KEY`；鉴权失败（HTTP 401/403 或错误消息命中鉴权关键词）抛 `TianyanchaAuthError` → 接口 401「API Key 无效」，其余 MCP 异常 502、未配置/未命中 404。接口：`GET /tianyancha/lookup/company?name=`（候选列表）、`GET /tianyancha/lookup/details?name=`（企业详情，按需扣 1 次额度）、`GET /tianyancha/tools`（调试辅助）。前端 `TianyanchaView.vue`：候选列表按「精确匹配（公司名称/信用代码匹配）vs 关联候选（股东/历史等，折叠）」分块，每条精确匹配行有「查看详情」按钮点查该企业画像（el-descriptions 单列固定顺序）；API Key 区默认只读显示脱敏 Key（未配置显示「无」），点「编辑」展开输入框、「保存」落库（留空保存清除配置）。数据来自天眼查 MCP，非内网数据共享接口。
- **内网案件监控**：`main.py` 的 lifespan 里跑 `asyncio` 后台循环，按 `case_sync_interval_minutes`（默认 60 分钟，时限设置页可改）做**轻量同步**——内网接口实测支持筛选（`receive?status=0` 只回待审核、`handle?status=未结案` 只回在办），已结案不再变动的 2100+ 件历史案件不重复拉取；另按 `application_date` 补抓今天+昨天的新收件/新立案（捕获"快速流转""立案当天即结案"的案件）；对"上轮还在办、本轮消失"的案件按案号单点补拉（捕获结案/退回翻转；receive 已处理的会再探一次 handle，防快照冻结在收件环节）；**receive 无案号案件**（"保存未审批"的收件案号字段是哈希串，案号探测无效）退到"申请日期 ±1 天 + case_id"定点探测：找到=已处理/已修改（更新快照，如保存后正式提交获得正式收字号），窗口内找不到=内网已删除（删除快照行，误删可用全量同步恢复），探测失败保留原值下轮重试；**reserve 消失案件**（轻量对 reserve 是全量拉取、无筛选，2026-08-17 起）拉取成功即判定"已审核离开预约环节（转收件，内网可能另建新 case_id）或内网已删除"，预约无案号不做探测、直接删除快照（转收件后由 receive 侧同步捕获），拉取失败保留原值下轮重试。同一案件多环节归并按 reserve→receive→handle 优先级取最靠后环节（不靠写入顺序）。`phase_entered_at` 锚点在环节/子状态/**中止标志**任一变化时重置，"已中止XX天"从进入中止算起。- **一致性校验**：`POST /internal-cases/verify-consistency` 全量只读对账（比对内网全量与快照的环节/子状态/结案字段，receive/reserve 环节加比内网 status——"保存未审批"被退回/处理、预约待审核被退回(0→2)只有 status 变化；不修正数据），结果落库到 `sync_verification_reports`（统计 + 完整差异明细，供排查轻量同步问题），`GET /internal-cases/verify-reports` 查历史；监控页"一致性校验"按钮触发。全量翻页仅作手工恢复手段（`POST /internal-cases/sync?full=true`），日常不跑；**全量模式会顺手清理幽灵快照**（reserve/receive/handle 全量历史比对，快照多出=内网已删除，删除并连带清理同 id 人工时效覆盖；任一环节拉取失败则跳过清理防误删）。快照表 `internal_case_trackings` 按 `external_case_id` upsert（receive/reserve 返回未过滤列表；reserve 审核通过即离开列表）。紧急度不落库，读取时由 `internal_case_urgency.compute_urgency` 按"人工时效覆盖 > 环节原生倒计时/超期信号 > 进入环节天数估算"实时计算；已结案/已归档为终态，优先于人工覆盖，直接隐藏（2026-07-30 起取消结案后的送达跟踪，结案即最后阶段）；reserve status 枚举：0 待审核（工作人员待办，优先按原生 `reserve_time_limit` 倒计时分档、与收件同一套临近/紧急阈值，拿不到按进入天数估算）、1/3 通过不告警、2/4 不通过（退回申请人补正）单列 rejected 不算超期、默认隐藏；单案件时效可用 `/override` 人工覆盖（终态案件拒绝设置）。
- **案前调解跟踪 + 立案绑定**（2026-08-24 上线）：收件环节 `next_step=3`（收件审核通过后进入调解）是活跃子状态，`internal_case_urgency.py` 的 `is_pre_mediation` 识别后单独分档（`compute_pre_mediation_urgency`：进入调解锚点 `review_at` 回落 `receive_at/created_at`，满 30 天标"临近"、满 45 天标"紧急/警告"），不进通用"时效提醒"卡片与紧急度分布（否则被误算"已超期"、淹没"紧急"桶），单列总览"案前调解"卡片并带 `pre_mediation_soon/urgent` 分档计数；监控/明细列表对案前调解显示"进入调解 X 天"与"进入状态时间"列（`state_entered_at`），立案后有正式收件号的案前调解标题改显收件号。内网立案时为同一纠纷另建 handle 记录（新 case_id）、原收件停在案前调解永不关闭且无外键，`services/pre_mediation_binding.py` 在同步时按"申请人身份证号 + 被申请人名称 + 时间窗口（handle_at ≥ review_at）"自动一对一绑定（历史已结案靠 search 按申请人姓名兜底补拉），落 `pre_mediation_bindings` 表；绑定后该案前调解从总览/监控/提醒消失（已进入下一阶段），其记事 `case_tags.subject_key` 从 `ext:{receive_id}` 转挂到 `ext:{handle_id}`（先转记事再落绑定，记事转移失败跳过本轮防半截）。轻量同步额外按 `receive?next_step=3` 补抓案前调解持续跟踪。
- **案件记事本 + IP→用户名绑定**（2026-08-24 上线）：panel 与 InfoWeb 共用同一张 MySQL 库（`判决书生成`，`app/db/mysql.py` 起独立异步连接 `aiomysql`，启动时幂等建表），两张共享表 `case_tags`（记事只增不改留痕：`subject_key`/`content`/`stage`/`operator`/`client_ip`/`created_at`）与 `user_ip`（IP→用户名 upsert）。subject_key 为统一线程键：`ext:{内网 case_id}`（收件/立案/预约，同 case_id 跨环节自动衔接）与 `virt:{预登记 id}`（本地预登记案件）；案前调解→立案因内网另建 case_id，由 `pre_mediation_binding` 转挂 `ext:{receive_id}`→`ext:{handle_id}`（见上）。记事 `stage` 由 panel 后端从 PG 快照实时解析（`services/case_tags.py::resolve_subject_stage`：收件且 next_step=3 的案前调解细分为 `pre_mediation`、显示「收件审查 · 案前调解」；立案在办按 `current_step` 细分——审理中止→`paused`、组织调解→`mediation`、仲裁裁决中→`deciding`、待开庭安排→`pending_hearing`、待开庭审理→`pending_trial`、审理事项进行中→`in_progress`、已结案→`closed`、已归档→`archived`，未识别回落 `handle`=立案在办），InfoWeb 无快照故由页面上下文显式传入（receive 页→receive、next_step=3 的案前调解→pre_mediation、handle 页按 `current_step` 同口径细分）；`operator` 由客户端 IP 查 `user_ip` 解析，未绑定则 409 提示先设置用户名。客户端 IP 取 nginx `X-Real-IP`（即真实 `$remote_addr`，不可伪造），不信任 XFF 首跳（`$proxy_add_x_forwarded_for` 追加式下客户端可伪造首跳）。panel 侧 `GET/POST /case-tags/{subject_key}`、`GET/PUT /user-bindings/current`（免登录），与 InfoWeb 的 Flask 接口（`/api/case-tags/...`、`/api/user-bindings/current`）同表同格式。前端 `MainLayout.vue` 右上角用户名 chip（首次使用弹窗设置、点击可改）、`CaseTagDialog.vue` 记事本弹窗（案件总览/进度/预登记页「记事本」按钮唤起）；MySQL `wait_timeout=600` 下用 `pool_recycle=300` 避免空闲断连（aiomysql 与 pymysql 方言 `do_ping` 签名不兼容，`pool_pre_ping` 无法开启）。**快捷内容**（2026-08-26 上线）：共享表 `case_tag_phrases`（content 唯一去重，最多 100 字，记录创建人 operator），panel 侧 `GET/POST /case-tag-phrases`、`DELETE /case-tag-phrases/{id}`（`api/v1/case_tag_phrases.py`，POST 幂等去重），InfoWeb 侧 `/api/case-tag-phrases` 同表同格式；两端记事本弹窗底部以可点选标签展示（点击填入输入框、× 删除、➕ 展开添加），所有用户共享。
- **中止天数回填**：列表接口不提供中止/恢复时间，但案件详情接口（`POST case/caseData`，与 InfoWeb 立案详情同源）返回 `review_matter` 审理事项记录，`services/internal_case_pause.py` 用"中止审理/恢复审理"的审批通过时间配对算出累计中止天数，由 `_pause_backfill_loop` 对已结案案件增量回填、对在办案件每轮重算（暂停仍在累计，ongoing 区间计到当天）；统计页/钻取的审理时长 = 结案日 - 立案日 - 中止天数。**超审限判定**（`_is_over_statutory_limit`）：经过天数 > 45 天法定审限 + `extension_days` 批准延期；经过天数从立案日起算，若 `review_matter` 中有变更/增加仲裁请求、反申请、追加当事人（审限依法重新起算）则从最近一次重启日（`clock_reset_at`）起算且只扣重启后中止（`paused_after_reset_days`）；结案案件算到结案日，在办算到今天。统计页 KPI 有"在办超审限/结案超审限"，钻取走 `/dashboard/chart-cases?kind=over_limit_open|over_limit_closed`。

## 前端结构

```text
frontend/src/
├── main.ts / App.vue         应用入口
├── router/index.ts           路由：/dashboard /priority /cases/:id /stats /time-limits /virtual-cases /models /ai-reserve-review /tianyancha（免登录，无 /login）
├── stores/                   Pinia：case.ts（案件工作台状态）、user.ts（当前 IP 用户名绑定）
├── api/                      axios 封装，按模块拆分（auth/dashboard/case/internalCase/ai/aiModel/stats/settings/virtualCases/reserveReview/tianyancha/caseTag/userBinding）
├── layouts/MainLayout.vue    顶部信息栏 + 侧边导航
├── views/
│   ├── DashboardView.vue     首页驾驶舱：待办案件/近日开庭/风险提醒等统计卡片（近日开庭卡片可点开看明细）
│   ├── CasePriorityView.vue  办案进度监控：内网案件监控（环节/紧急度筛选、时效覆盖、一致性校验）
│   ├── CaseWorkspaceView.vue 案件工作台：左画像/中当前阶段工作区/右 AI 助手/底部时间线
│   ├── StatsView.vue         统计分析
│   ├── SettingsView.vue      时限设置
│   ├── VirtualCasesView.vue  预登记案件
│   ├── ModelManageView.vue   AI 模型配置管理
│   ├── AiReserveReviewView.vue  AI 预约审查（待审核列表 + 动态审查流程 + 结论卡片）
│   └── TianyanchaView.vue    天眼查（查企业候选列表 + 企业详情）
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

- 后端：`pytest backend/tests`（191 个用例，纯函数/内存测试，用假字典目录、不打内网/外网），按模块覆盖：
  - `test_health.py` 健康检查；
  - `test_case_submit.py` / `test_application_doc.py` 预登记提交载荷与仲裁申请书拼接（请求文本/金额/intro/fact_reason 四段式、多申请人编号、多被申请人"各被申请人共同"等）；
  - `test_complex_virtual_case.py` 复杂预登记案件全链路回归（多申请人 + 多被申请人 + 三类代理人 + 四种请求类型，验证 build_payload / build_draft / 申请书 parties/agents/requests/facts）；
  - `test_reserve_review.py` AI 预约审查纯函数（案件摘要 `build_case_payload` 字段抽取、提示词拼接 `build_messages`、结论解析 `parse_result` 的正常 JSON / ```json 围栏 / 非法 JSON / 非法结论 / 缺字段兜底、审核口径归类 `_normalize_decision`、证件照片收集 `collect_material_images`）；
  - `test_reserve_review_runner.py` 预约自动审核编排纯函数（`latest_review_map` 同案多条取最近一次、`is_valid_conclusion` 有效结论判定：通过/补正/驳回算已审出结果、审查失败/None 下轮重试）；
  - `test_reserve_review_decision.py` 人工审核结果 schema 校验（不同意缺理由/需补填未填 422、同意清空理由）+ 内网 preAudit 请求体组装 `compose_preaudit_payload`（同意空 reason/1、不同意「其他」「请补正」带冒号明细、长句理由原文、缺理由兜底「其他」）；
  - `test_reserve_decision_submit.py` `submit_decision_to_internal` 假客户端单测（URL/payload 正确、code 0/200 成功、HTTP 非 200/业务 code 非 200/非 JSON 抛 `CaseSystemError`）；
  - `test_vision.py` 视觉辅助（路径归一化、Ghostscript PDF→PNG 转图、`build_vision_messages` 多模态消息形状）；
  - `test_internal_case_urgency.py` / `test_internal_case_refetch.py` / `test_internal_case_verify.py` / `test_internal_case_pause.py` / `test_virtual_case_urgency.py` / `test_case_tags.py` 内网案件紧急度分档（含案前调解 30/45 天）、消失案件补拉、一致性对账、中止天数回填、预登记紧急度与案件记事本 subject_key/IP 提取/用户名绑定。
  - `test_tianyancha.py` 天眼查 MCP 集成（SSE 解析、工具挑选、入参构造、候选表/画像 Markdown 解析与字段归一化、API Key 存取脱敏、鉴权错误识别）。
  - 亦可手工跑一遍最小闭环——创建案件 → 触发"收件预审 AI" → 确认输出 → 查看时间线，验证各层是否正确联动。
- 前端：`npm run build`（`vue-tsc` 类型检查 + Vite 构建，产物即 nginx 服务目录）；`npm run dev` 后在浏览器中人工走查案件总览、办案进度监控、统计分析、时限设置等页面。
