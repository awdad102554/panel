"""预登记案件提交内网(services/case_submit.py)的单元测试。

字典/目录全部用假数据,不打内网。请求体结构对齐 2026-08-11 内网 receive/add 抓包样例。
"""

from datetime import date

import pytest

from app.services.case_submit import (
    RequestItem,
    SubmitSpec,
    RequestSpec,
    build_payload,
    guess_amount,
    guess_request,
    validate_case,
    _fill_template,
)

CATALOG = [
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 26, "code": "2", "name": "经济补偿争议"},
            {"id": 28, "code": "3", "name": "解除或终止劳动合同经济补偿争议"},
        ],
        "options": ["解除劳动合同的经济补偿", "终止劳动合同的经济补偿", "未提前通知劳动者解除劳动合同的一个月工资"],
        "template": "请求裁决被申请人向申请人支付选项1标的元",
    },
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 27, "code": "2", "name": "赔偿争议"},
            {"id": 30, "code": "3", "name": "违法解除劳动合同赔偿金争议"},
        ],
        "options": ["违法解除劳动合同赔偿金"],
        "template": "请求裁决被申请人向申请人支付选项1标的元",
    },
    {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 5, "code": "2", "name": "确认劳动关系争议"},
            {"id": 6, "code": "3", "name": "确认劳动关系争议"},
        ],
        "options": [],
        "template": "请求裁决确认申请人与被申请人自选项1起存在劳动关系",
    },
]

CASE = {
    "case_reason": "经济补偿争议",
    "claims": None,
    "applicants": [
        {
            "party_type": "natural",
            "name": "黄荣斌",
            "id_number": "359001197712081010",
            "gender": "男",
            "ethnicity": "汉族",
            "birth_date": "1977-12-08",
            "address": "永安市燕东永乐佳房37幢3单元301室",
            "phone": "18905987587",
            "entry_date": "2011-01-01",
            "monthly_wage": "3656.25",
            "requests": ["请求裁决被申请人向申请人支付解除劳动合同的经济补偿53015.63元。"],
            "facts": "本人于2011年入职……",
        }
    ],
    "respondents": [
        {
            "party_type": "company",
            "name": "智胜化工股份有限公司",
            "id_number": "91350400727934314R",
            "address": "永安市燕北街道坂尾村90号",
            "phone": "0598-3699336",
            "legal_person": "林辰生",
            "legal_title": "董事长",
            "registered_capital": 45000,
        }
    ],
}

SPEC = SubmitSpec(
    apply_at=date(2026, 5, 20),
    case_reason="经济补偿争议",
    requests=[
        RequestSpec(
            text="请求裁决被申请人向申请人支付解除劳动合同的经济补偿53015.63元。",
            path_ids=[1, 26, 28],
            option="解除劳动合同的经济补偿",
            object=53015.63,
        )
    ],
)


def test_guess_request_by_option():
    g = guess_request("被申请人支付申请人违法解除劳动合同赔偿金4600元", CATALOG)
    assert g is not None
    assert g["path_ids"] == [1, 27, 30]
    assert g["option"] == "违法解除劳动合同赔偿金"


def test_guess_request_no_match():
    assert guess_request("要求单位赔礼道歉", CATALOG) is None


def test_guess_amount_prefers_option_context():
    text = "被申请人支付申请人违法解除劳动合同赔偿金 4600元。（计算标准：2300 × 1 个月 × 2 = 4600元）"
    assert guess_amount(text, "违法解除劳动合同赔偿金") == 4600.0
    assert guess_amount("没有金额的描述", None) is None
    # 万元与千分位
    assert guess_amount("拖欠工资2万元", None) == 20000.0
    assert guess_amount("赔偿金10,000元", None) == 10000.0


