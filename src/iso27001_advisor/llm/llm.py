"""Reusable LLM helpers for ISO 27001 Advisor."""

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path


def call_ollama(prompt, system_prompt, model="gemma3:12b-16k", host="http://localhost:11434", on_chunk=None):
    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": True if on_chunk else False,
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
            if on_chunk:
                full_response = []
                for line in response:
                    if line:
                        chunk = json.loads(line.decode('utf-8'))
                        content_chunk = chunk.get("message", {}).get("content", "")
                        if content_chunk:
                            on_chunk(content_chunk)
                            full_response.append(content_chunk)
                return "".join(full_response)
            else:
                res_data = json.loads(response.read().decode('utf-8'))
                return res_data.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise TimeoutError(f"Ollama 回應逾時 (120 秒)。這通常是因為大模型 (例如 {model}) 正在進行首次記憶體載入或硬體運算能力較吃緊。請稍後再次嘗試執行，或更換為較輕量的模型。")
        raise ConnectionError(f"無法連線至 Ollama 服務 ({host})。請確認 Ollama 已啟動，或使用 --gemini 參數指定 Gemini API。\n錯誤詳情: {e}")
    except socket.timeout:
        raise TimeoutError(f"Ollama 回應逾時 (120 秒)。這通常是因為大模型 (例如 {model}) 正在進行首次記憶體載入或硬體運算能力較吃緊。請稍後再次嘗試執行，或更換為較輕量的模型。")


def call_gemini(prompt, system_prompt, api_key, model="gemini-2.5-pro"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"System Instruction:\n{system_prompt}\n\nUser Question:\n{prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2
        }
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            candidates = res_data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return "無法解析 Gemini 的回應內容。"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        raise ConnectionError(f"Gemini API 呼叫失敗 (HTTP {e.code}): {error_body}")
    except Exception as e:
        raise ConnectionError(f"Gemini API 呼叫時發生錯誤: {e}")


def _is_mcq(query):
    """偵測是否為選擇題（包含 A. B. C. D. 或 A） B） 等格式）。"""
    import re
    return bool(re.search(r'\bA[\.）\)]\s', query) and re.search(r'\bB[\.）\)]\s', query))


def _build_history_block(history: list, max_turns: int = 3) -> str:
    """將最近對話歷史轉為 prompt 可插入的情境區塊。"""
    if not history:
        return ""

    recent = history[-(max_turns * 2):]
    lines = ["【對話歷史（最近對話，供情境參考）】"]
    for msg in recent:
        role_label = "使用者" if msg.get("role") == "user" else "顧問"
        content = msg.get("content", "")
        if msg.get("role") == "assistant" and len(content) > 600:
            content = content[:600] + "…（略）"
        lines.append(f"{role_label}：{content}")
    lines.append("")
    return "\n".join(lines)


def build_prompt(query, matched_items, max_chars_per_item=600, history=None):
    """組裝 LLM 所需的 Prompt，並加入 token 截斷防護。"""
    history_block = _build_history_block(history or [])
    context_parts = []
    for idx, r in enumerate(matched_items, 1):
        item = r["item"]
        item_type_zh = "條文" if item["type"] == "clause" else "附錄 A 控制措施"

        content = item["content"]
        if len(content) > max_chars_per_item:
            content = content[:max_chars_per_item] + "…（以下省略）"

        context_parts.append(
            f"=== [{item['id']}] {item['subsection']} ===\n"
            f"類型：{item_type_zh}  章節：{item['section']}\n"
            f"條文內容：\n{content}\n"
            f"（以上內容僅屬於 [{item['id']}]，勿與其他條文混用）"
        )

    context_str = "\n".join(context_parts)

    mcq_hint = ""
    if _is_mcq(query):
        mcq_hint = "\n\n【重要指示】此為選擇題。請在 🎯 諮詢問題分析之後、📖 依據條文之前，先輸出：\n✅ **建議答案：X**（X 為最正確的選項字母，並用一句話說明理由）\n然後逐一說明其他選項的錯誤原因（每項一句話）。"

    prompt = f"""{history_block}【使用者提問】
{query}

【檢索到的 ISO 27001 相關規範參考】
{context_str}

請根據上述參考規範，提供專業的顧問解答。{mcq_hint}"""
    return prompt


def map_phase(query, item, model, host):
    """Map：從單一條文提取與問題相關的要點（1-3 點）。"""
    content = item.get("content", "")
    if len(content) > 800:
        content = content[:800] + "…"
    prompt = (
        f"【ISO 27001 條文 {item['id']}】\n"
        f"章節：{item['section']} > {item['subsection']}\n"
        f"內容：{content}\n\n"
        f"【問題】{query}\n\n"
        "請從此條文中條列出與問題直接相關的要點（最多 3 點，每點 1 句話）。"
        "若此條文與問題完全無關，僅回答：不相關"
    )
    system = "你是 ISO 27001 條文分析助理。請從給定條文中提取與問題相關的要點，簡潔精準，不超過 3 點。"
    return call_ollama(prompt, system, model=model, host=host)


