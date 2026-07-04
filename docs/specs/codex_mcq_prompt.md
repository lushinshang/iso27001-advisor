# Codex CLI 提示詞：v4.4 MCQ 多選支援與選項分解檢索

> 用法（專案根目錄）：
>
> ```bash
> codex exec -s workspace-write "$(cat docs/specs/codex_mcq_prompt.md)"
> ```

---

你是本專案（ISO 27001 Advisor，Python src layout）的實作工程師。
任務：實作 v4.4——MCQ 多選支援與選項分解檢索。
**權威規格：`docs/specs/kg_hybrid_search_sdd.md` §12，先完整閱讀 §12.1-12.3。**

## 絕對規則（違反即停止）

1. SDD §12 為唯一權威；歧義時停下列出問題，不猜測。
2. TDD：先寫測試看紅，再實作到綠，每步跑全套 `python3 -m pytest -q`（0 failed）。
3. 全程離線：只允許 `http://localhost:11434`，禁裝新套件。
4. 不碰：`search_tool.py` 檢索邏輯、`HybridSearcher` 既有行為、LV2/LV3 tools、
   LLM 提名產線、雙資料集回歸護欄、評估集 JSON。
   `main.py` / `app.py` 只允許在檢索呼叫點做最小 diff 接線（§12.2c）。
5. **既有單選 MCQ 行為必須完全不變**（faithfulness 評估集依賴它）——
   多選指令只在偵測到多選訊號時觸發。
6. 驗證誠實；繁體中文（台灣用語）註解與訊息；每完成一項本地 git commit。

## 任務（依序，TDD）

### 任務 1：多選偵測 `_mcq_mode()`
`llm.py` 新增 `_mcq_mode(query)`：無選項 → None；有選項＋多選訊號
（「哪些」「複選」「多選」「所有正確」）→ "multi"；有選項無訊號 → "single"。
既有 `_is_mcq` 可重構為內部使用，但對外行為不變。
測試：single/multi/None 各 ≥ 2 案例（含「哪些」出現但無選項 → None）。

### 任務 2：多選指令注入
`build_prompt()`：mode="multi" 時注入多選版指令
（「✅ 建議答案：X、Y（列出所有正確選項）」＋逐項條文依據＋其餘選項理由）；
mode="single" 維持原指令一字不改。System Prompt 規則 3b 改寫涵蓋單/多選。
測試：斷言兩種 mode 注入的指令內容、None 時不注入。

### 任務 3：選項分解檢索
`core` 新增（建議 `core/mcq_search.py`）：
- `split_mcq_options(query)`：支援 `(A)` / `A.` / `A）` 三種格式，
  回傳題幹與選項 dict
- `mcq_union_search(searcher, query, limit=4, per_option=2)`：
  題幹 top-limit ＋ 每選項 top-per_option，聯集去重（同 id 取最高分）重排
測試：三種格式拆解；**真實回報題**（ISO 27001:2022 實體控制措施多選題，
題目全文見 SDD §12.1 對應描述，選項 A=實體進入控制措施、B=遠端工作應提出申請、
C=維護設備以確保其持續之可用性及完整性、D=未經事前授權不得將設備資訊帶出場域外）
以真實 ISO27001Searcher 執行 `mcq_union_search`，斷言結果包含
`control_7.2` 與 `control_7.13`。

### 任務 4：接線
`main.py` 的 `process_query` 與 `app.py` 的檢索呼叫點：
偵測到 MCQ（single 或 multi 皆是）時改走 `mcq_union_search`，其餘路徑不變。
最小 diff；不動 Strict Offline、SSE、快取等既有邏輯。
測試：可用注入 mock searcher 驗證路由（不需真 LLM）。

### 任務 5：最終驗證與回報
- `python3 -m pytest -q` 全綠，回報總測試數
- 回報各任務 commit hash
- 回報未解決問題／規格歧義（若有）
- 不要執行需要 LLM 生成的 e2e（§12.3 第 4 條由使用者人工確認）
