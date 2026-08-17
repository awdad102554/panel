"""复杂预登记案件:多申请人 + 多被申请人 + 代理人 + 多种请求类型 的全链路组装测试。

用一个贴近真实的复杂案件(2 申请人 + 2 被申请人[企业+自然人] + 3 类代理人 +
4 种请求类型)验证各功能组合在一起时的正确性,重点覆盖单测各自为政时容易漏的
交叉问题:
- 多申请人 + 多被申请人同时作用:intro 既要加"申请人N"又要改"各被申请人共同"
- 各申请人合同/社保不一致:事实理由逐申请人各说各话,结构化字段取第一申请人
- 多申请人请求归属 applicant_index 贯穿提交体/申请书
- 多种请求类型(单选项金额 / 多选项 $str / 期间类 / 两级叶子)同案并存
- 申请书合计金额跨申请人聚合(object 与 items 求和混合)

字典/目录全部用假数据,不打内网。
"""

from datetime import date

import pytest

from app.services.case_submit import (
    RequestItem,
    RequestSpec,
    SubmitSpec,
    build_draft,
    build_payload,
)

# ---------------------------------------------------------------- 请求类型目录

CATALOG = [
    # 经济补偿争议(单选项 + 金额)
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 26, "code": "2", "name": "经济补偿争议"},
            {"id": 28, "code": "3", "name": "解除或终止劳动合同经济补偿争议"},
        ],
        "options": ["解除劳动合同的经济补偿", "终止劳动合同的经济补偿"],
        "template": "请求裁决被申请人向申请人支付选项1标的元",
    },
    # 社会保险争议 → 工伤保险待遇(多选项 $str)
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 11, "code": "2", "name": "社会保险争议"},
            {"id": 12, "code": "3", "name": "工伤保险待遇争议"},
        ],
        "options": ["医疗费", "住院期间伙食补助费", "停工留薪期工资"],
        "template": "请求裁决被申请人向申请人支付工伤保险待遇共计标的元（其中：$str）",
    },
    # 劳动报酬争议 → 工资争议(期间类)
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 3, "code": "2", "name": "劳动报酬争议"},
            {"id": 4, "code": "3", "name": "工资争议（基本工资、奖励性工资、津补贴）"},
        ],
        "options": [],
        "template": "请求裁决被申请人向申请人支付开始日期至结束日期期间的工资标的元",
    },
    # 确认劳动关系(两级叶子,无第三层、无金额)
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 18, "code": "2", "name": "确认劳动关系争议"},
        ],
        "options": [],
        "template": "请求确认申请人与被申请人于开始日期至结束日期期间存在劳动关系",
    },
]

CASE_REASON_DICT = [
    "劳动报酬争议", "社会保险争议", "经济补偿争议", "确认劳动关系争议", "赔偿争议",
]


# ---------------------------------------------------------------- 复杂案件数据

