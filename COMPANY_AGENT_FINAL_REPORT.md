# 企业委托代理人数据库 - 完成报告

## 问题诊断

**原始问题：** 用户报告"不可能只有 0 条代理人数据"

**根本原因：**
- ❌ 列表接口（`/arb/reserve`, `/arb/receive`, `/arb/handle`）的 `raw_payload` **不包含** `agents` 字段
- ✅ 只有详情接口（`POST /v1/api/admin/case/caseData`）才返回完整的当事人信息，包括 `agents` 数组
- ❌ 原实现从列表接口的 `raw_payload` 提取，所以永远找不到代理人

**验证过程：**
1. 查询数据库 2351 条记录 → 0 条有 agents
2. 用户提供案件示例：InfoWeb `/api/handle/detail?id=240149` → 有代理人"黄志强"
3. 对比发现：InfoWeb 调用的是详情接口，不是列表接口
4. 修改提取逻辑：改为调用 `POST /v1/api/admin/case/caseData` 获取完整数据

## 最终实现

### 核心改动

1. **app/services/company_agents.py**
   - 新增 `_fetch_case_detail()` - 调用内网详情接口
   - 重构 `_extract_bindings_from_detail()` - 从详情数据提取
   - 更新 `extract_and_upsert_bindings()` - 只处理 handle 阶段案件
   - 更新 `initialize_from_all_snapshots()` - 从所有 handle 案件初始化

2. **app/services/internal_case_sync.py**
   - 修复：临时对象增加 `stage` 字段
   - 集成自动提取到轻量同步流程

3. **scripts/test_company_agents.py**
   - 新增：综合测试脚本，验证统计和查询功能

### 技术细节

**详情接口调用：**
```python
resp = await client.post(
    "/v1/api/admin/case/caseData",
    json={"id": handle_row_id}  # raw_payload.id
)
```

**返回数据结构：**
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

## 最终结果

### 数据统计（2026-08-28 初始化完成）

```
✓ 企业委托代理人数据库统计
  1607 条绑定记录
  374 家公司
  377 个代理人
  1521/2238 个案件有代理人 (68.0%)

  按类型分布:
    单位工作人员: 1306
    律师: 293
    近亲属: 6
    法律服务工作者: 2
```

### 性能数据

- **处理案件数：** 2238 个 handle 阶段案件
- **详情接口调用：** 2238 次
- **总耗时：** 约 11 分 27 秒
- **平均速度：** 0.3 秒/案件
- **成功率：** 68% 的案件有代理人数据

### 查询功能验证

**测试 1：按公司查询**
```
公司: 永安市佳洁贸易有限公司
结果: 315 条记录
代理人: 黄静（单位工作人员）
```

**测试 2：按代理人查询**
```
代理人: 王秋生（律师）
结果: 33 条记录
公司: 永安市前林煤业有限责任公司、福建省八一村永庆竹木业开发有限责任公司 等
```

**测试 3：用户提供的案例**
```
案件: 337713（明永劳人仲案字[2026]202号）
公司: 建新轮胎（福建）有限公司
代理人: 黄志强（律师）
律所: 福建永杭律师事务所
电话: 18650983770
✓ 数据完整，提取成功
```

## 功能特点

### 1. 自动增量更新
- 集成到内网轻量同步流程
- 只处理新增/更新的 handle 阶段案件
- 失败不影响主同步流程

### 2. 双向查询
- 按公司名查历年代理人（模糊匹配）
- 按代理人名查代理过的案件（模糊匹配）
- 结果按立案时间倒序

### 3. 数据完整性
- 唯一约束：(company_name, agent_name, external_case_id)
- 包含代理人类型、电话、律所、身份证号
- 区分申请人/被申请人角色

### 4. 历史留痕
- 代理人信息变更不覆盖，保留历史记录
- 记录创建时间和更新时间

## API 端点

```bash
# 按公司查询
GET /api/v1/company-agents/by-company?company_name=xxx

# 按代理人查询
GET /api/v1/company-agents/by-agent?agent_name=xxx

# 初始化（一次性操作）
POST /api/v1/company-agents/initialize
```

## 使用指南

### 初始化（首次运行）

```bash
# 方法 1：运行脚本（推荐）
./venv/bin/python scripts/initialize_company_agents.py

# 方法 2：通过 API
curl -X POST http://localhost:6543/api/v1/company-agents/initialize
```

**注意：** 初始化需要约 11 分钟，会调用 2238 次详情接口。

### 测试验证

```bash
# 运行综合测试
./venv/bin/python scripts/test_company_agents.py
```

### 查询示例

```python
from app.services.company_agents import list_agents_by_company, list_cases_by_agent

# 查询某公司的代理人
agents = await list_agents_by_company(session, "建新轮胎")

# 查询某代理人的案件
cases = await list_cases_by_agent(session, "黄志强")
```

## 注意事项

1. **只处理 handle 阶段案件**
   - reserve/receive 阶段没有 `raw_payload.id`
   - 无法调用详情接口

2. **每个案件需要一次详情接口调用**
   - 初始化较慢（2238 个案件约 11 分钟）
   - 增量更新很快（只处理新增/更新的案件）

3. **失败不阻塞主流程**
   - 详情接口失败只记 warning
   - 不影响内网案件同步

4. **数据覆盖率**
   - 68% 的案件有代理人（1521/2238）
   - 32% 的案件无代理人（公司方自行参与或个人案件）

## 测试结果

### 功能测试
- ✅ 详情接口调用
- ✅ 数据提取逻辑
- ✅ UPSERT 去重
- ✅ 按公司查询
- ✅ 按代理人查询
- ✅ 增量同步集成

### 性能测试
- ✅ 2238 个案件全量初始化（11 分 27 秒）
- ✅ 平均 0.3 秒/案件
- ✅ 无内存溢出（分批处理）

### 数据质量
- ✅ 1607 条记录无重复
- ✅ 公司/代理人关系准确
- ✅ 案号、立案时间完整

## 对比：修复前后

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 绑定记录数 | 0 | 1607 |
| 涉及公司 | 0 | 374 |
| 涉及代理人 | 0 | 377 |
| 覆盖率 | 0% | 68% |
| 数据来源 | 列表接口（无 agents） | 详情接口（有 agents） |

## 总结

✅ **问题已解决**：从 0 条记录到 1607 条记录

✅ **根因已定位**：列表接口不返回 agents 字段，必须调用详情接口

✅ **功能已验证**：提取、存储、查询全流程通过测试

✅ **增量更新已集成**：每次轻量同步自动更新

✅ **性能可接受**：初始化 11 分钟，增量更新秒级

---

**生成时间：** 2026-08-28  
**初始化耗时：** 11 分 27 秒  
**测试状态：** ✓ 所有测试通过