def test_items_missing_amount_rejected():
    """多选项请求任一项缺金额必须拒绝(静默求部分和会造成总额≠明细)。"""
    leaf = {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 11, "code": "2", "name": "社会保险争议"},
            {"id": 12, "code": "3", "name": "工伤保险待遇争议"},
        ],
        "options": ["医疗费", "住院期间伙食补助费"],
        "template": "请求裁决被申请人向申请人支付工伤保险待遇共计标的元（其中：$str）",
    }
    spec = SubmitSpec(
        apply_at=date(2026, 8, 10),
        case_reason="确认劳动关系",
        requests=[
            RequestSpec(
                text="工伤待遇",
                path_ids=[1, 11, 12],
                items=[RequestItem(name="医疗费", object=100), RequestItem(name="住院期间伙食补助费")],
            )
        ],
    )
    with pytest.raises(ValueError, match="每个费用项都需要金额"):
        build_payload(CASE, spec, CATALOG + [leaf])


def test_fill_template():
    assert (
        _fill_template("请求裁决被申请人向申请人支付选项1标的元", "解除劳动合同的经济补偿", 53015.63)
        == "请求裁决被申请人向申请人支付解除劳动合同的经济补偿53015.63元。"
    )
    # 缺金额/含 $str 的模板不可填充
    assert _fill_template("请求裁决被申请人向申请人支付选项1标的元", "x", None) is None
    assert _fill_template("请求裁决……共计标的元（其中：$str）", "x", 1.0) is None


def test_build_payload_matches_sample_structure():
    payload = build_payload(CASE, SPEC, CATALOG)
    assert set(payload) == {
        "case_info", "personals", "companys", "arb_requests", "fact_reason",
        "evidence_materials", "materials", "receive_info", "case_med_doc", "speed_arb_factor",
    }
    ci = payload["case_info"]
    assert ci["case_reason"] == "经济补偿争议"
    assert ci["case_source"] == "申请人窗口申请"
    assert ci["town_id"] == 350481001000
    assert ci["position"][-1] == {"Id": 350481000000, "name": "永安市"}

    person = payload["personals"][0]
    assert person["role"] == 1 and person["related_user_type"] == 1
    assert person["id_number"] == "359001197712081010"
    assert person["birth"] == "1977-12-08"

    company = payload["companys"][0]
    assert company["registered_capital"] == 45000.0
    assert company["company_nature"] == "私营企业"
    assert company["legal_name"] == "林辰生"

    req = payload["arb_requests"][0]
    assert [n["id"] for n in req["type"]] == [1, 26, 28]
    assert req["object"] == 53015.63
    assert req["intro"] == "请求裁决被申请人向申请人支付解除劳动合同的经济补偿53015.63元。"
    assert req["opt"] == [["解除劳动合同的经济补偿"]]
    assert req["level4_arr"] == [{"name": "解除劳动合同的经济补偿", "object": 53015.63}]

    fr = payload["fact_reason"]
    assert fr["entry_at"] == "2011-01-01"
    assert fr["salary"] == 3656.25
    assert fr["content"] == "本人于2011年入职……"
    assert payload["receive_info"] == {"next_step": 1, "application_at": "2026-05-20"}


def test_build_payload_rejects_bad_path():
    bad = SubmitSpec(
        apply_at=date(2026, 5, 20),
        case_reason="经济补偿争议",
        requests=[RequestSpec(text="x", path_ids=[1, 26, 999])],
    )
    with pytest.raises(ValueError, match="路径无效"):
        build_payload(CASE, bad, CATALOG)


def test_build_payload_intro_falls_back_to_text():
    spec = SubmitSpec(
        apply_at=date(2026, 5, 20),
        case_reason="确认劳动关系争议",
        requests=[RequestSpec(text="请求确认双方存在劳动关系", path_ids=[1, 5, 6])],
    )
    payload = build_payload(CASE, spec, CATALOG)
    req = payload["arb_requests"][0]
    assert req["intro"] == "请求确认双方存在劳动关系"
    assert req["opt"] == [[]]
    assert req["level4_arr"] == []


