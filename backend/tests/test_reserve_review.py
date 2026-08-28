"""AI 预约审查服务单测:纯函数(摘要拼接 / 提示词 / 结果解析),不打内网、不调模型。"""

from app.services import reserve_review as rr

# 仿照真实预约详情接口(GET /v1/api/admin/arb/{id}/reserve)的 data.data 结构。
_DETAIL = {
    "applicant": [
        {
            "name": "宁佳钰",
            "sex": "女",
            "birth": "2007-01-20",
            "id_number": "350481200701203027",
            "mobile": "13799181932",
            "registered_permanent_residence": "福建省永安市安砂镇曹田村土坪尾251号",
            "address": "",
            "receive_address": "福建省永安市燕北街道杨杨食杂店铺",
            "card_image_front": "/storage/uploads/images/2026/08/6a81a680294ec.jpeg",
            "card_image_reverse": "/storage/uploads/images/2026/08/6a81a68c6985e.jpeg",
            "agents": [],
        }
    ],
    "respondent": [
        {
            "name": "永安市红门宴餐饮店（个体工商户）",
            "social_code": "",
            "legal_name": "杨思盈",
            "registered_address": "住所：福建省永安市燕南含笑大道1882号、1888号、1892号、1896号",
            "company_address": "住所：福建省永安市燕南含笑大道1882号、1888号、1892号、1896号",
            "receive_address": "",
            "card_image_front": "/storage/uploads/images/2026/08/6a81a7e1b7238.png",
            "card_image_reverse": "",
            "registered_capital": "0.00",
            "company_nature": "",
            "agents": [],
        }
    ],
    "thirdpartys": [],
    "commonAgent": [],
    "case_arb_request": [
        {
            "type": [
                {"id": "1", "name": "劳动争议"},
                {"id": "3", "name": "劳动报酬争议"},
                {"id": "4", "name": "工资争议（基本工资、奖励性工资、津补贴）"},
            ],
            "is_main_dispute": 1,
            "start_at": "2026-03-22",
            "end_at": "2026-07-01",
            "intro": "请求裁决被申请人向申请人支付2026年3月22日至2026年7月1日拖欠的工资500.00元。",
            "object": "500.00",
        }
    ],
    "case_fact_reason": {
        "content": "申请人于2026年3月22日入职被申请人门店上班，未签订书面劳动合同……",
        "entry_at": "2026-03-22",
        "actual_workplace": "福建省永安市燕南含笑大道 1882 号",
        "job": "服务员",
        "salary": "3300.00",
        "is_sign_labor_contract": 0,
        "is_pay_social_insurance": 0,
        "main_cause": ["被申请人未及时足额支付劳动报酬"],
    },
    "case_evidence_material": [
        {
            "name": "与经营者微信聊天记录",
            "object": "证明本人在永安市红门宴餐饮店务工，店铺拖欠500元工资尾款",
            "type": "书证",
            "material_type": "复印件",
            "pages": 2,
            "submitter": "宁佳钰",
        }
    ],
    "cases": {
        "case_reason": "劳动报酬争议",
        "case_source": "申请人线上申请",
        "apply_at": "2026-08-16",
        "applicant_type": "劳动者",
        "involve_number": 1,
        "is_sign_labor_contract": 1,
        "is_involve_labor_dispatch": 0,
        "position": [
            {"Id": 350, "name": "福建省"},
            {"Id": 350400000000, "name": "三明市"},
            {"Id": 350481000000, "name": "永安市"},
        ],
    },
}


