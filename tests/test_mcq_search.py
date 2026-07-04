from iso27001_advisor.core.search_tool import ISO27001Searcher


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


def _report_query() -> str:
    return (
        "下列哪些屬於 ISO 27001:2022 附錄 A 實體控制措施？\n"
        "(A) 實體進入控制措施\n"
        "(B) 遠端工作應提出申請\n"
        "(C) 維護設備以確保其持續之可用性及完整性\n"
        "(D) 未經事前授權不得將設備資訊帶出場域外"
    )


def test_split_mcq_options_parenthesized():
    from iso27001_advisor.core.mcq_search import split_mcq_options

    parsed = split_mcq_options("題幹？ (A) 第一項 (B) 第二項")

    assert parsed["stem"] == "題幹？"
    assert parsed["options"] == {"A": "第一項", "B": "第二項"}


def test_split_mcq_options_dot_format():
    from iso27001_advisor.core.mcq_search import split_mcq_options

    parsed = split_mcq_options("題幹？ A. 第一項 B. 第二項")

    assert parsed["stem"] == "題幹？"
    assert parsed["options"] == {"A": "第一項", "B": "第二項"}


def test_split_mcq_options_fullwidth_parenthesis():
    from iso27001_advisor.core.mcq_search import split_mcq_options

    parsed = split_mcq_options("題幹？ A） 第一項 B） 第二項")

    assert parsed["stem"] == "題幹？"
    assert parsed["options"] == {"A": "第一項", "B": "第二項"}


def test_mcq_union_search_keeps_highest_score_and_reranks():
    from iso27001_advisor.core.mcq_search import mcq_union_search

    class FakeSearcher:
        def __init__(self):
            self.calls = []

        def search(self, query, limit=5):
            self.calls.append((query, limit))
            if query == "題幹？":
                return [_item("control_a") | {"score": 10.0}]
            if query == "第一項":
                return [_item("control_a") | {"score": 40.0}, _item("control_b") | {"score": 20.0}]
            return [_item("control_c") | {"score": 30.0}]

    fake = FakeSearcher()
    results = mcq_union_search(fake, "題幹？ (A) 第一項 (B) 第二項", limit=4, per_option=2)

    assert [(r["item"]["id"], r["score"]) for r in results] == [
        ("control_a", 40.0),
        ("control_c", 30.0),
        ("control_b", 20.0),
    ]
    assert fake.calls == [("題幹？", 4), ("第一項", 2), ("第二項", 2)]


def test_mcq_union_search_reported_question_hits_physical_controls():
    from iso27001_advisor.core.mcq_search import mcq_union_search

    results = mcq_union_search(ISO27001Searcher(), _report_query(), limit=4, per_option=2)
    ids = {result["item"]["id"] for result in results}

    assert "control_7.2" in ids
    assert "control_7.13" in ids
