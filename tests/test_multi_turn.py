import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import app as app_mod
from agent import _build_history_block, build_gap_prompt, build_roadmap_prompt


def _parse_sse(raw: str) -> list[dict]:
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _post_chat_events(payload: dict) -> list[dict]:
    async def _run() -> str:
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)
        response = await app_mod.chat_endpoint(request)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    return _parse_sse(asyncio.run(_run()))


def _matched_control() -> list[dict]:
    return [
        {
            "id": "control_8.13",
            "type": "control",
            "section": "Annex A",
            "subsection": "8.13 資訊備份",
            "content": "資訊、軟體與系統的備份應依約定備份政策定期維護並測試。",
        }
    ]


def test_build_history_block_empty():
    assert _build_history_block([]) == ""


def test_build_history_block_formats_correctly():
    history = [
        {"role": "user", "content": "備份問題", "mode": "gap"},
        {"role": "assistant", "content": "缺少還原測試", "mode": "gap"},
    ]

    result = _build_history_block(history)

    assert "使用者：備份問題" in result
    assert "顧問：缺少還原測試" in result
    assert "【對話歷史" in result


def test_build_history_block_truncates_to_max_turns():
    history = [
        {"role": "user", "content": f"第{i}輪問題", "mode": "gap"}
        for i in range(1, 9)
    ]

    result = _build_history_block(history, max_turns=3)

    assert "第8輪問題" in result
    assert "第1輪問題" not in result


def test_build_history_block_truncates_long_assistant():
    long_content = "A" * 800
    history = [{"role": "assistant", "content": long_content, "mode": "gap"}]

    result = _build_history_block(history)

    assert "…（略）" in result
    assert "A" * 601 not in result


def test_build_gap_prompt_includes_history():
    history = [
        {"role": "user", "content": "上一個問題", "mode": "qa"},
        {"role": "assistant", "content": "上一個答案", "mode": "qa"},
    ]

    prompt = build_gap_prompt("新問題", [], {}, [], [], [], history=history)

    assert "對話歷史" in prompt
    assert "上一個問題" in prompt


def test_build_gap_prompt_no_history_section_when_empty():
    prompt = build_gap_prompt("新問題", [], {}, [], [], [])

    assert "對話歷史" not in prompt


def test_roadmap_mode_receives_history(monkeypatch):
    captured = {}
    context_gap_result = {
        "risk_level": "high",
        "covered_signals": ["每日備份至 NAS"],
        "missing_signals": [{"theme": "還原測試", "detail": "未描述定期還原測試"}],
        "notes": [],
    }

    def mock_build(*args, **kwargs):
        captured["history"] = kwargs.get("history")
        return build_roadmap_prompt(*args, **kwargs)

    monkeypatch.setattr(app_mod, "_search_iso", lambda query, top_k=4: _matched_control())
    monkeypatch.setattr(
        app_mod,
        "_build_roadmap",
        lambda result, clause_ids: {
            "risk_level": result["risk_level"],
            "items": [{"theme": result["missing_signals"][0]["theme"]}],
        },
    )
    monkeypatch.setattr(app_mod, "build_roadmap_prompt", mock_build)
    monkeypatch.setattr(app_mod, "stream_ollama", lambda *args, **kwargs: iter(["還原測試"]))

    events = _post_chat_events(
        {
            "query": "協助設計改善計畫",
            "mode": "roadmap",
            "strict_offline": True,
            "context_gap_result": context_gap_result,
            "history": [
                {"role": "user", "content": "備份缺還原測試", "mode": "gap"},
                {"role": "assistant", "content": "缺少還原測試", "mode": "gap"},
            ],
        }
    )

    assert any(event.get("type") == "done" for event in events)
    assert captured["history"] is not None
    assert len(captured["history"]) > 0


def test_invalid_history_defaults_to_empty(monkeypatch):
    captured = {}
    context_gap_result = {
        "risk_level": "high",
        "covered_signals": ["每日備份至 NAS"],
        "missing_signals": [{"theme": "還原測試", "detail": "未描述定期還原測試"}],
        "notes": [],
    }

    def mock_build(*args, **kwargs):
        captured["history"] = kwargs.get("history")
        return build_roadmap_prompt(*args, **kwargs)

    monkeypatch.setattr(app_mod, "_search_iso", lambda query, top_k=4: _matched_control())
    monkeypatch.setattr(
        app_mod,
        "_build_roadmap",
        lambda result, clause_ids: {
            "risk_level": result["risk_level"],
            "items": [{"theme": result["missing_signals"][0]["theme"]}],
        },
    )
    monkeypatch.setattr(app_mod, "build_roadmap_prompt", mock_build)
    monkeypatch.setattr(app_mod, "stream_ollama", lambda *args, **kwargs: iter(["fallback ok"]))

    events = _post_chat_events(
        {
            "query": "協助設計改善計畫",
            "mode": "roadmap",
            "strict_offline": True,
            "context_gap_result": context_gap_result,
            "history": "invalid",
        }
    )

    assert any(event.get("type") == "done" for event in events)
    assert captured["history"] == []