def test_build_case_payload_extracts_core_fields():
    payload = rr.build_case_payload(_DETAIL)
    assert payload["案件基本信息"]["案由"] == "劳动报酬争议"
    assert payload["案件基本信息"]["地区(管辖)"] == "福建省/三明市/永安市"
    # 0/1 布尔字段归一为「是/否」。
    assert payload["案件基本信息"]["是否签订劳动合同"] == "是"
    assert payload["案件基本信息"]["是否涉及劳务派遣"] == "否"
    assert payload["事实与理由"]["是否签订劳动合同"] == "否"
    assert payload["事实与理由"]["是否缴纳社保"] == "否"
    assert payload["仲裁请求"][0]["是否主要争议"] == "是"
    assert payload["申请人"][0]["姓名"] == "宁佳钰"
    assert payload["申请人"][0]["身份证照片(正/反)"] == "已上传/已上传"
    assert payload["被申请人"][0]["名称"] == "永安市红门宴餐饮店（个体工商户）"
    assert payload["被申请人"][0]["法定代表人"] == "杨思盈"
    assert payload["被申请人"][0]["证照照片(正/反)"] == "已上传/未上传"
    assert payload["仲裁请求"][0]["请求类型"] == "劳动争议/劳动报酬争议/工资争议（基本工资、奖励性工资、津补贴）"
    assert payload["仲裁请求"][0]["金额(元)"] == "500.00"
    assert payload["仲裁请求"][0]["起止期间"] == "2026-03-22 至 2026-07-01"
    assert payload["事实与理由"]["内容"].startswith("申请人于2026年3月22日")
    assert payload["事实与理由"]["主要事由"] == ["被申请人未及时足额支付劳动报酬"]
    assert payload["证据材料"][0]["证明对象"].startswith("证明本人在永安市红门宴餐饮店务工")


def test_build_case_payload_tolerates_empty_detail():
    payload = rr.build_case_payload({})
    assert payload["申请人"] == []
    assert payload["仲裁请求"] == []
    assert payload["事实与理由"]["内容"] == ""


def test_build_messages_system_prompt_and_user_json():
    messages = rr.build_messages({"案件基本信息": {"案由": "劳动报酬争议"}})
    assert messages[0]["role"] == "system"
    assert "审查规则" in messages[0]["content"]
    assert "劳动人事争议仲裁委员会" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert '"案由"' in messages[1]["content"] and "劳动报酬争议" in messages[1]["content"]


def test_parse_result_plain_json():
    text = '{"conclusion":"补正","reason":"补充工资流水","issues":["缺流水"],"missing_materials":["工资流水"],"rule_refs":["4"]}'
    r = rr.parse_result(text)
    assert r["conclusion"] == "补正"
    assert r["reason"] == "补充工资流水"
    assert r["issues"] == ["缺流水"]
    assert r["missing_materials"] == ["工资流水"]
    assert r["rule_refs"] == ["4"]


def test_parse_result_strips_markdown_fence():
    text = '```json\n{"conclusion":"驳回","reason":"被申请人不明确","issues":[],"missing_materials":[],"rule_refs":["1"]}\n```'
    r = rr.parse_result(text)
    assert r["conclusion"] == "驳回"
    assert r["reason"] == "被申请人不明确"


def test_parse_result_invalid_json_degrades():
    r = rr.parse_result("这不是 JSON")
    assert r["conclusion"] == "审查失败"
    assert "无法解析" in r["reason"]


def test_parse_result_illegal_conclusion_degrades():
    r = rr.parse_result('{"conclusion":"暂缓","reason":"x","issues":[],"missing_materials":[],"rule_refs":[]}')
    assert r["conclusion"] == "审查失败"
    assert "合法" in r["reason"]


def test_parse_result_missing_fields_defaulted():
    r = rr.parse_result('{"conclusion":"通过"}')
    assert r["conclusion"] == "通过"
    assert r["issues"] == []
    assert r["missing_materials"] == []
    assert r["rule_refs"] == []
    assert r["reason"] != ""


def test_parse_result_checks_normalized():
    text = (
        '{"conclusion":"补正","reason":"x","issues":[],"missing_materials":[],'
        '"rule_refs":["4"],"checks":[{"rule_id":"4","rule_name":"证据材料齐备性",'
        '"passed":false,"note":"缺工资流水"}]}'
    )
    r = rr.parse_result(text)
    # 补齐漏给的 4 个维度,且保留模型给出的第 4 项不通过。
    assert len(r["checks"]) == 5
    by_id = {c["rule_id"]: c for c in r["checks"]}
    assert by_id["4"]["passed"] is False
    assert by_id["4"]["note"] == "缺工资流水"
    assert by_id["1"]["rule_name"] == "被申请人明确性"


