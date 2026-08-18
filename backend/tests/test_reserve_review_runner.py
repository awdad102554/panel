"""AI 预约审查编排模块的纯函数单测(不触 DB、不打内网、不调模型)。"""

from app.services import reserve_review_runner as runner


def test_latest_review_map_takes_newest_first():
    # rows 按 created_at 倒序传入;同案多条时取第一条(最新)结论。
    rows = [
        ("case-a", "补正"),
        ("case-b", "通过"),
        ("case-a", "审查失败"),
    ]
    assert runner.latest_review_map(rows) == {"case-a": "补正", "case-b": "通过"}


def test_latest_review_map_empty():
    assert runner.latest_review_map([]) == {}


def test_is_valid_conclusion():
    # 有效结论(通过/补正/驳回)→ 已审出结果,不再自动重审。
    assert runner.is_valid_conclusion("通过") is True
    assert runner.is_valid_conclusion("补正") is True
    assert runner.is_valid_conclusion("驳回") is True
    # 审查失败 / 无记录 → 视为未审出结果,自动审核下轮重试。
    assert runner.is_valid_conclusion("审查失败") is False
    assert runner.is_valid_conclusion(None) is False
