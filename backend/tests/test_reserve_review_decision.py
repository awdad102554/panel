"""人工「审核结果」提交载荷的校验与内网请求体组装单测(纯函数,不打内网、不触 DB)。"""

import pytest
from pydantic import ValidationError

from app.schemas.reserve_review import ReserveReviewDecisionCreate
from app.services.reserve_decision_submit import compose_preaudit_payload


def test_agree_clears_reason_and_detail():
    d = ReserveReviewDecisionCreate(decision="同意", reject_reason="其他", reject_detail="残留")
    assert d.decision == "同意"
    assert d.reject_reason is None
    assert d.reject_detail is None


def test_reject_requires_reason():
    with pytest.raises(ValidationError):
        ReserveReviewDecisionCreate(decision="不同意")


def test_reject_reason_must_be_known():
    with pytest.raises(ValidationError):
        ReserveReviewDecisionCreate(decision="不同意", reject_reason="瞎写的理由")


def test_supplement_requires_detail():
    # 「请补正」「其他」命中需补填项,缺补充说明应报错。
    with pytest.raises(ValidationError):
        ReserveReviewDecisionCreate(decision="不同意", reject_reason="请补正")
    with pytest.raises(ValidationError):
        ReserveReviewDecisionCreate(decision="不同意", reject_reason="其他", reject_detail="  ")


def test_plain_reason_needs_no_detail():
    d = ReserveReviewDecisionCreate(
        decision="不同意", reject_reason="您的预申请不属于劳动人事争议仲裁委受案范围"
    )
    assert d.reject_reason == "您的预申请不属于劳动人事争议仲裁委受案范围"
    assert d.reject_detail is None


def test_reject_with_detail_ok():
    d = ReserveReviewDecisionCreate(
        decision="不同意", reject_reason="请补正", reject_detail="请补充劳动合同及工资流水"
    )
    assert d.reject_reason == "请补正"
    assert d.reject_detail == "请补充劳动合同及工资流水"


# ---- 内网 preAudit 请求体组装(compose_preaudit_payload) ----


def test_compose_agree_is_empty_reason_status_1():
    assert compose_preaudit_payload("同意", None, None) == {"reason": "", "status": 1}


def test_compose_reject_other_prepends_detail():
    payload = compose_preaudit_payload("不同意", "其他", "1.缺工资月份；2.缺信用代码")
    assert payload == {"reason": "其他:1.缺工资月份；2.缺信用代码", "status": 2}


def test_compose_reject_supplement_prepends_detail():
    payload = compose_preaudit_payload("不同意", "请补正", "请补充劳动合同及工资流水")
    assert payload == {"reason": "请补正:请补充劳动合同及工资流水", "status": 2}


def test_compose_reject_plain_reason_verbatim():
    reason = "您的预申请不属于劳动人事争议仲裁委受案范围"
    payload = compose_preaudit_payload("不同意", reason, None)
    assert payload == {"reason": reason, "status": 2}


def test_compose_reject_missing_reason_falls_back_to_other():
    assert compose_preaudit_payload("不同意", None, None) == {"reason": "其他", "status": 2}


def test_compose_reject_detail_missing_yields_colon_only():
    # 「其他」/「请补正」明细为空时仍带冒号(与内网样例的「理由:」形态一致)。
    assert compose_preaudit_payload("不同意", "其他", None) == {"reason": "其他:", "status": 2}
