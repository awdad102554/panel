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
    with pytest.raises(ValueError, match="不存在"):
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


def test_validate_case():
    errors, warnings = validate_case(CASE)
    assert errors == []
    bad = {**CASE, "applicants": [{"name": "张三", "requests": ["要钱"]}]}
    errors, _ = validate_case(bad)
    assert any("身份证" in e for e in errors)