CASE = {
    "case_reason": "社会保险争议",
    "applicants": [
        {
            # 申请人1:老员工,工伤,签合同缴社保,带律师代理人,两种请求(多选项+单选项)
            "party_type": "natural",
            "name": "黄荣斌",
            "gender": "男",
            "ethnicity": "汉族",
            "birth_date": "1977-12-08",
            "id_number": "359001197712081010",
            "address": "永安市燕东永乐佳房37幢3单元301室",
            "phone": "18905987587",
            "entry_date": "2011-01-01",
            "work_place": "智胜化工股份有限公司",
            "position": "操作工",
            "monthly_wage": "3656.25",
            "is_sign_labor_contract": 1,
            "is_pay_social_insurance": 1,
            "main_causes": ["申请人负工伤，被申请人拒绝支付工伤保险待遇"],
            "facts": "于2024年2月1日在车间工作时被机器压伤右手。",
            "requests": [
                "请求裁决被申请人向申请人支付工伤保险待遇共计22571.63元（其中：（1）医疗费21911.63元、（2）住院期间伙食补助费660元）。",
                "请求裁决被申请人向申请人支付解除劳动合同的经济补偿53015.63元。",
            ],
            "request_specs": [
                {
                    "path_ids": [1, 11, 12],
                    "items": [
                        {"name": "医疗费", "object": 21911.63},
                        {"name": "住院期间伙食补助费", "object": 660},
                    ],
                },
                {
                    "path_ids": [1, 26, 28],
                    "option": "解除劳动合同的经济补偿",
                    "object": 53015.63,
                },
            ],
            "agents": [
                {
                    "name": "陈钦",
                    "agent_type": 6,
                    "agent_auth": "特别授权",
                    "id_type": "居民身份证（户口簿）",
                    "id_number": "35012119880711672X",
                    "mobile": "15280409500",
                    "law_firm_name": "泰和泰（福州）律师事务所",
                    "lawer_type": 1,
                    "is_legal_aid": 0,
                    "address": "福建省福州市台江区长汀街23号",
                }
            ],
        },
        {
            # 申请人2:新员工,未签合同未缴社保,带法定代理人,两种请求(两级叶子+期间类)
            "party_type": "natural",
            "name": "郭庆梅",
            "gender": "女",
            "ethnicity": "汉族",
            "birth_date": "1982-05-14",
            "id_number": "35048119820514204X",
            "address": "永安市西洋镇西洋村12号",
            "phone": "13859123456",
            "entry_date": "2021-03-01",
            "work_place": "智胜化工股份有限公司",
            "position": "包装工",
            "monthly_wage": "4000",
            "is_sign_labor_contract": 0,
            "is_pay_social_insurance": 0,
            "main_causes": ["被申请人未与本人签订书面劳动合同"],
            "requests": [
                "请求确认申请人与被申请人于2021年03月01日至2026年08月01日期间存在劳动关系",
                "请求裁决被申请人向申请人支付2026年07月01日至2026年08月15日期间的工资5500元。",
            ],
            "request_specs": [
                {"path_ids": [1, 18], "start_at": "2021-03-01", "end_at": "2026-08-01"},
                {
                    "path_ids": [1, 3, 4],
                    "object": 5500,
                    "start_at": "2026-07-01",
                    "end_at": "2026-08-15",
                },
            ],
            "agents": [
                {
                    "name": "张伟",
                    "agent_type": 1,
                    "relation": "配偶",
                    "id_number": "350481198001011234",
                    "mobile": "13799112233",
                }
            ],
        },
    ],
    "respondents": [
        {
            # 被申请人1:企业,带单位工作人员代理人
            "party_type": "company",
            "name": "智胜化工股份有限公司",
            "id_number": "91350400727934314R",
            "address": "永安市燕北街道坂尾村90号",
            "phone": "0598-3699336",
            "legal_person": "林辰生",
            "legal_title": "董事长",
            "registered_capital": 45000,
            "company_nature": "私营企业",
            "agents": [
                {
                    "name": "张冰",
                    "agent_type": 5,
                    "relation": "其他",
                    "select_other_content": "人事经理",
                    "sex": "男",
                }
            ],
        },
        {
            # 被申请人2:自然人(个体工商户/实际用工方),无代理人
            "party_type": "natural",
            "name": "陈永安",
            "gender": "男",
            "ethnicity": "汉族",
            "birth_date": "1975-09-20",
            "id_number": "350481197509206078",
            "address": "永安市贡川镇大坂村35号",
            "phone": "13605981234",
        },
    ],
}

# 正式提交用的 SubmitSpec(请求归属 applicant_index 贯穿提交体)
SPEC = SubmitSpec(
    apply_at=date(2026, 8, 17),
    case_reason="劳动报酬争议",
    is_sign_labor_contract=1,
    is_pay_social_insurance=1,
    main_causes=["申请人负工伤，被申请人拒绝支付工伤保险待遇"],
    requests=[
        RequestSpec(
            text="工伤保险待遇",
            path_ids=[1, 11, 12],
            applicant_index=0,
            items=[
                RequestItem(name="医疗费", object=21911.63),
                RequestItem(name="住院期间伙食补助费", object=660),
            ],
        ),
        RequestSpec(
            text="解除劳动合同经济补偿",
            path_ids=[1, 26, 28],
            applicant_index=0,
            option="解除劳动合同的经济补偿",
            object=53015.63,
        ),
        RequestSpec(
            text="确认劳动关系",
            path_ids=[1, 18],
            applicant_index=1,
            start_at=date(2021, 3, 1),
            end_at=date(2026, 8, 1),
        ),
        RequestSpec(
            text="支付拖欠工资",
            path_ids=[1, 3, 4],
            applicant_index=1,
            object=5500,
            start_at=date(2026, 7, 1),
            end_at=date(2026, 8, 15),
        ),
    ],
)


# ---------------------------------------------------------------- 提交内网请求体


def test_complex_payload_parties():
    """当事人拆分:2 申请人 + 1 自然人被申请人进 personals,1 企业进 companys。"""
    payload = build_payload(CASE, SPEC, CATALOG)
    personals = payload["personals"]
    assert [p["name"] for p in personals] == ["黄荣斌", "郭庆梅", "陈永安"]
    assert [p["role"] for p in personals] == [1, 1, 2]
    assert [p["related_user_type"] for p in personals] == [1, 1, 2]
    companys = payload["companys"]
    assert [c["name"] for c in companys] == ["智胜化工股份有限公司"]
    assert companys[0]["role"] == 2
    # 案件涉及人数(申请人)写进 case_info
    assert payload["case_info"]["involve_number"] == 2


