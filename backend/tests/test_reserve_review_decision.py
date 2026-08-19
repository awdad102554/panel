"""人工「审核结果」提交载荷的校验单测(纯函数,不打内网、不触 DB)。"""

import pytest
from pydantic import ValidationError

from app.schemas.reserve_review import ReserveReviewDecisionCreate


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
