from iso27001_advisor.llm.llm import _is_mcq, _mcq_mode


def test_mcq_mode_single_cases():
    assert _mcq_mode("下列何者正確？ A. 風險 B. 備份") == "single"
    assert _mcq_mode("請選出正確項目 A） 政策 B） 稽核") == "single"


def test_mcq_mode_multi_cases():
    assert _mcq_mode("下列哪些正確？ A. 風險 B. 備份") == "multi"
    assert _mcq_mode("本題為複選，所有正確選項為何？ (A) 政策 (B) 稽核") == "multi"


def test_mcq_mode_none_cases():
    assert _mcq_mode("哪些控制措施屬於實體控制？") is None
    assert _mcq_mode("請說明資訊備份控制措施") is None


def test_is_mcq_external_behavior_unchanged():
    assert _is_mcq("下列何者正確？ A. 風險 B. 備份") is True
    assert _is_mcq("哪些控制措施屬於實體控制？") is False