def test_complex_payload_agents():
    """代理人挂各自当事人:律师/法定代理人/单位工作人员,无代理人当事人不带 agents 键。"""
    payload = build_payload(CASE, SPEC, CATALOG)
    personals = payload["personals"]
    # 申请人1 律师:type [None,6],带律所/授权
    a1 = personals[0]["agents"][0]
    assert a1["type"] == [None, 6]
    assert a1["law_firm_name"] == "泰和泰（福州）律师事务所"
    assert a1["agent_auth"] == "特别授权"
    assert a1["is_legal_aid"] == 0
    # 申请人2 法定代理人:type [1](单元素),带关系
    a2 = personals[1]["agents"][0]
    assert a2["type"] == [1]
    assert a2["relation"] == "配偶"
    # 企业 单位工作人员:type [None,5],关系"其他"文本进 select_other_content
    ca = payload["companys"][0]["agents"][0]
    assert ca["type"] == [None, 5]
    assert ca["relation"] == "其他"
    assert ca["select_other_content"] == "人事经理"
    # 自然人被申请人无代理人 → 不带 agents 键
    assert "agents" not in personals[2]


def test_complex_payload_requests_multi_type():
    """4 种请求类型同案:多选项/单选项/两级叶子/期间,归属加"申请人N"、多被申请人复数化。"""
    reqs = build_payload(CASE, SPEC, CATALOG)["arb_requests"]
    assert len(reqs) == 4

    # 工伤保险待遇(多选项 $str):object 求和,opt/level4_arr 明细
    r0 = reqs[0]
    assert [n["id"] for n in r0["type"]] == [1, 11, 12]
    assert r0["object"] == 22571.63
    assert r0["opt"] == [["医疗费", "住院期间伙食补助费"]]
    assert r0["level4_arr"] == [
        {"name": "医疗费", "object": 21911.63},
        {"name": "住院期间伙食补助费", "object": 660},
    ]
    assert "各被申请人共同向申请人1支付工伤保险待遇共计22571.63元" in r0["intro"]
    assert "（1）医疗费21911.63元、（2）住院期间伙食补助费660元" in r0["intro"]

    # 经济补偿(单选项)
    r1 = reqs[1]
    assert [n["id"] for n in r1["type"]] == [1, 26, 28]
    assert r1["object"] == 53015.63
    assert r1["intro"] == "请求裁决各被申请人共同向申请人1支付解除劳动合同的经济补偿53015.63元。"

    # 确认劳动关系(两级叶子,无金额):归属申请人2,不加"各被申请人共同"
    r2 = reqs[2]
    assert [n["id"] for n in r2["type"]] == [1, 18]
    assert r2["object"] is None
    assert r2["intro"] == "请求确认申请人2与被申请人于2021年03月01日至2026年08月01日期间存在劳动关系。"
    assert "各被申请人共同" not in r2["intro"]

    # 工资(期间):起止日期进 start_at/end_at
    r3 = reqs[3]
    assert [n["id"] for n in r3["type"]] == [1, 3, 4]
    assert r3["object"] == 5500
    assert r3["start_at"] == "2026-07-01"
    assert r3["end_at"] == "2026-08-15"
    assert r3["intro"] == "请求裁决各被申请人共同向申请人2支付2026年07月01日至2026年08月15日期间的工资5500元。"


def test_complex_payload_fact_reason():
    """事实理由:逐申请人四段式,合同/社保不一致各段各说各话,结构化字段取第一申请人。"""
    fr = build_payload(CASE, SPEC, CATALOG)["fact_reason"]
    content = fr["content"]
    # 逐申请人分段
    assert "申请人1于2011年01月01日入职被申请人处" in content
    assert "申请人2于2021年03月01日入职被申请人处" in content
    # 合同/社保不一致:各自表述
    assert "被申请人有与本人签订书面劳动合同,有为本人缴纳社会保险费" in content
    assert "被申请人没有与本人签订书面劳动合同,没有为本人缴纳社会保险费" in content
    # 补充事实 + 主因
    assert "于2024年2月1日在车间工作时被机器压伤右手" in content
    assert "因申请人负工伤，被申请人拒绝支付工伤保险待遇" in content
    assert "因被申请人未与本人签订书面劳动合同" in content
    # 固定结尾只出现一次
    assert content.endswith("为维护本人合法权益，特提出申请，望裁如所请。")
    assert content.count("为维护本人合法权益") == 1
    # 结构化字段(取第一申请人)
    assert fr["entry_at"] == "2011-01-01"
    assert fr["salary"] == 3656.25
    assert fr["actual_workplace"] == "智胜化工股份有限公司"
    assert fr["job"] == "操作工"
    # 案件级主因(预设原样入列)
    assert fr["main_cause"] == ["申请人负工伤，被申请人拒绝支付工伤保险待遇"]