def test_parse_result_checks_fallback_from_rule_refs():
    r = rr.parse_result('{"conclusion":"驳回","reason":"x","rule_refs":["1","2"]}')
    assert len(r["checks"]) == 5
    by_id = {c["rule_id"]: c for c in r["checks"]}
    assert by_id["1"]["passed"] is False
    assert by_id["2"]["passed"] is False
    assert by_id["5"]["passed"] is True


def test_parse_result_checks_passed_true_but_problem_note_downgraded():
    # 模型把「有问题」的项标成通过(note 里列了缺陷),应降级为需人工核验(null)。
    text = (
        '{"conclusion":"补正","reason":"x","issues":[],"missing_materials":[],'
        '"rule_refs":[],"checks":[{"rule_id":"1","rule_name":"被申请人明确性",'
        '"passed":true,"note":"统一社会信用代码空缺、送达地址未填写,需人工核验工商登记信息"}]}'
    )
    r = rr.parse_result(text)
    by_id = {c["rule_id"]: c for c in r["checks"]}
    assert by_id["1"]["passed"] is None
    assert "空缺" in by_id["1"]["note"]


def test_parse_result_checks_passed_true_clean_note_kept():
    text = (
        '{"conclusion":"通过","reason":"x","issues":[],"missing_materials":[],'
        '"rule_refs":[],"checks":[{"rule_id":"5","rule_name":"管辖",'
        '"passed":true,"note":"实际工作地及被申请人住所地均在辖区,有管辖权"}]}'
    )
    r = rr.parse_result(text)
    by_id = {c["rule_id"]: c for c in r["checks"]}
    assert by_id["5"]["passed"] is True


def test_note_has_problem_ignores_positive_phrases():
    assert rr._note_has_problem("材料齐全,无需补充") is False
    assert rr._note_has_problem("该项审查通过") is False
    assert rr._note_has_problem("统一社会信用代码空缺,需人工核验") is True


def test_failure_result_has_empty_checks():
    r = rr.failure_result("boom")
    assert r["conclusion"] == "审查失败"
    assert r["checks"] == []
    # 审查失败无审核口径预测。
    assert r["decision"] is None
    assert r["reject_reason"] is None
    assert r["reject_detail"] is None


def test_parse_result_decision_agree():
    r = rr.parse_result('{"conclusion":"通过","reason":"x"}')
    assert r["decision"] == "同意"
    assert r["reject_reason"] is None
    assert r["reject_detail"] is None


def test_parse_result_decision_supplement_from_conclusion():
    # 结论=补正,模型未给 reject_reason → 兜底归类为「请补正」。
    r = rr.parse_result('{"conclusion":"补正","reason":"x","reject_detail":"补充工资流水"}')
    assert r["decision"] == "不同意"
    assert r["reject_reason"] == "请补正"
    assert r["reject_detail"] == "补充工资流水"


def test_parse_result_decision_reject_specific_reason():
    text = '{"conclusion":"驳回","reason":"x","reject_reason":"您的预申请不属于劳动人事争议仲裁委受案范围"}'
    r = rr.parse_result(text)
    assert r["decision"] == "不同意"
    assert r["reject_reason"] == "您的预申请不属于劳动人事争议仲裁委受案范围"
    assert r["reject_detail"] is None


def test_parse_result_decision_reject_reason_fallback_to_other():
    r = rr.parse_result('{"conclusion":"驳回","reason":"x","reject_reason":"瞎写的理由"}')
    assert r["decision"] == "不同意"
    assert r["reject_reason"] == "其他"