def test_fill_template_multi_items():
    """样例2:$str 模板+多选项枚举(工伤保险待遇)。"""
    tpl = "请求裁决被申请人向申请人支付工伤保险待遇共计标的元（其中：$str）"
    items = [
        RequestItem(name="医疗费", object=21911.63),
        RequestItem(name="住院期间伙食补助费", object=660),
    ]
    assert _fill_template(tpl, None, 22571.63, items) == (
        "请求裁决被申请人向申请人支付工伤保险待遇共计22571.63元"
        "（其中：（1）医疗费21911.63元、（2）住院期间伙食补助费660元）。"
    )
    # items 缺金额则不可填充
    bad = [RequestItem(name="医疗费", object=None)]
    assert _fill_template(tpl, None, 1.0, bad) is None


def test_build_payload_multi_option_request():
    """样例2:多选项请求 opt/level4_arr/object(求和)/intro 结构。"""
    leaf = {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 11, "code": "2", "name": "社会保险争议"},
            {"id": 12, "code": "3", "name": "工伤保险待遇争议"},
        ],
        "options": ["医疗费", "住院期间伙食补助费", "停工留薪期工资"],
        "template": "请求裁决被申请人向申请人支付工伤保险待遇共计标的元（其中：$str）",
    }
    catalog = CATALOG + [leaf]
    spec = SubmitSpec(
        apply_at=date(2026, 8, 10),
        case_reason="确认劳动关系",
        is_easy=0,
        requests=[
            RequestSpec(
                text="请求裁决被申请人支付工伤保险待遇",
                path_ids=[1, 11, 12],
                items=[
                    RequestItem(name="医疗费", object=21911.63),
                    RequestItem(name="住院期间伙食补助费", object=660),
                ],
            )
        ],
    )
    payload = build_payload(CASE, spec, catalog)
    req = payload["arb_requests"][0]
    assert req["object"] == 22571.63
    assert req["opt"] == [["医疗费", "住院期间伙食补助费"]]
    assert req["level4_arr"] == [
        {"name": "医疗费", "object": 21911.63},
        {"name": "住院期间伙食补助费", "object": 660},
    ]
    assert "共计22571.63元（其中：（1）医疗费21911.63元、（2）住院期间伙食补助费660元）" in req["intro"]
    assert payload["case_info"]["is_easy"] == 0
    fr = payload["fact_reason"]
    assert fr["actual_workplace"] == CASE["applicants"][0].get("work_place")
    assert fr["is_sign_labor_contract"] == 1
    # 多选项名称必须在字典内
    bad_spec = spec.model_copy(deep=True)
    bad_spec.requests[0].items = [RequestItem(name="不存在的费用", object=1)]
    with pytest.raises(ValueError, match="不在字典"):
        build_payload(CASE, bad_spec, catalog)


def test_compose_facts_and_overrides():
    """事实理由自动生成(内网模板) + main_cause/fact_content 覆盖。"""
    from app.services.case_submit import compose_facts

    first = CASE["applicants"][0]
    text = compose_facts(first, 1, 1, ["被申请人违法解除与申请人劳动关系，请求支付赔偿金"])
    assert text == (
        "本人于2011年01月01日入职被申请人处, 月工资标准为3656.25元。"
        "本人入职后，被申请人有与本人签订书面劳动合同,有为本人缴纳社会保险费;"
        "因被申请人违法解除与申请人劳动关系，请求支付赔偿金。"
        "为维护本人合法权益，特提出申请，望裁如所请。"
    )
    # 多主因:顿号连接
    text_multi = compose_facts(first, 1, 1, ["申请人负工伤，被申请人拒绝支付工伤保险待遇", "其他补充"])
    assert "因申请人负工伤，被申请人拒绝支付工伤保险待遇，其他补充。" in text_multi
    # 无主因:分号变句号
    text2 = compose_facts(first, 0, 0)
    assert "没有与本人签订书面劳动合同,没有为本人缴纳社会保险费。为维护" in text2
    # 缺入职信息:省略首段
    assert compose_facts({}, 1, 1).startswith("本人入职后")

    # spec.fact_content 优先于 facts/自动生成
    case_no_facts = {
        **CASE,
        "applicants": [{**CASE["applicants"][0], "facts": None}],
    }
    spec = SubmitSpec(
        apply_at=date(2026, 5, 20),
        case_reason="经济补偿争议",
        main_causes=["被申请人拖欠工资"],
        fact_content="手工编辑的事实理由。",
        requests=[RequestSpec(text="x", path_ids=[1, 26, 28], option="解除劳动合同的经济补偿", object=1)],
    )
    fr = build_payload(case_no_facts, spec, CATALOG)["fact_reason"]
    assert fr["content"] == "手工编辑的事实理由。"
    # 非预设文本视为"其他":[None, 文本](样例1)
    assert fr["main_cause"] == [None, "被申请人拖欠工资"]
    # 预设原样入列
    spec_preset = spec.model_copy(update={"main_causes": ["申请人负工伤，被申请人拒绝支付工伤保险待遇"]})
    fr_p = build_payload(case_no_facts, spec_preset, CATALOG)["fact_reason"]
    assert fr_p["main_cause"] == ["申请人负工伤，被申请人拒绝支付工伤保险待遇"]
    # 不给 fact_content/facts:自动生成
    spec2 = spec.model_copy(update={"fact_content": None})
    fr2 = build_payload(case_no_facts, spec2, CATALOG)["fact_reason"]
    assert fr2["content"].startswith("本人于2011年01月01日入职")
    assert "因被申请人拖欠工资。" in fr2["content"]


