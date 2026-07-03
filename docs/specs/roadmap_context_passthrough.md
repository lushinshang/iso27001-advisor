# 實作計畫：Roadmap Context Passthrough

**功能**：「協助設計改善計畫」請求應銜接第一次缺口分析的結果，而非重新分析。  
**版本**：v4.0  
**日期**：2026-06-29

---

## 一、問題陳述（Problem Statement）

現行 roadmap 模式（`mode=roadmap`）在 `app.py:579` 執行：

```python
gap_result = _analyze_coverage(query, matched)
```

當使用者以「協助設計改善計畫」作為第二個問題時，`query` 是這段文字本身，而非第一個問題的客觀現況。`_analyze_coverage` 因此找到的是與「稽核」相關的缺口（A.9.2），而非第一次分析的備份缺口（A.8.13）。

**期望行為**：roadmap 請求應直接使用第一次 gap 分析的結構化結果（`gap_result`），並附上使用者第一次的原始問題文字，讓 LLM 撰寫具體且符合客觀現況的改善行動。

---

## 二、軟體設計文件（SDD）

### 2.1 架構決策

| 選項 | 說明 | 決策 |
|---|---|---|
| A. 前端傳原始問題，後端重跑分析 | 簡單但結果不穩定 | ✗ |
| B. 後端 session 快取 gap_result | 需管理狀態，增加複雜度 | ✗ |
| **C. 前端存 gap_result，隨 roadmap 請求一起傳** | Stateless、結果確定、改動最小 | ✓ |

### 2.2 資料流（修改後）

```
[Gap 分析完成]
  後端 SSE → { type: "gap_result", data: gap_result }
  前端儲存 → lastGapQuery = 使用者原始問題
              lastGapResult = gap_result

[使用者問：協助設計改善計畫]
  前端 POST /api/chat
    body: {
      query: "協助設計改善計畫",
      mode: "roadmap",
      context_query: lastGapQuery,     ← 新增
      context_gap_result: lastGapResult ← 新增
    }

[後端 roadmap 模式]
  if context_gap_result 存在:
      gap_result = context_gap_result  ← 直接使用，跳過 _analyze_coverage
  else:
      gap_result = _analyze_coverage(query, matched)  ← fallback

  prompt = build_roadmap_prompt(
      document_text = context_query or query,  ← 原始現況描述
      roadmap = _build_roadmap(gap_result, clause_ids)
  )
```

### 2.3 需修改的檔案

| 檔案 | 變更類型 | 說明 |
|---|---|---|
| `app.py` | 修改 | gap 模式新增 `gap_result` SSE event；roadmap 模式接受並使用 `context_gap_result` 與 `context_query` |
| `index.html` | 修改 | 捕捉 `gap_result` event 並存入 state；roadmap 請求附帶 context |
| `agent.py` | 修改 | `build_roadmap_prompt()` 新增 `context_query` 參數 |

### 2.4 API 請求格式（修改後）

```json
POST /api/chat
{
  "query": "協助設計改善計畫",
  "mode": "roadmap",
  "model": "gemma4:e2b-mlx",
  "host": "http://localhost:11434",
  "top_k": 4,
  "context_query": "我們公司每日備份資料庫到本地 NAS，但沒有定期還原測試...",
  "context_gap_result": {
    "risk_level": "high",
    "missing_signals": [
      {"theme": "還原測試", "detail": "..."},
      {"theme": "備份保存期限", "detail": "..."},
      {"theme": "備份保護（加密/異地）", "detail": "..."}
    ],
    "covered": ["每日備份至 NAS"]
  }
}
```

### 2.5 SSE Event 新增（gap 模式）

```json
{ "type": "gap_result", "data": { ...gap_result... } }
```

此 event 在 `gap_result` 計算完成後、LLM 推理開始前發出，讓前端可以及早儲存。

### 2.6 `build_roadmap_prompt` 簽名變更

```python
# 修改前
def build_roadmap_prompt(document_text: str, roadmap: dict, detail_level: str = "standard") -> str

# 修改後
def build_roadmap_prompt(
    document_text: str,
    roadmap: dict,
    detail_level: str = "standard",
    context_query: str = "",  # 新增：使用者原始現況描述
) -> str
```

當 `context_query` 非空時，prompt 的「現況描述」欄位優先使用 `context_query`，`document_text` 作為 fallback。

---

## 三、測試驅動設計（TDD）

### 3.1 測試策略

- 所有新行為先寫測試，再實作
- 後端測試使用 `pytest` + `httpx.AsyncClient` 對 FastAPI app 做整合測試
- 前端邏輯不寫自動化測試（UI 狀態管理），以手動驗收清單取代

### 3.2 測試檔案

新增：`tests/test_roadmap_context.py`

### 3.3 測試案例（Test Cases）

#### TC-01：gap 模式回應包含 gap_result event

```python
def test_gap_mode_emits_gap_result_event():
    """gap 模式的 SSE 串流中必須包含 type=gap_result 的 event。"""
    # Given: 一個備份相關的 gap 查詢
    # When: POST /api/chat with mode=gap
    # Then: SSE events 中存在 type == "gap_result"
    #       且 data 包含 "missing_signals" key
```

#### TC-02：roadmap 模式接受並使用 context_gap_result