def reduce_phase(query, map_results, model, host, on_chunk=None):
    """Reduce：彙整所有 Map 要點，生成最終顧問解答。"""
    relevant = [
        f"[{item['id']} {item['subsection']}]\n{points}"
        for item, points in map_results
        if points.strip() and "不相關" not in points.strip()
    ]
    if not relevant:
        msg = "根據檢索結果，目前條文庫中沒有找到與此問題直接相關的條文依據。"
        if on_chunk:
            on_chunk(msg)
        return msg
    points_text = "\n\n".join(relevant)
    prompt = (
        f"【使用者提問】\n{query}\n\n"
        f"【各條文關鍵要點彙整】\n{points_text}\n\n"
        "請根據以上條文要點，提供專業的顧問解答。"
    )
    return call_ollama(prompt, get_system_prompt(), model=model, host=host, on_chunk=on_chunk)


def map_reduce_query(query, matched_items, model, host, on_progress=None, on_chunk=None):
    """完整 Map-Reduce 流程：逐條提取要點，再彙整生成解答。"""
    map_results = []
    for i, r in enumerate(matched_items):
        item = r["item"]
        if on_progress:
            on_progress(f"Map [{i + 1}/{len(matched_items)}] {item['id']}...")
        points = map_phase(query, item, model, host)
        map_results.append((item, points))
    if on_progress:
        on_progress("Reduce 彙整中...")
    return reduce_phase(query, map_results, model, host, on_chunk=on_chunk)


def get_system_prompt():
    return """你是一位專業的 ISO 27001 資訊安全管理系統 (ISMS) 顧問。你的職責是根據 Context 提供的 ISO 27001 繁體中文條文與控制措施，回答使用者的諮詢。

請遵循以下最高指導原則：
1. 一律使用繁體中文（台灣用語）回應，不使用簡體中文或中國大陸慣用語。
2. 回答必須基於 Context 中所提供的條文或控制措施。
3. 【強制引用規則】每個論述句子末尾必須標註其依據的條文 ID，格式為 [control_X.X] 或 [clause_X.X]。標註前自問：「這項要求的原文確實出現在該 ID 的條文內容中嗎？」若不確定，不得標註該 ID。
3b. 【選擇題規則】若問題含有選項（A. B. C. D.），必須在 🎯 分析後立即輸出「✅ **建議答案：X**（理由一句話）」，再說明其他選項的錯誤原因。
4. 提供實務性的建議。對於使用者的合規性疑問，請協助分析「文件缺口」或「需要的稽核證據」。
5. 【重要 - 格式與長度優化】直接切入核心回答，禁止任何客套問候語（如「您好，我是...」）。
6. 回答字數請控制在 350 字以內，以精煉的條列式呈現，確保在有限長度內完整輸出所有核心建議。
7. 【三層引用架構】回答前對 Context 中每個條文做分類判斷：
   - 核心條文（直接回答問題）：必須詳細說明，完整引用
   - 延伸條文（間接相關）：在主要說明後以「📌 相關考量」段落簡短提及
   - 背景條文（僅語意相近但不回答問題）：完全省略
8. 【控制項消歧規則 — 高頻混淆對】標註前務必確認：
   - 「密碼/通行碼的複雜度、更換頻率、保密要求」→ 屬於 [control_5.17 鑑別資訊]，NOT 8.24
   - 「加密演算法、金鑰生成/儲存/銷毀、PKI 憑證」→ 屬於 [control_8.24 密碼技術之使用]，NOT 5.17
   - 「帳號/使用者 ID 的建立與停用」→ 屬於 [control_5.16 身分管理]，NOT 8.24
   - 「存取權限的審查與撤銷」→ 屬於 [control_5.18 存取權限]，NOT 5.16
   - 「聘用終止後的責任」→ 屬於 [control_6.5 聘用終止或變更後之責任]
   - 「離職時資產歸還」→ 屬於 [control_5.11 資產之歸還]
9. 【閉卷約束與延伸聲明】
   - 你的回答只能引用上方 Context 中明文出現的條文內容。
   - 若某面向在 Context 中找不到依據，明確說明：「依目前檢索到的條文尚未涵蓋此面向」。
   - 若要補充 Context 未涵蓋但對使用者有價值的 ISO 27001 常識或實務，必須用【延伸建議，非條文明文】標籤明確標示，且不得加上任何條文 ID 標註。
10. 回答應使用結構化 Markdown，包含：
    - 🎯 **諮詢問題分析** (1-2 句，描述「問題要求什麼」，不引入條文)
    - 📖 **依據條文與控制項說明** (只列核心條文，每句末標註 [ID])
    - 🛠️ **文件缺口與稽核證據建議** (最核心的 2-3 點，聚焦核心條文舉證需求)
    - ⚠️ **免責與合規警示** (簡短 1 句話)"""


def load_dotenv(env_path=None):
    """純 Python 實作輕量版 .env 載入器，避免本地離線環境需要安裝額外套件。"""
    if os.environ.get("SKIP_DOTENV") == "1":
        return
    if env_path is None:
        env_path = Path(__file__).resolve().parents[3] / ".env"
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val
