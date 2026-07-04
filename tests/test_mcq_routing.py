import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import app as app_mod
import main as main_mod


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


def test_main_route_uses_mcq_union_search_for_mcq(monkeypatch):
    calls = []

    class FakeSearcher:
        def search(self, query, limit=4):
            calls.append(("search", query, limit))
            return [_item("control_search")]

    monkeypatch.setattr(
        main_mod,
        "mcq_union_search",
        lambda searcher, query, limit=4: calls.append(("mcq", query, limit)) or [_item("control_mcq")],
    )

    assert main_mod._retrieve_matches(FakeSearcher(), "哪些？ A. 一 B. 二", 4)[0]["item"]["id"] == "control_mcq"
    assert main_mod._retrieve_matches(FakeSearcher(), "請說明備份", 4)[0]["item"]["id"] == "control_search"
    assert calls == [("mcq", "哪些？ A. 一 B. 二", 4), ("search", "請說明備份", 4)]


def test_app_route_uses_mcq_union_search_for_qa_mcq(monkeypatch):
    calls = []

    class FakeSearcher:
        def search(self, query, limit=4):
            calls.append(("search", query, limit))
            return [_item("control_search")]

    monkeypatch.setattr(app_mod, "searcher", FakeSearcher())
    monkeypatch.setattr(app_mod, "sem_cache", None)
    monkeypatch.setattr(app_mod.rec_engine, "recommend", lambda clause_ids: [])
    monkeypatch.setattr(
        app_mod,
        "mcq_union_search",
        lambda searcher, query, limit=4: calls.append(("mcq", query, limit)) or [_item("control_mcq")],
    )
    monkeypatch.setattr(app_mod, "stream_ollama", lambda *args, **kwargs: iter(["完成"]))

    events = _post_chat_events(
        {
            "query": "下列哪些正確？ A. 一 B. 二",
            "mode": "qa",
            "strict_offline": True,
            "top_k": 4,
        }
    )

    references = [event for event in events if event.get("type") == "references"]
    assert references[0]["data"][0]["item"]["id"] == "control_mcq"
    assert calls == [("mcq", "下列哪些正確？ A. 一 B. 二", 4)]
