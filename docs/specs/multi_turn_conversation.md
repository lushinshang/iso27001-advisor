# 實作計畫：多輪對話情境感知（Multi-turn Conversation History）

**功能**：所有諮詢類型均可銜接前幾輪問答的情境。  
**版本**：v4.1  
**日期**：2026-06-29  
**參考**：[Sliding Window Memory](https://github.com/ligilou/llm-sliding-window-memory) · [mem0 Chat History Guide](https://mem0.ai/blog/llm-chat-history-summarization-guide-2025) · [Context Window Management](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/)

---

## 一、問題陳述

現行每次請求完全無狀態（stateless）。使用者做完缺口分析後，不管切換到哪個諮詢類型，下一個問題都無法承接前一輪的客觀現況與分析結論。

**期望行為**：

| 第一輪 | 第二輪（任意模式） | 期望 |
|---|---|---|
| gap：備份缺還原測試 | roadmap：協助設計改善計畫 | 計畫基於備份缺口 |
| gap：備份缺還原測試 | qa：哪個最優先？ | 顧問知道「備份」是上文脈絡 |
| gap：備份缺還原測試 | evidence：需要準備什麼？ | 直接聚焦備份相關證據 |

---

## 二、架構決策

### 2.1 主流策略比較

| 策略 | 說明 | Token 用量 | 適合場景 |
|---|---|---|---|
| Full Window | 所有歷史全塞 | 線性成長，不可控 | 短對話 |
| Sliding Window | 只保留最近 N 輪 | 固定上界 | 一般諮詢 ✓ |
| Sliding + Summarization | 近 N 輪原文 + 舊輪摘要 | 壓縮後固定 | 長對話生產環境 |
| RAG over History | 歷史存向量庫，按需檢索 | 最小 | 超長期對話 |

**本專案選擇：Sliding Window（最近 3 輪）**

理由：
- Demo app，對話通常不超過 10 輪
- 不需 LLM 摘要（避免額外 API 呼叫）
- 3 輪涵蓋絕大多數「前一個問題銜接」場景
- 每輪 assistant 回應截斷至 600 字元，控制 token 預算

### 2.2 歷史格式（業界標準）

```json
[
  {
    "role": "user",
    "content": "我們公司每日備份資料庫到本地 NAS，但沒有定期還原測試...",
    "mode": "gap"
  },
  {
    "role": "assistant",
    "content": "【判斷摘要】貴公司在資訊備份管理方面存在關鍵缺失...\n【主要缺口】1. 缺乏還原測試 2. 未定義保存期限 3. 備份保護不足",
    "mode": "gap"
  }
]
```

### 2.3 資料流

```
[前端]
conversationHistory = []   ← 模組級 state，頁面存活期間保持

每次請求送出：
  POST /api/chat {
    query: "...",
    mode: "roadmap",
    history: conversationHistory.slice(-6),  ← 最近 3 輪（6 則）
    ...原有欄位
  }

每次回應完成：
  conversationHistory.push({role:"user", content: query, mode: queryMode})
  conversationHistory.push({role:"assistant", content: truncate(responseText, 600), mode: currentMode})

[後端]
history = body.get("history", [])   ← List[{role, content, mode}]

history_block = _build_history_block(history)
↓
注入到每個 mode 的 prompt 頂端
```

### 2.4 與 v4.0 context_gap_result 的關係

**保留** `context_gap_result`（v4.0 實作）：
- 用途：roadmap 工具層（deterministic），直接決定哪些缺口進 30/60/90 天計畫
- 本質：結構化資料，不是文字

**新增** `history`（v4.1 實作）：
- 用途：LLM prompt 層，提供自然語言情境
- 本質：文字對話歷史

兩者互補，不衝突。

---

## 三、軟體設計文件（SDD）

### 3.1 需修改的檔案

| 檔案 | 變更 |
|---|---|
| `agent.py` | 新增 `_build_history_block()` 工具函式；所有 `build_*_prompt()` 加 `history` 參數 |
| `app.py` | 從 request body 讀取 `history`；各 mode 呼叫 prompt builder 時傳入 `history` |
| `index.html` | 新增 `conversationHistory` state；每輪完成後 push；送出請求時附帶 |

### 3.2 `_build_history_block()` 設計

```python
def _build_history_block(history: list, max_turns: int = 3) -> str:
    """將對話歷史轉為 prompt 插入文字。
    
    只取最近 max_turns 輪（1 輪 = 1 user + 1 assistant）。
    每則 assistant 回應截斷至 600 字元。
    """
    if not history:
        return ""
    
    # 取最近 max_turns * 2 則
    recent = history[-(max_turns * 2):]
    
    lines = ["【對話歷史（最近對話，供情境參考）】"]
    for msg in recent:
        role_label = "使用者" if msg["role"] == "user" else "顧問"
        content = msg["content"]
        if msg["role"] == "assistant" and len(content) > 600:
            content = content[:600] + "…（略）"
        lines.append(f"{role_label}：{content}")
    lines.append("")  # 空行分隔
    
    return "\n".join(lines)
```

### 3.3 各 prompt builder 修改模式

以 `build_gap_prompt` 為例，其他模式同理：

```python
# 修改前
def build_gap_prompt(query, matched, gap_result, evidence_list, remediation, recs, detail_level="standard"):
    ...
    return f"""【使用者提供的文件或描述】
{query}
..."""

# 修改後
def build_gap_prompt(query, matched, gap_result, evidence_list, remediation, recs,
                     detail_level="standard", history: list = None):
    history_block = _build_history_block(history or [])
    ...
    return f"""{history_block}【使用者提供的文件或描述】
{query}
..."""
```

所有 build_*_prompt 函式套用相同模式：
- `build_gap_prompt` ✓
- `build_evidence_prompt` ✓
- `build_soa_prompt` ✓
- `build_audit_report_prompt` ✓
- `build_audit_pack_prompt` ✓
- `build_roadmap_prompt` ✓
- `build_prompt`（QA mode，在 `llm/` 套件內） ✓

### 3.4 app.py 修改模式

```python
# request body 讀取（加在現有欄位讀取之後）
history = body.get("history", [])
if not isinstance(history, list):
    history = []
# 防禦：最多接受 10 則（5 輪），多的捨棄
history = history[-10:]

# 各 mode 的 prompt builder 呼叫加入 history 參數
gap_prompt = build_gap_prompt(..., history=history)
evidence_prompt = build_evidence_prompt(..., history=history)
rm_prompt = build_roadmap_prompt(..., history=history)
# ... 其他 mode 同理
```

### 3.5 前端 state 設計

```js
// 模組級 state（sendMessage 函式外）
let conversationHistory = [];   // [{role, content, mode}]

// sendMessage() 內，請求 body 組裝
const requestBody = {
    query,
    mode: queryMode,
    history: conversationHistory.slice(-6),  // 最近 3 輪
    ...
};

// done event 處理後，記錄本輪
conversationHistory.push({ role: "user", content: query, mode: queryMode });
conversationHistory.push({
    role: "assistant",
    content: responseText.slice(0, 800),  // 截斷避免 state 過大
    mode: currentArtifactType || queryMode,
});
```

### 3.6 Token 預算估算

| 項目 | 估算字元 | 估算 token（中文 ~2 char/token） |
|---|---|---|
| 1 則 user（原始問題） | ~200 | ~100 |
| 1 則 assistant（截斷 600） | ~600 | ~300 |
| 3 輪（6 則）合計 | ~2,400 | ~1,200 |
| 現有 prompt（RAG + 工具資料） | ~3,000 | ~1,500 |
| **加入歷史後總計** | **~5,400** | **~2,700** |

Ollama `gemma4:e2b-mlx` context window 預設 8K token，2,700 token 的歷史佔用合理。

---

## 四、TDD 測試設計

### 4.1 測試檔案

新增：`tests/test_multi_turn.py`

### 4.2 測試案例

#### TC-01：`_build_history_block` 空歷史回傳空字串

```python
def test_build_history_block_empty():
    assert _build_history_block([]) == ""
```

#### TC-02：`_build_history_block` 正確格式化歷史

```python
def test_build_history_block_formats_correctly():
    history = [
        {"role": "user", "content": "備份問題", "mode": "gap"},
        {"role": "assistant", "content": "缺少還原測試", "mode": "gap"},
    ]
    result = _build_history_block(history)
    assert "使用者：備份問題" in result
    assert "顧問：缺少還原測試" in result
    assert "【對話歷史" in result
```

#### TC-03：`_build_history_block` 超過 max_turns 時只取最近 N 輪

```python
def test_build_history_block_truncates_to_max_turns():
    history = [
        {"role": "user", "content": f"第{i}輪問題", "mode": "gap"}
        for i in range(1, 9)  # 8 則 = 4 輪 user（無 assistant）
    ]
    result = _build_history_block(history, max_turns=3)
    assert "第8輪問題" in result  # 最新的要在
    assert "第1輪問題" not in result  # 最舊的要被截掉
```

#### TC-04：`_build_history_block` assistant 回應超過 600 字元時截斷

```python
def test_build_history_block_truncates_long_assistant():
    long_content = "A" * 800
    history = [{"role": "assistant", "content": long_content, "mode": "gap"}]
    result = _build_history_block(history)
    assert "…（略）" in result
    assert "A" * 601 not in result
```

#### TC-05：`build_gap_prompt` 有歷史時 prompt 包含歷史區塊

```python
def test_build_gap_prompt_includes_history():
    history = [
        {"role": "user", "content": "上一個問題", "mode": "qa"},
        {"role": "assistant", "content": "上一個答案", "mode": "qa"},
    ]
    prompt = build_gap_prompt("新問題", [], {}, [], [], [], history=history)
    assert "對話歷史" in prompt
    assert "上一個問題" in prompt
```

#### TC-06：`build_gap_prompt` 無歷史時 prompt 不含歷史區塊

```python
def test_build_gap_prompt_no_history_section_when_empty():
    prompt = build_gap_prompt("新問題", [], {}, [], [], [])
    assert "對話歷史" not in prompt
```

#### TC-07：後端 roadmap 模式接受並傳遞 history

```python
def test_roadmap_mode_receives_history(monkeypatch):
    """roadmap 請求帶 history 時，prompt builder 應收到 history 參數。"""
    captured = {}
    original_build = build_roadmap_prompt
    def mock_build(*args, **kwargs):
        captured["history"] = kwargs.get("history")
        return original_build(*args, **kwargs)
    monkeypatch.setattr(app_mod, "build_roadmap_prompt", mock_build)
    # ... 送出含 history 的 roadmap 請求
    assert captured["history"] is not None
    assert len(captured["history"]) > 0
```

#### TC-08：後端防禦—history 非 list 時降級為空

```python
def test_invalid_history_defaults_to_empty(monkeypatch):
    """history 欄位若非 list（如傳入字串），應降級為空 list 不 crash。"""
    # ... 送出 history="invalid" 的請求
    # Then: 不 crash，正常回應
```

#### TC-09：前端手動驗收清單

```
□ 發送第一個問題（gap 分析）後，DevTools Console 確認 conversationHistory.length === 2
□ 發送第二個問題（任意模式），Network 確認 request body 包含 history 陣列
□ 第二個問題的回應內容有提到第一個問題的脈絡（如「根據您之前提到的備份情況」）
□ 第 4 輪問題之後，request body 的 history 最多 6 則（3 輪）
□ 重整頁面後，history 清空，下一輪請求 history 為空陣列
```

---

## 五、實作步驟

### Step 1：新增 `tests/test_multi_turn.py`
寫 TC-01 ～ TC-08（全部 FAIL）

### Step 2：`agent.py` — 新增 `_build_history_block()`
- 實作函式邏輯
- 跑 TC-01 ～ TC-04 → 應通過

### Step 3：`agent.py` — 修改所有 `build_*_prompt()`
- 7 個函式各加 `history: list = None` 參數
- 函式頂部呼叫 `_build_history_block(history or [])`
- 注入到 prompt 頂部（在現有內容之前）
- 跑 TC-05、TC-06 → 應通過

### Step 4：`app.py` — 讀取 history 並傳遞給各 mode
- 讀取 `history = body.get("history", [])`
- 加入型別防禦與長度限制
- 每個 mode 的 prompt builder 呼叫加入 `history=history`
- 跑 TC-07、TC-08 → 應通過

### Step 5：`index.html` — 前端 state 管理
- 宣告 `conversationHistory = []`
- 送出請求時附帶 `history: conversationHistory.slice(-6)`
- done event 後 push 兩則
- 手動執行 TC-09 驗收清單

### Step 6：全套測試

```bash
python3 -m pytest tests/ eval/tests/ -q
```

192 + 新增 8 個 = 200 passed，才算完成。

---

## 六、邊界條件

| 情境 | 處理方式 |
|---|---|
| 第一輪請求（無歷史） | `history=[]`，`_build_history_block` 回傳空字串，prompt 不變 |
| history 非 list（惡意或錯誤傳值） | 後端降級為 `[]` |
| history 超過 10 則（前端帶太多） | 後端截斷為 `history[-10:]` |
| assistant 回應為空（錯誤情境） | push `content=""` 不影響 prompt |
| 頁面重整 | `conversationHistory` 清空，行為回到第一輪 |
| 快取命中（semantic cache）回應 | 仍執行 push，歷史正常累積 |

---

## 七、不在本次範圍

- LLM 摘要舊輪次（Sliding + Summarization）— 需額外 API 呼叫，留待 v4.2
- LocalStorage 持久化歷史（跨頁面重整）
- 多使用者 session 隔離（Backend session store）
- 歷史 token 計數（目前以字元數估算）

---

## 八、與 v4.0 的相容性

v4.0 實作（`context_gap_result` + `context_query`）**保留不動**。

v4.1 在其基礎上疊加：
- roadmap 模式：`context_gap_result` 決定工具層缺口 + `history` 提供 LLM 自然語言情境
- 其他模式：只有 `history` 提供情境

Sources:
- [Sliding Window Memory for LLM Chatbots](https://github.com/ligilou/llm-sliding-window-memory)
- [LLM Chat History Summarization Best Practices](https://mem0.ai/blog/llm-chat-history-summarization-guide-2025)
- [Context Window Management Strategies](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/)
- [Conversational RAG with Haystack](https://haystack.deepset.ai/tutorials/48_conversational_rag)
- [Multi-turn Conversational RAG Benchmarking](https://arxiv.org/pdf/2410.23090)