def test_worker_flags():
    """农民工/三期女职工开关作用于全部申请人,默认 0(否)。"""
    spec = SubmitSpec(
        apply_at=date(2026, 5, 20),
        case_reason="经济补偿争议",
        is_migrant_worker=1,
        is_three_woman_worker=1,
        requests=[RequestSpec(text="x", path_ids=[1, 26, 28], option="解除劳动合同的经济补偿", object=1)],
    )
    person = build_payload(CASE, spec, CATALOG)["personals"][0]
    assert person["is_migrant_worker"] == 1
    assert person["is_three_woman_worker"] == 1
    default = build_payload(CASE, SPEC, CATALOG)["personals"][0]
    assert default["is_migrant_worker"] == 0
    assert default["is_three_woman_worker"] == 0


def test_agents_attached_per_party():
    """样例3:代理人挂在当事人 agents 键;type 末元素为类型码。"""
    case = {
        **CASE,
        "applicants": [
            {
                **CASE["applicants"][0],
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
                    },
                    {"name": "类型不合法", "agent_type": 99},
                ],
            }
        ],
        "respondents": [
            {
                **CASE["respondents"][0],
                "agents": [
                    {
                        "name": "张冰",
                        "agent_type": 1,
                        "relation": "其他",
                        "select_other_content": "员工",
                        "sex": "男",
                    }
                ],
            }
        ],
    }
    payload = build_payload(case, SPEC, CATALOG)
    agents = payload["personals"][0]["agents"]
    assert len(agents) == 1  # 类型不合法的跳过
    a = agents[0]
    assert a["type"] == [None, 6]
    assert a["is_common"] == 0 and a["add_e_delivery"] == 0
    assert a["law_firm_name"] == "泰和泰（福州）律师事务所"
    assert a["agent_auth"] == "特别授权"
    assert "relation" not in a  # 未填的可选键不出现
    ca = payload["companys"][0]["agents"][0]
    assert ca["type"] == [1]
    assert ca["relation"] == "其他" and ca["select_other_content"] == "员工"
    # 无代理人当事人不带 agents 键
    assert "agents" not in build_payload(CASE, SPEC, CATALOG)["personals"][0]


