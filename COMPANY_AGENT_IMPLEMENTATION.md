# 企业委托代理人数据库功能实现总结

## 功能概述

从内网案件详情接口提取公司-代理人绑定关系，建立历史数据库，支持：
1. 查询某公司历年用过哪些代理人
2. 查询某代理人代理过哪些案件
3. 每次轻量同步自动增量更新

## 核心发现

**列表接口不返回代理人信息！**

- 列表接口（`/arb/reserve`, `/arb/receive`, `/arb/handle`）的 `raw_payload` **不包含** `agents` 字段
- 只有详情接口（`POST /v1/api/admin/case/caseData`）才返回完整的当事人信息，包括 `agents` 数组
- 因此必须调用详情接口才能获取代理人数据

## 实现的文件

### 后端

1. **app/models/company_agent.py** - 数据模型
   - CompanyAgentBinding 表（公司-代理人-案件三元组）
   - 唯一约束：(company_name, agent_name, external_case_id)
   - 索引：company_name, agent_name, external_case_id, filed_at

2. **app/services/company_agents.py** - 业务逻辑
   - `_fetch_case_detail()` - 调用内网详情接口获取完整案件数据
   - `_extract_bindings_from_detail()` - 从详情数据提取绑定
   - `extract_and_upsert_bindings()` - 批量 UPSERT（只处理 handle 阶段案件）
   - `initialize_from_all_snapshots()` - 全量初始化（从所有 handle 案件）
   - `list_agents_by_company()` - 按公司查询
   - `list_cases_by_agent()` - 按代理人查询

3. **app/api/v1/company_agents.py** - API 路由
   - GET /company-agents/by-company?company_name=xxx
   - GET /company-agents/by-agent?agent_name=xxx
   - POST /company-agents/initialize (初始化)

4. **app/api/v1/router.py** - 注册路由
   - 已添加 company_agents 路由

5. **app/services/internal_case_sync.py** - 集成到同步流程
   - 同步完成后自动调用 extract_and_upsert_bindings()
   - 只处理新增/更新的 handle 阶段案件（增量更新）
   - 失败不影响主同步流程
   - 已修复：添加 stage 字段到临时对象

6. **scripts/initialize_company_agents.py** - 初始化脚本
   - 一次性从所有 handle 阶段案件提取历史数据
   - 每个案件调用一次详情接口

7. **alembic/versions/add_company_agent_bindings.py** - 数据库迁移

### 前端

1. **frontend/src/api/companyAgent.ts** - API 客户端
   - getAgentsByCompany()
   - getCasesByAgent()
   - initializeCompanyAgentDatabase()

2. **frontend/src/components/CompanyAgentDatabasePanel.vue** - UI 组件
   - 双模式搜索（按公司/按代理人）
   - 结果分组展示
   - 可嵌入预登记"保存到内网"页右侧

## 数据提取逻辑

**关键点：必须调用详情接口！**

1. 对于 handle 阶段案件，从 `raw_payload.id` 获取内网 handle 表主键
2. 调用 `POST /v1/api/admin/case/caseData` 获取完整案件数据
3. 从详情数据的 `respondent_arr` 和 `applicant_arr` 提取 `agents` 数组

提取规则：

1. **被申请人（主要）**：遍历 respondent_arr
   - 判断是公司：有 social_code 或 company_nature
   - 提取 agents 数组

2. **申请人（次要）**：当至少有一个被申请人是公司时
   - 遍历 applicant_arr 中的公司
   - 提取 agents 数组

3. **代理人类型**：从 agent.type 列表取最后一个元素
   - 1=法定代理人, 2=指定代理人, 3=近亲属
   - 4=团体推荐, 5=单位工作人员
   - 6=律师, 7=法律服务工作者

## 使用流程

### 1. 创建数据库表

```bash
# 方式1：运行迁移（如果使用 alembic）
cd backend
alembic upgrade head

# 方式2：手动执行建表 SQL（见迁移文件）
```

### 2. 初始化历史数据

```bash
# 方式1：通过 API（需启动服务）
curl -X POST http://localhost:8000/api/v1/company-agents/initialize

# 方式2：运行脚本
cd backend
./venv/bin/python scripts/initialize_company_agents.py
```

**注意：** 初始化会调用所有 handle 阶段案件的详情接口，耗时较长（2238 个案件约需 11 分钟）。

### 3. 查询示例

```bash
# 查询某公司的代理人
curl "http://localhost:8000/api/v1/company-agents/by-company?company_name=建新轮胎"

# 查询某代理人的案件
curl "http://localhost:8000/api/v1/company-agents/by-agent?agent_name=黄志强"
```

### 4. 自动更新

每次内网轻量同步后自动增量更新，只对新增/更新的 handle 阶段案件调用详情接口。

## 实测数据（2026-08-28）

从 2238 个 handle 阶段案件中提取：
- **1258+** 条绑定记录
- **287+** 家公司
- **284+** 个代理人

按类型分布：
- 单位工作人员: 1054+
- 律师: 197+
- 近亲属: 5
- 法律服务工作者: 2

## 注意事项

1. **数据来源限制**：
   - 只能处理 handle 阶段的案件（reserve/receive 阶段没有 raw_payload.id）
   - 列表接口不返回 agents 字段，必须调用详情接口
   - 每个案件需要一次详情接口调用（较慢）

2. **公司判定**：依赖 social_code 或 company_nature 字段

3. **时区处理**：filed_at 存储为 UTC 时间，前端显示时自动转本地时区

4. **唯一约束**：同一公司、同一代理人、同一案件只记录一次

5. **历史留痕**：代理人信息变更不覆盖，保留历史记录

6. **性能考虑**：
   - 初始化需要调用 2238+ 次详情接口，约 11 分钟
   - 增量同步只处理新增/更新的案件，速度快
   - 失败不影响主同步流程

## 已完成的测试

✓ 模型导入测试
✓ 服务函数测试（详情接口调用）
✓ 提取逻辑验证（案件 337713 成功提取代理人"黄志强"）
✓ API 路由注册
✓ 前端组件结构
✓ 增量同步集成（已修复 stage 字段）

## 后续工作

1. 等待初始化完成（后台进程正在运行）
2. 在预登记"保存到内网"页面嵌入 CompanyAgentDatabasePanel 组件
3. 前端测试查询功能
4. 验证轻量同步时的自动更新

## 技术细节

### 详情接口调用

```python
# 参考 internal_case_pause.py 的实现
resp = await client.post(
    "/v1/api/admin/case/caseData",
    json={"id": handle_row_id}  # raw_payload.id
)
```

### 返回数据结构

```json
{
  "data": {
    "respondent_arr": [{
      "name": "建新轮胎（福建）有限公司",
      "social_code": "91350481699040291G",
      "agents": [{
        "name": "黄志强",
        "type": ["", 6],
        "mobile": "18650983770",
        "law_firm_name": "福建永杭律师事务所"
      }]
    }]
  }
}
```