def test_parse_result_decision_ignores_contradictory_decision_field():
    # 模型 decision 与 conclusion 矛盾时,以 conclusion 为准派生。
    r = rr.parse_result('{"conclusion":"通过","reason":"x","decision":"不同意"}')
    assert r["decision"] == "同意"
    assert r["reject_reason"] is None
    assert r["reject_detail"] is None


def test_parse_result_offline_submit_forces_other():
    # 补正指引含"当面提交"(线下提交固定收尾)→ 归类「其他」而非「请补正」
    # (2026-08-28 业务口径:可在线补正才用「请补正」)。
    text = (
        '{"conclusion":"补正","reason":"x","reject_reason":"请补正",'
        '"reject_detail":"1.缺2025年12月工资流水；2.缺劳动合同；'
        '材料齐全的情况下，劳动仲裁申请书、申请人身份证复印件等一式三份，'
        '由本人向永安市劳动人事争议仲裁院当面提交"}'
    )
    r = rr.parse_result(text)
    assert r["decision"] == "不同意"
    assert r["reject_reason"] == "其他"
    assert "当面提交" in r["reject_detail"]


def test_parse_result_online_supplement_stays_buzheng():
    # 可在线补正的(无"当面提交"指引)仍为「请补正」。
    r = rr.parse_result(
        '{"conclusion":"补正","reason":"x","reject_reason":"请补正",'
        '"reject_detail":"1.补充2025年12月工资流水并重新上传"}'
    )
    assert r["reject_reason"] == "请补正"


def test_parse_result_fallback_also_flips_on_offline_hint():
    # 模型漏给 reject_reason 兜底「请补正」后,detail 含当面提交指引同样改归「其他」。
    r = rr.parse_result(
        '{"conclusion":"补正","reason":"x",'
        '"reject_detail":"1.缺劳动合同原件；由本人向永安市劳动人事争议仲裁院当面提交"}'
    )
    assert r["reject_reason"] == "其他"


def test_prompt_contains_reason_length_limit():
    # 提示词必须写明内网 reason 255 字上限与明细精简要求(2026-08-28 内网实测校验)。
    assert "255" in rr.RESERVE_REVIEW_SYSTEM_PROMPT
    assert "250 字以内" in rr.RESERVE_REVIEW_SYSTEM_PROMPT


def test_prompt_license_single_side_suffices():
    # 被申请人营业执照只要求"有登记信息的一面",不得把另一面未上传当缺项(2026-08-28 业务口径)。
    assert "只需上传有登记信息的一面" in rr.RESERVE_REVIEW_SYSTEM_PROMPT
    assert "只提供一面证照图片属正常" in rr.VISION_INSTRUCTIONS


def test_prompt_offline_first_and_no_upload_wording():
    # 补正默认优先引导线下当面提交;线下指引的明细不得要求申请人"上传/重新上传"
    # (2026-08-28 业务口径:引导线下后线上补传无意义)。
    assert "默认优先 b 类线下提交" in rr.RESERVE_REVIEW_SYSTEM_PROMPT
    assert "不得要求申请人" in rr.RESERVE_REVIEW_SYSTEM_PROMPT
    assert "上传/重新上传/在线补正" in rr.RESERVE_REVIEW_SYSTEM_PROMPT


def test_collect_material_images_card_photos():
    imgs = rr.collect_material_images(_DETAIL)
    by_label = {i["label"]: i["path"] for i in imgs}
    # 申请人正反、被申请人证照正面(反面为空路径,跳过)。
    assert by_label["申请人身份证正面"] == "/storage/uploads/images/2026/08/6a81a680294ec.jpeg"
    assert by_label["申请人身份证反面"] == "/storage/uploads/images/2026/08/6a81a68c6985e.jpeg"
    assert by_label["被申请人证照正面"] == "/storage/uploads/images/2026/08/6a81a7e1b7238.png"
    assert "被申请人证照反面" not in by_label
    assert len(imgs) == 3


def test_collect_material_images_empty_detail():
    assert rr.collect_material_images({}) == []