def test_date_range_request():
    """样例3:模板含 开始日期/结束日期 的期间类请求(工资争议)。"""
    leaf = {
        "path": [
            {"id": 1, "code": "1", "name": "劳动争议"},
            {"id": 3, "code": "2", "name": "劳动报酬争议"},
            {"id": 4, "code": "3", "name": "工资争议（基本工资、奖励性工资、津补贴）"},
        ],
        "options": [],
        "template": "请求裁决被申请人向申请人支付开始日期至结束日期期间的工资标的元",
    }
    catalog = CATALOG + [leaf]
    spec = SubmitSpec(
        apply_at=date(2026, 8, 11),
        case_reason="确认劳动关系",
        requests=[
            RequestSpec(
                text="请求支付工资",
                path_ids=[1, 3, 4],
                object=0,
                start_at=date(2026, 7, 29),
                end_at=date(2026, 8, 20),
            )
        ],
    )
    req = build_payload(CASE, spec, catalog)["arb_requests"][0]
    assert req["intro"] == "请求裁决被申请人向申请人支付2026年07月29日至2026年08月20日期间的工资0元。"
    assert req["start_at"] == "2026-07-29" and req["end_at"] == "2026-08-20"
    assert req["opt"] == [[]] and req["level4_arr"] == []
    # 缺日期则模板不可填,退回自由文本
    spec2 = spec.model_copy(deep=True)
    spec2.requests[0].start_at = None
    req2 = build_payload(CASE, spec2, catalog)["arb_requests"][0]
    assert req2["intro"] == "请求支付工资"


def test_validate_case():
    errors, warnings = validate_case(CASE)
    assert errors == []
    bad = {**CASE, "applicants": [{"name": "张三", "requests": ["要钱"]}]}
    errors, _ = validate_case(bad)
    assert any("身份证" in e for e in errors)



CASE_REASON_DICT = [
    "劳动报酬争议", "社会保险争议", "确认劳动关系争议", "合同争议",
    "经济补偿争议", "赔偿争议", "劳动标准及保护争议", "福利待遇争议", "其他劳动争议",
]


@pytest.fixture
def fake_internal(monkeypatch):
    """build_draft 的内网依赖全部换假实现,不打内网。"""
    from app.services import case_submit

    async def _catalog():
        return CATALOG

    async def _towns():
        return []

    async def _dict(key):
        if key == "case_reason":
            return [{"name": n} for n in CASE_REASON_DICT]
        return [{"name": "私营企业"}]

    async def _fill(_applicants, _respondents):
        return []

    monkeypatch.setattr(case_submit, "get_request_catalog", _catalog)
    monkeypatch.setattr(case_submit, "get_towns", _towns)
    monkeypatch.setattr(case_submit, "get_norm_dict", _dict)
    monkeypatch.setattr(case_submit, "_fill_company_info", _fill)
    return case_submit


async def test_build_draft_case_reason_follows_first_request(fake_internal):
    """案由默认值跟随第一条请求的第二层类型(内网规律),覆盖案件已填的自由文本。"""
    case = {**CASE, "case_reason": "确认劳动关系"}
    draft = await fake_internal.build_draft(case)
    assert draft["requests"][0]["path_names"][1] == "经济补偿争议"
    assert draft["defaults"]["case_reason"] == "经济补偿争议"


async def test_build_draft_case_reason_fallback_to_filled(fake_internal):
    """请求猜不出类型时,退回案件已填值的字典模糊匹配。"""
    case = {
        **CASE,
        "case_reason": "确认劳动关系",
        "applicants": [dict(CASE["applicants"][0], requests=["要求单位赔礼道歉"])],
    }
    draft = await fake_internal.build_draft(case)
    assert draft["requests"][0]["guessed"] is False
    assert draft["defaults"]["case_reason"] == "确认劳动关系争议"


async def test_build_draft_uses_stored_request_spec(fake_internal):
    """存了结构化请求:直接用存的类型/金额,不猜文本;文本与模板一致时 intro 为空。"""
    case = {
        **CASE,
        "applicants": [
            dict(
                CASE["applicants"][0],
                request_specs=[
                    {
                        "path_ids": [1, 26, 28],
                        "path_names": ["劳动争议", "经济补偿争议", "解除或终止劳动合同经济补偿争议"],
                        "option": "解除劳动合同的经济补偿",
                        "object": 53015.63,
                    }
                ],
            )
        ],
    }
    draft = await fake_internal.build_draft(case)
    entry = draft["requests"][0]
    assert entry["path_ids"] == [1, 26, 28]
    assert entry["option"] == "解除劳动合同的经济补偿"
    assert entry["object"] == 53015.63
    assert entry["guessed"] is True and entry["intro"] is None


