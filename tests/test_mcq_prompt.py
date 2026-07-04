from iso27001_advisor.llm.llm import build_prompt, get_system_prompt


def _item(item_id: str = "control_7.2") -> dict:
    return {
        "item": {
            "id": item_id,
            "type": "control",
            "section": "Annex A",
            "subsection": "7.2 實體進入",
            "content": "應保護實體進入區域。",
        },
        "score": 99.0,
    }


def test_build_prompt_single_mcq_instruction_unchanged():
    prompt = build_prompt("下列何者正確？ A. 風險 B. 備份", [_item()])

    assert "✅ **建議答案：X**（X 為最正確的選項字母，並用一句話說明理由）" in prompt
    assert "列出**所有**正確選項" not in prompt


def test_build_prompt_multi_mcq_instruction():
    prompt = build_prompt("下列哪些正確？ A. 風險 B. 備份", [_item()])

    assert "✅ **建議答案：X、Y**（列出**所有**正確選項" in prompt
    assert "逐一說明每個正確選項的條文依據" in prompt
    assert "其餘選項不屬於正解的理由" in prompt


def test_build_prompt_no_mcq_instruction_without_options():
    prompt = build_prompt("哪些控制措施屬於實體控制？", [_item()])

    assert "【重要指示】此為選擇題" not in prompt
    assert "建議答案" not in prompt


def test_system_prompt_mcq_rule_covers_single_and_multi():
    system_prompt = get_system_prompt()

    assert "單選題" in system_prompt
    assert "多選題" in system_prompt
    assert "✅ **建議答案：X、Y**" in system_prompt
