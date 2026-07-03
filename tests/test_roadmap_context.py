import json
import asyncio
from unittest.mock import AsyncMock, MagicMock

import app as app_mod
from agent import build_roadmap_prompt


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


def test_gap_mode_emits_gap_result_event(monkeypatch):
    gap_result = {
        "risk_level": "high",
        "covered_signals": ["每日備份至 NAS"],
        "missing_signals": [{"theme": "還原測試", "detail": "未描述定期還原測試"}],
        "notes": [],
    }

    monkeypatch.setattr(app_mod, "_search_iso", lambda query, top_k=4: _matched_control())
    monkeypatch.setattr(app_mod, "_analyze_coverage", lambda query, matched: gap_result)
    monkeypatch.setattr(app_mod, "_evidence_checklist", lambda clause_ids: [])
    monkeypatch.setattr(app_mod, "_draft_remediation", lambda result, clause_ids: [])
    monkeypatch.setattr(app_mod.rec_engine, "recommend", lambda clause_ids: [])
    monkeypatch.setattr(app_mod, "stream_ollama", lambda *args, **kwargs: iter(["缺口分析完成"]))

    events = _post_chat_events(
        {
            "query": "我們公司每日備份資料庫到本地 NAS，但沒有定期還原測試",
            "mode": "gap",
            "strict_offline": True,
        }
    )

    gap_events = [event for event in events if event.get("type") == "gap_result"]
    assert gap_events
    assert "missing_signals" in gap_events[0]["data"]


def test_roadmap_uses_context_gap_result_when_provided(monkeypatch):
    context_gap_result = {
        "risk_level": "high",
        "covered_signals": ["每日備份至 NAS"],
        "missing_signals": [{"theme": "還原測試", "detail": "未描述定期還原測試"}],
        "notes": [],
    }

    def fail_analyze_coverage(query, matched):
        raise AssertionError("roadmap mode should use context_gap_result")

    monkeypatch.setattr(app_mod, "_search_iso", lambda query, top_k=4: _matched_control())
    monkeypatch.setattr(app_mod, "_analyze_coverage", fail_analyze_coverage)
    monkeypatch.setattr(
        app_mod,
        "_build_roadmap",
        lambda result, clause_ids: {
            "risk_level": result["risk_level"],
            "items": [{"theme": result["missing_signals"][0]["theme"]}],
        },
    )
    monkeypatch.setattr(app_mod, "stream_ollama", lambda *args, **kwargs: iter(["還原測試"]))
    agent_logs = []
    monkeypatch.setattr(
        app_mod,
        "_agent_log",
        lambda request_id, message, **fields: agent_logs.append(message),
    )

    events = _post_chat_events(
        {
            "query": "協助設計改善計畫",
            "mode": "roadmap",
            "strict_offline": True,
            "context_query": "我們公司每日備份資料庫到本地 NAS，但沒有定期還原測試",
            "context_gap_result": context_gap_result,
        }
    )

    chunks = "".join(event.get("data", "") for event in events if event.get("type") == "chunk")
    assert "還原測試" in chunks
    assert "tool.analyze_document_coverage" not in agent_logs


def test_roadmap_fallback_when_no_context(monkeypatch):
    gap_result = {
        "risk_level": "medium",
        "covered_signals": [],
        "missing_signals": [{"theme": "還原測試", "detail": "未描述定期還原測試"}],
        "notes": [],
    }

    monkeypatch.setattr(app_mod, "_search_iso", lambda query, top_k=4: _matched_control())
    monkeypatch.setattr(app_mod, "_analyze_coverage", lambda query, matched: gap_result)
    monkeypatch.setattr(
        app_mod,
        "_build_roadmap",
        lambda result, clause_ids: {
            "risk_level": result["risk_level"],
            "items": [{"theme": result["missing_signals"][0]["theme"]}],
        },
    )
    monkeypatch.setattr(app_mod, "stream_ollama", lambda *args, **kwargs: iter(["fallback ok"]))
    agent_logs = []
    monkeypatch.setattr(
        app_mod,
        "_agent_log",
        lambda request_id, message, **fields: agent_logs.append(message),
    )

    events = _post_chat_events(
        {
            "query": "備份缺還原測試",
            "mode": "roadmap",
            "strict_offline": True,
        }
    )

    assert any(event.get("type") == "done" for event in events)
    assert "tool.analyze_document_coverage" in agent_logs


def test_build_roadmap_prompt_uses_context_query_when_provided():
    prompt = build_roadmap_prompt(
        "協助設計改善計畫",
        {"items": [{"theme": "還原測試"}]},
        context_query="我們公司每日備份資料庫到本地 NAS，但沒有定期還原測試",
    )

    status_section = prompt.split("【改善路線圖（工具產生）】", maxsplit=1)[0]
    assert "我們公司每日備份" in status_section
    assert "協助設計改善計畫" not in status_section


def test_build_roadmap_prompt_fallback_to_document_text():
    prompt = build_roadmap_prompt("備份缺還原測試", {"items": [{"theme": "還原測試"}]})

    status_section = prompt.split("【改善路線圖（工具產生）】", maxsplit=1)[0]
    assert "備份缺還原測試" in status_section