```python
def test_roadmap_uses_context_gap_result_when_provided():
    """當請求帶有 context_gap_result 時，roadmap 模式不呼叫 _analyze_coverage。"""
    # Given: context_gap_result = {"missing_signals": [{"theme": "還原測試"}], ...}
    # When: POST /api/chat with mode=roadmap + context_gap_result
    # Then: SSE chunks 中的改善計畫包含「還原測試」
    #       且 agent_log 中不出現 tool.analyze_document_coverage
```

#### TC-03：roadmap 模式無 context 時 fallback 正常

```python
def test_roadmap_fallback_when_no_context():
    """當請求不帶 context_gap_result 時，roadmap 模式正常執行 _analyze_coverage。"""
    # Given: 無 context_gap_result
    # When: POST /api/chat with mode=roadmap, query="備份缺還原測試"
    # Then: 回應正常（不 crash）
    #       且 agent_log 包含 tool.analyze_document_coverage
```

#### TC-04：build_roadmap_prompt 優先使用 context_query

```python
def test_build_roadmap_prompt_uses_context_query_when_provided():
    """context_query 非空時，prompt 的現況欄位應包含 context_query 內容。"""
    # Given: document_text="協助設計改善計畫", context_query="我們公司每日備份..."
    # When: build_roadmap_prompt(document_text, roadmap, context_query=context_query)
    # Then: 回傳的 prompt 包含 "我們公司每日備份"
    #       且不包含 "協助設計改善計畫" 在現況欄位
```

#### TC-05：build_roadmap_prompt 無 context_query 時使用 document_text

```python
def test_build_roadmap_prompt_fallback_to_document_text():
    """context_query 為空時，prompt 的現況欄位使用 document_text。"""
    # Given: document_text="備份缺還原測試", context_query=""
    # When: build_roadmap_prompt(document_text, roadmap)
    # Then: 回傳的 prompt 包含 "備份缺還原測試"
```

#### TC-06：前端狀態手動驗收清單

```
□ 發送 gap 查詢後，開啟 DevTools Console，確認 lastGapResult 非 null
□ 切換到 roadmap 模式，發送「協助設計改善計畫」
□ 在 Network 分項確認 /api/chat 請求 body 包含 context_gap_result
□ 改善計畫的缺口項目與第一次 gap 分析一致（如「還原測試」）
□ gap 查詢後若重新整理頁面，roadmap 請求不帶 context（正常 fallback）
```

---

## 四、實作步驟（Implementation Order）

依 TDD 順序：**先寫測試 → 跑失敗 → 實作 → 跑通過**

### Step 1：新增測試檔 `tests/test_roadmap_context.py`
- 寫 TC-01 ～ TC-05（此時全部應 FAIL）

### Step 2：修改 `agent.py` — `build_roadmap_prompt`
- 新增 `context_query: str = ""` 參數
- prompt 現況欄位改為：`context_query if context_query else document_text`
- 跑 TC-04、TC-05 → 應通過

### Step 3：修改 `app.py` — gap 模式
- 在 `gap_result = _analyze_coverage(...)` 之後、LLM 推理之前，新增：
  ```python
  yield f"data: {json.dumps({'type': 'gap_result', 'data': gap_result})}\n\n"
  ```
- 跑 TC-01 → 應通過

### Step 4：修改 `app.py` — roadmap 模式
- 從 request body 讀取 `context_gap_result`（`Optional[Dict]`，預設 `None`）和 `context_query`（`str`，預設 `""`）
- roadmap 分支邏輯：
  ```python
  if context_gap_result:
      gap_result = context_gap_result
  else:
      gap_result = _analyze_coverage(query, matched)
  ```
- `build_roadmap_prompt` 呼叫加入 `context_query` 參數
- 跑 TC-02、TC-03 → 應通過

### Step 5：修改 `index.html` — 前端狀態
- 在 `sendMessage()` 函式頂部新增 `let lastGapQuery` 與 `let lastGapResult` 為模組級 state
- event handler 新增 `gap_result` 處理：
  ```js
  } else if (event.type === 'gap_result') {
      lastGapResult = event.data;
  }
  ```
- gap 模式 done 時：`lastGapQuery = query`
- 發送請求時，若 `queryMode === 'roadmap'` 且 `lastGapResult` 存在，附加欄位

### Step 6：跑完整測試套件
```bash
python -m pytest tests/ eval/tests/ -q
```
- 全部 187 + 新增測試通過，才算完成

---

## 五、邊界條件與風險

| 情境 | 處理方式 |
|---|---|
| 使用者直接問 roadmap，沒有先做 gap | `context_gap_result` 為 null，fallback 到 `_analyze_coverage`，行為與現在相同 |
| 頁面重新整理後問 roadmap | `lastGapResult` 為 null，同上 fallback |
| `context_gap_result` 格式異常 | `build_remediation_roadmap` 的 `gap_result.get("missing_signals", [])` 預設空清單，不 crash |
| gap 模式以外（qa/evidence）後接 roadmap | `lastGapResult` 不會被更新，保持 null，fallback |

---

## 六、不在本次範圍內

- 多輪對話的 session 管理
- `lastGapResult` 的跨 tab 持久化（LocalStorage）
- 改善計畫的差異比對（與前一版對照）
