import os
import json
import urllib.request
import urllib.error
import socket
import webbrowser
import logging
import time
import uuid
from typing import Generator
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

agent_logger = logging.getLogger("iso27001.agent")
if not agent_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [agent] %(message)s"))
    agent_logger.addHandler(handler)
agent_logger.setLevel(logging.INFO)
agent_logger.propagate = False

from iso27001_advisor.core.search_tool import ISO27001Searcher
from iso27001_advisor.core.mcq_search import mcq_union_search
from iso27001_advisor.core.recommendation import RecommendationEngine
from iso27001_advisor.llm import (
    build_prompt,
    call_gemini,
    get_system_prompt,
    load_dotenv,
    map_phase,
)
from iso27001_advisor.llm.llm import _is_mcq

# 載入環境變數
load_dotenv()

app = FastAPI(title="ISO 27001 Advisor Agent Web UI")

# 允許跨網域請求 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化檢索器
searcher = ISO27001Searcher()

# 初始化語意快取（index 不存在時靜默跳過）
sem_cache = None
try:
    from iso27001_advisor.core.semantic_cache import SemanticCache
    sem_cache = SemanticCache()
except Exception:
    pass

# 初始化推薦引擎
rec_engine = RecommendationEngine()

# 初始化 Level 2 tools（不呼叫 LLM）
try:
    from iso27001_advisor.tools.iso_tools import search_iso as _search_iso
    from iso27001_advisor.tools.gap_analysis_tools import analyze_document_coverage as _analyze_coverage
    from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist as _evidence_checklist
    from iso27001_advisor.tools.draft_tools import draft_gap_remediation as _draft_remediation
    from agent import (
        LEVEL2_SYSTEM_PROMPT,
        LEVEL3_SYSTEM_PROMPT,
        build_gap_prompt,
        build_evidence_prompt,
        build_soa_prompt,
        build_audit_report_prompt,
        build_audit_pack_prompt,
        build_roadmap_prompt,
        classify_task as _classify_task,
    )
    _tools_available = True
except ImportError:
    _tools_available = False

# 初始化 Level 3 tools
_l3_tools_available = False
try:
    from iso27001_advisor.tools.soa_tools import build_soa_matrix as _build_soa_matrix
    from iso27001_advisor.tools.audit_report_tools import (
        build_audit_readiness_report as _build_audit_readiness_report,
        build_audit_question_pack as _build_audit_question_pack,
    )
    from iso27001_advisor.tools.action_plan_tools import build_remediation_roadmap as _build_roadmap
    _l3_tools_available = True
except ImportError:
    pass

    def _classify_task(text: str) -> str:
        text_lower = text.lower()
        if any(s in text_lower for s in ["稽核證據", "證據", "查核", "準備什麼", "要準備"]):
            return "evidence"
        if any(s in text_lower for s in ["程序如下", "政策如下", "現況如下", "控制措施如下"]):
            return "gap"
        if (
            any(s in text_lower for s in ["我們公司", "目前", "現況", "如下", "請幫我看"])
            and any(
                s in text_lower
                for s in [
                    "缺什麼",
                    "符合嗎",
                    "符合 iso",
                    "缺口",
                    "不足",
                    "稽核時可能",
                    "被挑戰",
                    "挑戰哪些",
                    "可能被挑戰",
                    "會被挑戰",
                ]
            )
        ):
            return "gap"
        if (
            any(s in text_lower for s in ["我們公司", "目前", "現況", "如下", "請幫我看"])
            and any(s in text_lower for s in ["沒有", "無", "缺乏", "尚未", "未定義", "未建立"])
        ):
            return "gap"
        return "qa"

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>找不到 index.html</h1>"

@app.get("/api/models")
async def get_ollama_models(host: str = "http://localhost:11434"):
    url = f"{host}/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            models = [m.get("name") for m in res_data.get("models", []) if m.get("name")]
            return {"models": models}
    except Exception:
        return {"models": []}

