"""仲裁申请书生成(services/application_doc.py)的单元测试。

重点:合计金额优先取结构化请求(request_specs)的 object/items,
不依赖文本正则;无结构化数据的行退回文本提取(旧数据兼容)。
"""

from app.services.application_doc import build_total_amount

SPEC_A = {"path_ids": [1, 26, 28], "object": 53015.63}
SPEC_B = {"path_ids": [1, 26, 28], "object": 3656.25}


def test_total_amount_from_specs():
    """结构化金额:直接取 object,文本里金额写错/不写都不影响合计。"""
    applicants = [
        {
            "requests": ["请求支付经济补偿(金额待核)", "请求支付代通知金若干"],
            "request_specs": [SPEC_A, SPEC_B],
        }
    ]
    assert build_total_amount(applicants) == "以上共计56671.88元。"


def test_total_amount_from_spec_items():
    """多选项请求(items)按明细求和,object 为空也行。"""
    applicants = [
        {
            "requests": ["请求支付工伤保险待遇", "请求支付拖欠工资5000元。"],
            "request_specs": [
                {
                    "path_ids": [1, 11, 12],
                    "items": [{"name": "医疗费", "object": 100}, {"name": "护理费", "object": 50}],
                },
                None,  # 第二行自由文本,退回正则提取
            ],
        }
    ]
    assert build_total_amount(applicants) == "以上共计5150.00元。"


def test_total_amount_text_fallback_without_specs():
    """旧数据没有 request_specs:保持原文本正则行为。"""
    applicants = [{"requests": ["请求支付工资5000元。", "请求支付赔偿金2,000.50元。"]}]
    assert build_total_amount(applicants) == "以上共计7000.50元。"


def test_total_amount_single_request_empty():
    applicants = [{"requests": ["请求确认劳动关系。"]}]
    assert build_total_amount(applicants) == ""


def test_total_amount_partial_items_not_summed():
    """items 只有部分金额:不求部分和,退回 object/文本(部分和偏低会误导正式文书)。"""
    applicants = [
        {
            "requests": ["请求支付工伤保险待遇共计5000元。", "请求支付工资1000元。"],
            "request_specs": [
                {
                    "path_ids": [1, 11, 12],
                    "items": [{"name": "医疗费", "object": 100}, {"name": "护理费", "object": None}],
                },
                None,
            ],
        }
    ]
    # 第一行退回文本正则取 5000,第二行取 1000
    assert build_total_amount(applicants) == "以上共计6000.00元。"


def test_total_amount_object_wins_over_items():
    """object 与 items 同时在库:object 优先(与提交链 build_payload 口径一致)。"""
    applicants = [
        {
            "requests": ["请求A", "请求B"],
            "request_specs": [
                {"path_ids": [1], "object": 300, "items": [{"name": "x", "object": 100}]},
                {"path_ids": [1], "object": 200},
            ],
        }
    ]
    assert build_total_amount(applicants) == "以上共计500.00元。"


def test_claims_fallback_for_legacy_data():
    """旧数据只有 claims 没有 requests:请求段与合计都要能出(此前整段空白)。"""
    from app.services.application_doc import build_requests_text

    applicants = [{"claims": "请求支付拖欠工资2万元。", "requests": []}, {"requests": ["请求支付赔偿金1000元。"]}]
    assert "请求支付拖欠工资2万元" in build_requests_text(applicants)
    # 正则支持"万元":20000 + 1000
    assert build_total_amount(applicants) == "以上共计21000.00元。"


def test_requests_text_multi_applicant_marked():
    """多申请人:申请书请求段按归属加"申请人N";单申请人保持原样。"""
    from app.services.application_doc import build_requests_text

    multi = [
        {"name": "张三", "requests": ["请求裁决被申请人向申请人支付工资5000元。"]},
        {"name": "李四", "requests": ["请求裁决被申请人向申请人支付工资4000元。"]},
    ]
    text = build_requests_text(multi)
    assert "1.请求裁决被申请人向申请人1支付工资5000元。" in text
    assert "2.请求裁决被申请人向申请人2支付工资4000元。" in text

    single = [{"name": "张三", "requests": ["请求裁决被申请人向申请人支付工资5000元。"]}]
    assert "申请人1" not in build_requests_text(single)