async def test_build_draft_spec_edited_text_goes_to_intro(fake_internal):
    """用户在表单里改过请求文本(与模板生成不一致):文本进 intro 随提交走。"""
    edited = "请求裁决被申请人支付解除劳动合同的经济补偿53015.63元(含利息)。"
    case = {
        **CASE,
        "applicants": [
            dict(
                CASE["applicants"][0],
                requests=[edited],
                request_specs=[
                    {
                        "path_ids": [1, 26, 28],
                        "option": "解除劳动合同的经济补偿",
                        "object": 53015.63,
                    }
                ],
            )
        ],
    }
    draft = await fake_internal.build_draft(case)
    assert draft["requests"][0]["intro"] == edited


async def test_build_draft_stale_spec_falls_back_to_guess(fake_internal):
    """存的类型已不在内网目录(目录改版):退回文本猜测并提示重新选择。"""
    case = {
        **CASE,
        "applicants": [
            dict(
                CASE["applicants"][0],
                request_specs=[{"path_ids": [1, 26, 999], "option": "解除劳动合同的经济补偿"}],
            )
        ],
    }
    draft = await fake_internal.build_draft(case)
    entry = draft["requests"][0]
    # 退回猜测后仍命中正确路径(文本含选项关键词)
    assert entry["path_ids"] == [1, 26, 28]
    assert any("已保存的请求类型" in w for w in draft["warnings"])


# 两级叶子(确认劳动关系争议,无第三层)与其他类($other 模板)——2026-08-12 内网实测结构。
TWO_LEVEL_LEAF = {
    "path": [
        {"id": 1, "code": "1", "name": "劳动争议"},
        {"id": 18, "code": "2", "name": "确认劳动关系争议"},
    ],
    "options": [],
    "template": "请求确认申请人与被申请人于开始日期至结束日期期间存在劳动关系",
    "other_name": None,
}

OTHER_LEAF = {
    "path": [
        {"id": 1, "code": "1", "name": "劳动争议"},
        {"id": 43, "code": "2", "name": "其他劳动争议"},
    ],
    "options": [],
    "template": "请求裁决被申请人向申请人支付$other标的元",
    "other_name": "其他",
}


def test_build_payload_two_level_leaf():
    """两级叶子(确认劳动关系):type 数组两级,期间模板正常填充。"""
    spec = SubmitSpec(
        apply_at=date(2026, 8, 12),
        case_reason="确认劳动关系争议",
        requests=[
            RequestSpec(
                text="确认劳动关系",
                path_ids=[1, 18],
                start_at=date(2020, 1, 1),
                end_at=date(2026, 1, 31),
            )
        ],
    )
    req = build_payload(CASE, spec, CATALOG + [TWO_LEVEL_LEAF])["arb_requests"][0]
    assert [n["id"] for n in req["type"]] == [1, 18]
    assert req["intro"] == "请求确认申请人与被申请人于2020年01月01日至2026年01月31日期间存在劳动关系。"


def test_build_payload_other_template():
    """$other 模板:other 文本进表述与 other 载荷;缺 other 拒绝(防字面$other进内网)。"""
    spec = SubmitSpec(
        apply_at=date(2026, 8, 12),
        case_reason="其他劳动争议",
        requests=[
            RequestSpec(text="其他", path_ids=[1, 43], object=100, other="未缴纳住房公积金损失")
        ],
    )
    req = build_payload(CASE, spec, CATALOG + [OTHER_LEAF])["arb_requests"][0]
    assert req["intro"] == "请求裁决被申请人向申请人支付未缴纳住房公积金损失100元。"
    assert req["other"] == {"name": "其他", "value": "未缴纳住房公积金损失"}

    bad = SubmitSpec(
        apply_at=date(2026, 8, 12),
        case_reason="其他劳动争议",
        requests=[RequestSpec(text="其他", path_ids=[1, 43], object=100)],
    )
    with pytest.raises(ValueError, match="其他类请求"):
        build_payload(CASE, bad, CATALOG + [OTHER_LEAF])