@app.get("/api/gemini-models")
async def get_gemini_models():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"]}
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            models = []
            for m in res_data.get("models", []):
                name = m.get("name", "")
                methods = m.get("supportedGenerationMethods", [])
                if name.startswith("models/") and "generateContent" in methods:
                    model_id = name.replace("models/", "")
                    if "gemini" in model_id:
                        models.append(model_id)
            if models:
                models.sort(key=lambda x: ("2.5" not in x, "1.5" not in x, x))
                return {"models": models}
    except Exception:
        pass
    return {"models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"]}

def stream_ollama(prompt: str, system_prompt: str, model: str, host: str) -> Generator[str, None, None]:
    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        "options": {
            "temperature": 0.2,
            "num_predict": 2048,
            "num_ctx": 16384
        }
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            for line in response:
                if line:
                    chunk = json.loads(line.decode('utf-8'))
                    content_chunk = chunk.get("message", {}).get("content", "")
                    if content_chunk:
                        yield content_chunk
    except Exception as e:
        yield f"\n❌ 連線至 Ollama 失敗: {e}"

def stream_reduce(query: str, map_results: list, model: str, host: str) -> Generator[str, None, None]:
    relevant = [
        f"[{item['id']} {item['subsection']}]\n{points}"
        for item, points in map_results
        if points.strip() and "不相關" not in points.strip()
    ]
    if not relevant:
        yield "根據檢索結果，目前條文庫中沒有找到與此問題直接相關的條文依據。"
        return
    points_text = "\n\n".join(relevant)
    prompt = (
        f"【使用者提問】\n{query}\n\n"
        f"【各條文關鍵要點彙整】\n{points_text}\n\n"
        "請根據以上條文要點，提供專業的顧問解答。"
    )
    yield from stream_ollama(prompt, get_system_prompt(), model, host)


def _ollama_available(host: str) -> bool:
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def _agent_log(request_id: str, message: str, **fields) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    agent_logger.info(f"request_id={request_id} {message}" + (f" {details}" if details else ""))


def _ids_from_flat(items: list) -> str:
    return ",".join(item.get("id", "") for item in items)


def _ids_from_search_results(items: list) -> str:
    return ",".join(item.get("item", {}).get("id", "") for item in items)