# ---------------------------------------------------------------- 仲裁申请书


def test_complex_application_info():
    """申请书当事人信息:多申请人/多被申请人加编号。"""
    from app.services.application_doc import build_applicant_info, build_respondent_info

    ai = build_applicant_info(CASE["applicants"])
    assert "申请人1：黄荣斌" in ai
    assert "申请人2：郭庆梅" in ai
    ri = build_respondent_info(CASE["respondents"])
    assert "被申请人1：智胜化工股份有限公司" in ri
    assert "被申请人2：陈永安" in ri


def test_complex_application_requests_and_amount():
    """申请书请求段(编号+归属+复数化)与合计金额(object 与 items 求和混合聚合)。"""
    from app.services.application_doc import build_requests_text, build_total_amount

    rt = build_requests_text(CASE["applicants"], CASE["respondents"])
    assert "1.请求裁决各被申请人共同向申请人1支付工伤保险待遇共计22571.63元" in rt
    assert "2.请求裁决各被申请人共同向申请人1支付解除劳动合同的经济补偿53015.63元" in rt
    assert "3.请求确认申请人2与被申请人于2021年03月01日至2026年08月01日期间存在劳动关系" in rt
    assert "4.请求裁决各被申请人共同向申请人2支付2026年07月01日至2026年08月15日期间的工资5500元" in rt

    # 合计 = 工伤 items(22571.63) + 经济补偿(53015.63) + 工资(5500),确认劳动关系无金额
    assert build_total_amount(CASE["applicants"]) == "以上共计81087.26元。"


def test_complex_application_facts():
    """申请书事实理由:与提交内网同规则逐申请人拼接。"""
    from app.services.application_doc import build_facts_reasons

    fr = build_facts_reasons(CASE["applicants"], CASE["respondents"])
    assert "申请人1于2011年01月01日入职" in fr
    assert "申请人2于2021年03月01日入职" in fr
    assert "有与本人签订书面劳动合同" in fr
    assert "没有与本人签订书面劳动合同" in fr
    assert fr.endswith("现申请人为了维护自身的合法权益，特依法提起仲裁，望予以公正裁决。")


# ---------------------------------------------------------------- 提交草稿(draft)


@pytest.fixture
def fake_internal(monkeypatch):
    """build_draft 的内网依赖全部换假实现,不打内网。"""
    from app.services import case_submit

    async def _catalog():
        return CATALOG

    async def _towns():
        return []

    async def _dict(key):
        return [{"name": n} for n in CASE_REASON_DICT]

    async def _fill(_applicants, _respondents):
        return []

    monkeypatch.setattr(case_submit, "get_request_catalog", _catalog)
    monkeypatch.setattr(case_submit, "get_towns", _towns)
    monkeypatch.setattr(case_submit, "get_norm_dict", _dict)
    monkeypatch.setattr(case_submit, "_fill_company_info", _fill)
    return case_submit


async def test_complex_build_draft(fake_internal):
    """草稿:结构化请求不再猜文本,案由跟随最后一条请求,合同/社保不一致告警。"""
    draft = await build_draft(CASE)

    # 4 条请求都命中结构化路径(guessed=True),不用关键词猜
    assert len(draft["requests"]) == 4
    assert all(r["guessed"] for r in draft["requests"])
    assert draft["requests"][0]["path_ids"] == [1, 11, 12]
    assert draft["requests"][0]["object"] == 22571.63  # items 求和
    assert draft["requests"][1]["path_ids"] == [1, 26, 28]
    assert draft["requests"][2]["path_ids"] == [1, 18]  # 两级叶子
    assert draft["requests"][3]["path_ids"] == [1, 3, 4]

    # 案由跟随最后一条请求(工资争议 → 劳动报酬争议)
    assert draft["defaults"]["case_reason"] == "劳动报酬争议"

    # 各申请人合同/社保不一致 → 两条告警
    joined = "；".join(draft["warnings"])
    assert "劳动合同签订情况" in joined
    assert "社保缴纳情况" in joined

    # 事实理由逐申请人(与提交组装同规则)
    assert "申请人1于2011年01月01日入职" in draft["fact_content"]
    assert "申请人2于2021年03月01日入职" in draft["fact_content"]
