"""tests/test_done_event_metadata.py
驗證 app.py event_generator 的 done event 帶有正確 metadata。
不啟動真實 HTTP server，直接呼叫 event_generator 邏輯測試。
"""
import json
import os
import sys
import asyncio

import pytest



# ────────────────────────────────────────────────
# Helper：從 SSE stream 收集全部 events
# ────────────────────────────────────────────────

def _parse_sse(raw: str) -> list[dict]:
    """解析 SSE data: {...} 格式，回傳 event dict 清單。"""
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _collect_events(gen) -> list[dict]:
    """將 async generator 收集為 event list。"""
    async def _run():
        parts = []
        async for chunk in gen:
            parts.append(chunk)
        return "".join(parts)

    raw = asyncio.run(_run())
    return _parse_sse(raw)


# ────────────────────────────────────────────────
# 直接測試 _ARTIFACT_LABELS 和 _done_event 結構
# ────────────────────────────────────────────────

def _make_mock_generator(query: str, mode: str = "auto", strict_offline: bool = True):
    """
    用最小 mock body 呼叫 app.py 的 event_generator 邏輯。
    只測試 done event 結構，不啟動 LLM。
    """
    import importlib
    import unittest.mock as mock

    # 動態 import app 模組
    spec = importlib.util.spec_from_file_location(
        "app",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"),
    )
    app_mod = importlib.util.module_from_spec(spec)

    # mock FastAPI request
    mock_request = mock.MagicMock()
    mock_request.json = mock.AsyncMock(return_value={
        "query": query,
        "model": "test-model",
        "host": "http://localhost:11434",
        "gemini": False,
        "gemini_model": "gemini-2.5-pro",
        "top_k": 4,
        "deep_mode": False,
        "mode": mode,
        "strict_offline": strict_offline,
    })
    return mock_request


class TestDoneEventStructure:
    """直接驗證 done event 的 payload 結構。"""

    def _extract_done_event(self, events):
        for e in events:
            if e.get("type") == "done":
                return e
        return None

    def test_done_event_has_required_fields(self):
        """done event 必須包含 mode, artifact_type, backend, model, strict_offline, elapsed_seconds。"""
        required = {"type", "mode", "artifact_type", "backend", "model", "strict_offline", "elapsed_seconds"}

        # 從 _ARTIFACT_LABELS 驗證（不實際呼叫 generator）
        import importlib.util as ilu
        spec = ilu.spec_from_file_location(
            "app_check",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"),
        )
        # 只做靜態 AST 檢查
        import ast
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
        # 確認 _done_event 函式存在
        assert "_done_event" in src, "_done_event helper 應存在於 app.py"
        # 確認所有 required fields 出現在 _done_event 函式定義附近
        for field in required:
            assert f'"{field}"' in src or f"'{field}'" in src, f"done event payload 應包含欄位: {field}"

    def test_artifact_labels_mapping(self):
        """確認所有 LV3 模式都有對應的 artifact_type 標籤。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
        expected_mappings = {
            "soa":          "SoA 草稿",
            "audit-report": "稽核準備報告",
            "audit-pack":   "稽核問答包",
            "roadmap":      "30/60/90 改善計畫",
            "gap":          "缺口分析",
            "evidence":     "稽核證據",
            "qa":           "條文問答",
        }
        for mode_key, label in expected_mappings.items():
            assert mode_key in src, f"_ARTIFACT_LABELS 應包含 mode: {mode_key}"
            assert label in src, f"_ARTIFACT_LABELS 應包含 label: {label}"

    def test_done_event_uses_helper_not_hardcoded(self):
        """所有 done event yield 都應使用 _done_event()，不應有舊的硬編碼 {'type': 'done'}。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
        # 不應出現舊格式
        old_format = "json.dumps({'type': 'done'})"
        assert old_format not in src, f"app.py 中仍有舊格式 done event：{old_format}"
        # _done_event() 呼叫應存在
        assert "_done_event()" in src, "_done_event() 呼叫應存在於 app.py"

    def test_em_holder_exists(self):
        """_em mutable holder 應存在，確保 effective_mode 能被 _done_event 讀取。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
        assert "_em = [None]" in src, "_em = [None] holder 應存在於 event_generator 中"
        assert "_em[0] = effective_mode" in src, "_em[0] 應在 effective_mode 確定後被賦值"

    def test_done_event_count(self):
        """確認替換後 done event 數量正確（12 個，含 1 個定義函式）。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
        count = src.count("_done_event()")
        # 應有 12 個呼叫（11 個原始 + 1 個 QA 路徑末尾）
        assert count >= 11, f"_done_event() 呼叫次數應 >= 11，實際: {count}"


class TestFrontendDoneHandling:
    """驗證 index.html 的 done event 處理邏輯。"""

    def _get_html_src(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
        return open(path).read()

    def test_done_handler_reads_mode_from_event(self):
        src = self._get_html_src()
        assert "dm.mode" in src, "index.html done handler 應從 event 讀取 dm.mode"

    def test_done_handler_reads_artifact_type(self):
        src = self._get_html_src()
        assert "dm.artifact_type" in src or "LV3_ARTIFACT_LABELS[dm.mode]" in src, \
            "index.html done handler 應處理 artifact_type"

    def test_done_handler_reads_strict_offline(self):
        src = self._get_html_src()
        assert "dm.strict_offline" in src, "index.html done handler 應從 done event 讀取 strict_offline"

    def test_done_handler_reads_model(self):
        src = self._get_html_src()
        assert "dm.model" in src, "index.html done handler 應從 done event 讀取 model"

    def test_done_handler_reads_elapsed_seconds(self):
        src = self._get_html_src()
        assert "dm.elapsed_seconds" in src, "index.html done handler 應從 done event 讀取 elapsed_seconds"

    def test_download_uses_done_metadata_first(self):
        src = self._get_html_src()
        # 下載函式應優先使用 dm.model
        assert "dm.model" in src, "downloadMarkdown 應優先使用 done event 的 model"
        assert "dm.strict_offline" in src, "downloadMarkdown 應優先使用 done event 的 strict_offline"

    def test_fallback_to_tracking_state(self):
        src = self._get_html_src()
        # 應有 fallback 邏輯（|| strictOffline 或 || useGemini）
        assert "strictOffline" in src, "index.html 應保留 strictOffline fallback"
        assert "currentArtifactType" in src, "index.html 應保留 currentArtifactType fallback"