def _retrieve_matches(searcher, query, limit):
    """依題型選擇一般檢索或 MCQ 選項分解檢索。"""
    if _is_mcq(query):
        return mcq_union_search(searcher, query, limit=limit)
    return searcher.search(query, limit=limit)


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    request_id = uuid.uuid4().hex[:8]
    start_time = time.monotonic()
    body = await request.json()
    query = body.get("query", "").strip()
    model = body.get("model", "gemma4:e2b-mlx")
    host = body.get("host", "http://localhost:11434")
    use_gemini = body.get("gemini", False)
    gemini_model = body.get("gemini_model", "gemini-2.5-pro")
    top_k = body.get("top_k", 4)
    deep_mode = body.get("deep_mode", False)
    mode = body.get("mode", "auto")   # "auto", "gap", "evidence", "qa"
    strict_offline = bool(body.get("strict_offline", True))
    context_query = body.get("context_query", "").strip()
    context_gap_result = body.get("context_gap_result")
    if not isinstance(context_gap_result, dict):
        context_gap_result = None
    history = body.get("history", [])
    if not isinstance(history, list):
        history = []
    history = history[-10:]

    # 進行安全防禦，確保 top_k >= 1
    if not isinstance(top_k, int) or top_k < 1:
        top_k = 4

    # 自動切換邏輯 (與 main.py 一致)
    api_key = os.environ.get("GEMINI_API_KEY")
    if strict_offline and use_gemini:
        use_gemini = False
    if not strict_offline and not use_gemini and api_key and not _ollama_available(host):
        use_gemini = True
        _agent_log(request_id, "fallback_to_gemini", reason="ollama_unavailable")

    backend = "gemini" if use_gemini else "ollama"
    _agent_log(
        request_id,
        "request_received",
        requested_mode=mode,
        backend=backend,
        model=gemini_model if use_gemini else model,
        top_k=top_k,
        strict_offline=strict_offline,
    )

    # Artifact type label mapping (用於 done event metadata)
    _ARTIFACT_LABELS = {
        "soa":          "SoA 草稿",
        "audit-report": "稽核準備報告",
        "audit-pack":   "稽核問答包",
        "roadmap":      "30/60/90 改善計畫",
        "gap":          "缺口分析",
        "evidence":     "稽核證據",
        "qa":           "條文問答",
    }

    async def event_generator():
        # mutable holder，讓 _done_event 在 effective_mode 確定後取得正確值
        _em = [None]

        def _done_event() -> str:
            """產生帶 metadata 的 done event JSON 字串。"""
            em = _em[0] or mode
            return json.dumps({
                "type": "done",
                "mode": em,
                "artifact_type": _ARTIFACT_LABELS.get(em, ""),
                "backend": backend,
                "model": gemini_model if use_gemini else model,
                "strict_offline": strict_offline,
                "elapsed_seconds": round(time.monotonic() - start_time, 2),
            })

        if not query:
            _agent_log(request_id, "empty_query")
            yield f"data: {json.dumps({'type': 'chunk', 'data': '請輸入您的諮詢問題！'})}\n\n"
            yield f"data: {_done_event()}\n\n"
            return

        if strict_offline and body.get("gemini", False):
            _agent_log(request_id, "strict_offline_rejected_gemini")
            yield f"data: {json.dumps({'type': 'error', 'data': '❌ Strict Offline 模式禁止使用 Gemini。請改用 Ollama 或關閉 Strict Offline。'})}\n\n"
            yield f"data: {_done_event()}\n\n"
            return

        # Level 2 mode 判斷。先判斷模式，避免 gap/evidence 被 FAQ 快取攔截成一般問答。
        effective_mode = mode if mode != "auto" else _classify_task(query)
        _em[0] = effective_mode  # 讓 _done_event() 拿到正確模式
        _agent_log(request_id, "mode_selected", effective_mode=effective_mode)

        # 1. 語意快取查詢（僅 QA + Ollama 模式啟用）
        if effective_mode == "qa" and sem_cache and sem_cache.is_ready and not use_gemini:
            try:
                hit = sem_cache.search(query)
                if hit:
                    _agent_log(
                        request_id,
                        "tool.semantic_cache.hit",
                        faq_id=hit["faq_id"],
                        similarity=hit["similarity"],
                        clause_ids=",".join(hit["clause_ids"]),
                    )
                    yield f"data: {json.dumps({'type': 'cache_hit', 'data': {'faq_id': hit['faq_id'], 'similarity': hit['similarity'], 'clause_ids': hit['clause_ids']}})}\n\n"
                    yield f"data: {json.dumps({'type': 'chunk', 'data': hit['answer']})}\n\n"
                    recs = rec_engine.recommend(hit["clause_ids"])
                    if recs:
                        yield f"data: {json.dumps({'type': 'recommendations', 'data': recs})}\n\n"
                    yield f"data: {_done_event()}\n\n"
                    _agent_log(
                        request_id,
                        "request_completed",
                        path="semantic_cache",
                        elapsed=f"{time.monotonic() - start_time:.2f}s",
                    )
                    return
            except Exception:
                pass  # 快取失敗時靜默降級走 RAG

        # Level 2 gap mode
        if effective_mode == "gap" and _tools_available:
            yield f"data: {json.dumps({'type': 'mode', 'data': 'gap'})}\n\n"

            yield f"data: {json.dumps({'type': 'progress', 'data': '🔍 檢索相關條文...'})}\n\n"
            matched = _search_iso(query, top_k=top_k)
            _agent_log(request_id, "tool.search_iso", hits=len(matched), ids=_ids_from_flat(matched))
            yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"

            yield f"data: {json.dumps({'type': 'progress', 'data': '🔎 分析文件缺口...'})}\n\n"
            gap_result = _analyze_coverage(query, matched)
            gap_themes = ",".join(s.get("theme", "") for s in gap_result.get("missing_signals", []))
            _agent_log(
                request_id,
                "tool.analyze_document_coverage",
                risk_level=gap_result.get("risk_level", ""),
                gaps=gap_themes or "none",
            )
            yield f"data: {json.dumps({'type': 'gap_result', 'data': gap_result})}\n\n"

            yield f"data: {json.dumps({'type': 'progress', 'data': '📋 產生稽核證據清單...'})}\n\n"
            clause_ids = [r["id"] for r in matched]
            evidence_list = _evidence_checklist(clause_ids)
            evidence_count = sum(len(item.get("evidence", [])) for item in evidence_list)
            _agent_log(
                request_id,
                "tool.generate_audit_evidence_checklist",
                controls=",".join(clause_ids),
                evidence_items=evidence_count,
            )

            yield f"data: {json.dumps({'type': 'progress', 'data': '✍️ 準備補強建議...'})}\n\n"
            remediation = _draft_remediation(gap_result, clause_ids)
            _agent_log(request_id, "tool.draft_gap_remediation", bullets=len(remediation))

            recs = rec_engine.recommend(clause_ids)
            _agent_log(request_id, "tool.recommend_next_steps", recommendations=len(recs))

            gap_prompt = build_gap_prompt(
                query,
                matched,
                gap_result,
                evidence_list,
                remediation,
                recs,
                detail_level="deep" if deep_mode else "standard",
                history=history,
            )
            _agent_log(
                request_id,
                "prompt.built",
                mode="gap",
                detail_level="deep" if deep_mode else "standard",
            )

            try:
                if use_gemini:
                    if not api_key:
                        yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
                    else:
                        _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                        ans = call_gemini(
                            gap_prompt, LEVEL2_SYSTEM_PROMPT, api_key, model=gemini_model
                        )
                        yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                else:
                    _agent_log(request_id, "llm.start", backend="ollama", model=model)
                    for chunk in stream_ollama(gap_prompt, LEVEL2_SYSTEM_PROMPT, model, host):
                        yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ Gap 分析失敗: {e}'})}\n\n"

            if recs:
                yield f"data: {json.dumps({'type': 'recommendations', 'data': recs})}\n\n"
            yield f"data: {_done_event()}\n\n"
            _agent_log(
                request_id,
                "request_completed",
                path="gap",
                elapsed=f"{time.monotonic() - start_time:.2f}s",
            )
            return

        # Level 3 soa mode
        elif effective_mode == "soa" and _tools_available and _l3_tools_available:
            yield f"data: {json.dumps({'type': 'mode', 'data': 'soa'})}\n\n"
            _agent_log(request_id, "mode_selected", effective_mode="soa")

            yield f"data: {json.dumps({'type': 'progress', 'data': '🔍 檢索相關條文...'})}\n\n"
            matched = _search_iso(query, top_k=top_k)
            _agent_log(request_id, "tool.search_iso", hits=len(matched), ids=_ids_from_flat(matched))
            yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"

            clause_ids = [r["id"] for r in matched]
            yield f"data: {json.dumps({'type': 'progress', 'data': '📄 產生 SoA 矩陣...'})}\n\n"
            soa_rows = _build_soa_matrix(clause_ids, query)
            _agent_log(request_id, "tool.build_soa_matrix", controls=",".join(clause_ids))

            yield f"data: {json.dumps({'type': 'progress', 'data': '📋 產生稽核證據清單...'})}\n\n"
            evidence_list = _evidence_checklist(clause_ids)

            soa_prompt = build_soa_prompt(
                query,
                soa_rows,
                evidence_list,
                detail_level="deep" if deep_mode else "standard",
                history=history,
            )
            _agent_log(request_id, "prompt.built", mode="soa", detail_level="deep" if deep_mode else "standard")

            try:
                if use_gemini:
                    if not api_key:
                        yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
                    else:
                        _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                        ans = call_gemini(soa_prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
                        yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                else:
                    _agent_log(request_id, "llm.start", backend="ollama", model=model)
                    for chunk in stream_ollama(soa_prompt, LEVEL3_SYSTEM_PROMPT, model, host):
                        yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ SoA 草稿產生失敗: {e}'})}\n\n"

            yield f"data: {_done_event()}\n\n"
            _agent_log(request_id, "request_completed", path="soa", elapsed=f"{time.monotonic() - start_time:.2f}s")
            return

        # Level 3 audit-report mode
        elif effective_mode == "audit-report" and _tools_available and _l3_tools_available:
            yield f"data: {json.dumps({'type': 'mode', 'data': 'audit-report'})}\n\n"
            _agent_log(request_id, "mode_selected", effective_mode="audit-report")

            yield f"data: {json.dumps({'type': 'progress', 'data': '🔍 檢索相關條文...'})}\n\n"
            matched = _search_iso(query, top_k=top_k)
            _agent_log(request_id, "tool.search_iso", hits=len(matched), ids=_ids_from_flat(matched))
            yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"

            clause_ids = [r["id"] for r in matched]
            gap_result = _analyze_coverage(query, matched)
            evidence_list = _evidence_checklist(clause_ids)
            remediation = _draft_remediation(gap_result, clause_ids)

            yield f"data: {json.dumps({'type': 'progress', 'data': '🗺️ 產生改善路線圖...'})}\n\n"
            roadmap = _build_roadmap(gap_result, clause_ids)
            _agent_log(request_id, "tool.build_remediation_roadmap", risk_level=gap_result.get("risk_level", ""))

            yield f"data: {json.dumps({'type': 'progress', 'data': '📊 產生稽核準備報告...'})}\n\n"
            readiness = _build_audit_readiness_report(query, matched, gap_result, evidence_list, remediation)
            _agent_log(
                request_id,
                "tool.build_audit_readiness_report",
                controls=",".join(clause_ids),
                gaps=str(readiness["summary"]["gap_count"]),
            )

            ar_prompt = build_audit_report_prompt(
                query,
                readiness,
                roadmap,
                detail_level="deep" if deep_mode else "standard",
                history=history,
            )
            _agent_log(request_id, "prompt.built", mode="audit-report", detail_level="deep" if deep_mode else "standard")

            try:
                if use_gemini:
                    if not api_key:
                        yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
                    else:
                        _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                        ans = call_gemini(ar_prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
                        yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                else:
                    _agent_log(request_id, "llm.start", backend="ollama", model=model)
                    for chunk in stream_ollama(ar_prompt, LEVEL3_SYSTEM_PROMPT, model, host):
                        yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ 稽核準備報告產生失敗: {e}'})}\n\n"

            recs = rec_engine.recommend(clause_ids)
            if recs:
                yield f"data: {json.dumps({'type': 'recommendations', 'data': recs})}\n\n"
            yield f"data: {_done_event()}\n\n"
            _agent_log(request_id, "request_completed", path="audit-report", elapsed=f"{time.monotonic() - start_time:.2f}s")
            return

        # Level 3 audit-pack mode
        elif effective_mode == "audit-pack" and _l3_tools_available:
            yield f"data: {json.dumps({'type': 'mode', 'data': 'audit-pack'})}\n\n"
            _agent_log(request_id, "mode_selected", effective_mode="audit-pack")

            if _tools_available:
                matched = _search_iso(query, top_k=top_k)
                clause_ids = [r["id"] for r in matched]
                yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"
            else:
                clause_ids = []

            yield f"data: {json.dumps({'type': 'progress', 'data': '🎯 產生稽核問答包...'})}\n\n"
            packs = _build_audit_question_pack(clause_ids)
            _agent_log(request_id, "tool.build_audit_question_pack", controls=",".join(clause_ids))

            pack_prompt = build_audit_pack_prompt(
                query,
                packs,
                detail_level="deep" if deep_mode else "standard",
                history=history,
            )
            _agent_log(request_id, "prompt.built", mode="audit-pack", detail_level="deep" if deep_mode else "standard")

            try:
                if use_gemini:
                    if not api_key:
                        yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
                    else:
                        _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                        ans = call_gemini(pack_prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
                        yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                else:
                    _agent_log(request_id, "llm.start", backend="ollama", model=model)
                    for chunk in stream_ollama(pack_prompt, LEVEL3_SYSTEM_PROMPT, model, host):
                        yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ 稽核問答包產生失敗: {e}'})}\n\n"

            yield f"data: {_done_event()}\n\n"
            _agent_log(request_id, "request_completed", path="audit-pack", elapsed=f"{time.monotonic() - start_time:.2f}s")
            return

        # Level 3 roadmap mode
        elif effective_mode == "roadmap" and _tools_available and _l3_tools_available:
            yield f"data: {json.dumps({'type': 'mode', 'data': 'roadmap'})}\n\n"
            _agent_log(request_id, "mode_selected", effective_mode="roadmap")

            yield f"data: {json.dumps({'type': 'progress', 'data': '🔍 檢索相關條文...'})}\n\n"
            matched = _search_iso(query, top_k=top_k)
            _agent_log(request_id, "tool.search_iso", hits=len(matched), ids=_ids_from_flat(matched))
            yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"

            clause_ids = [r["id"] for r in matched]
            if context_gap_result:
                gap_result = context_gap_result
            else:
                gap_result = _analyze_coverage(query, matched)
                gap_themes = ",".join(s.get("theme", "") for s in gap_result.get("missing_signals", []))
                _agent_log(
                    request_id,
                    "tool.analyze_document_coverage",
                    risk_level=gap_result.get("risk_level", ""),
                    gaps=gap_themes or "none",
                )

            yield f"data: {json.dumps({'type': 'progress', 'data': '🗺️ 產生改善路線圖...'})}\n\n"
            roadmap = _build_roadmap(gap_result, clause_ids)
            _agent_log(request_id, "tool.build_remediation_roadmap", risk_level=gap_result.get("risk_level", ""))

            rm_prompt = build_roadmap_prompt(
                query,
                roadmap,
                detail_level="deep" if deep_mode else "standard",
                context_query=context_query,
                history=history,
            )
            _agent_log(request_id, "prompt.built", mode="roadmap", detail_level="deep" if deep_mode else "standard")

            try:
                if use_gemini:
                    if not api_key:
                        yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
                    else:
                        _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                        ans = call_gemini(rm_prompt, LEVEL3_SYSTEM_PROMPT, api_key, model=gemini_model)
                        yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                else:
                    _agent_log(request_id, "llm.start", backend="ollama", model=model)
                    for chunk in stream_ollama(rm_prompt, LEVEL3_SYSTEM_PROMPT, model, host):
                        yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ 改善計畫產生失敗: {e}'})}\n\n"

            yield f"data: {_done_event()}\n\n"
            _agent_log(request_id, "request_completed", path="roadmap", elapsed=f"{time.monotonic() - start_time:.2f}s")
            return

        # Level 2 evidence mode
        elif effective_mode == "evidence" and _tools_available:
            yield f"data: {json.dumps({'type': 'mode', 'data': 'evidence'})}\n\n"

            yield f"data: {json.dumps({'type': 'progress', 'data': '🔍 檢索相關條文...'})}\n\n"
            matched = _search_iso(query, top_k=top_k)
            _agent_log(request_id, "tool.search_iso", hits=len(matched), ids=_ids_from_flat(matched))
            yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"

            yield f"data: {json.dumps({'type': 'progress', 'data': '📋 產生稽核證據清單...'})}\n\n"
            clause_ids = [r["id"] for r in matched]
            evidence_list = _evidence_checklist(clause_ids)
            evidence_count = sum(len(item.get("evidence", [])) for item in evidence_list)
            _agent_log(
                request_id,
                "tool.generate_audit_evidence_checklist",
                controls=",".join(clause_ids),
                evidence_items=evidence_count,
            )
            recs = rec_engine.recommend(clause_ids)
            _agent_log(request_id, "tool.recommend_next_steps", recommendations=len(recs))

            evidence_prompt = build_evidence_prompt(query, matched, evidence_list, history=history)

            try:
                if use_gemini:
                    if not api_key:
                        yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
                    else:
                        _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                        ans = call_gemini(
                            evidence_prompt, LEVEL2_SYSTEM_PROMPT, api_key, model=gemini_model
                        )
                        yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                else:
                    _agent_log(request_id, "llm.start", backend="ollama", model=model)
                    for chunk in stream_ollama(evidence_prompt, LEVEL2_SYSTEM_PROMPT, model, host):
                        yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ 稽核證據查詢失敗: {e}'})}\n\n"

            if recs:
                yield f"data: {json.dumps({'type': 'recommendations', 'data': recs})}\n\n"
            yield f"data: {_done_event()}\n\n"
            _agent_log(
                request_id,
                "request_completed",
                path="evidence",
                elapsed=f"{time.monotonic() - start_time:.2f}s",
            )
            return

        # 2. 檢索條文
        matched = _retrieve_matches(searcher, query, top_k)
        _agent_log(request_id, "tool.searcher.search", hits=len(matched), ids=_ids_from_search_results(matched))

        # 發送參考條文給前端
        yield f"data: {json.dumps({'type': 'references', 'data': matched})}\n\n"
        
        if not matched:
            yield f"data: {json.dumps({'type': 'chunk', 'data': '⚠️ 找不到與該關鍵字相關的條文。'})}\n\n"
            yield f"data: {_done_event()}\n\n"
            _agent_log(
                request_id,
                "request_completed",
                path="qa_no_match",
                elapsed=f"{time.monotonic() - start_time:.2f}s",
            )
            return
            
        # 3. 呼叫推理後端並串流輸出
        if use_gemini:
            if not api_key:
                yield f"data: {json.dumps({'type': 'error', 'data': '❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。'})}\n\n"
            else:
                try:
                    prompt = build_prompt(query, matched, history=history)
                    _agent_log(request_id, "llm.start", backend="gemini", model=gemini_model)
                    ans = call_gemini(prompt, get_system_prompt(), api_key, model=gemini_model)
                    yield f"data: {json.dumps({'type': 'chunk', 'data': ans})}\n\n"
                except Exception as e:
                    _agent_log(request_id, "llm.error", error=str(e))
                    yield f"data: {json.dumps({'type': 'error', 'data': f'❌ Gemini 推理失敗: {e}'})}\n\n"
        elif deep_mode:
            try:
                # Map 階段：逐條提取要點，串流進度事件
                map_results = []
                for i, r in enumerate(matched):
                    item = r["item"]
                    progress_msg = f"Map [{i + 1}/{len(matched)}] 分析 {item['id']}..."
                    yield f"data: {json.dumps({'type': 'progress', 'data': progress_msg})}\n\n"
                    _agent_log(request_id, "tool.map_phase", item_id=item["id"], step=f"{i + 1}/{len(matched)}")
                    points = map_phase(query, item, model, host)
                    map_results.append((item, points))

                yield f"data: {json.dumps({'type': 'progress', 'data': 'Reduce 彙整中...'})}\n\n"

                # Reduce 階段：串流輸出最終解答
                _agent_log(request_id, "llm.start", backend="ollama", model=model, mode="deep_reduce")
                for chunk in stream_reduce(query, map_results, model, host):
                    yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ 深度分析失敗: {e}'})}\n\n"
        else:
            try:
                prompt = build_prompt(query, matched, history=history)
                _agent_log(request_id, "llm.start", backend="ollama", model=model)
                for chunk in stream_ollama(prompt, get_system_prompt(), model, host):
                    yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            except Exception as e:
                _agent_log(request_id, "llm.error", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'data': f'❌ Ollama 推理失敗: {e}'})}\n\n"
                
        # 推薦下一步問題（從已命中條文 ID 查圖譜）
        hit_ids = [r["item"]["id"] for r in matched] if matched else []
        recs = rec_engine.recommend(hit_ids)
        _agent_log(request_id, "tool.recommend_next_steps", recommendations=len(recs))
        if recs:
            yield f"data: {json.dumps({'type': 'recommendations', 'data': recs})}\n\n"

        yield f"data: {_done_event()}\n\n"
        _agent_log(
            request_id,
            "request_completed",
            path="qa",
            elapsed=f"{time.monotonic() - start_time:.2f}s",
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    # 自動在瀏覽器開啟 Web 視窗
    webbrowser.open("http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
