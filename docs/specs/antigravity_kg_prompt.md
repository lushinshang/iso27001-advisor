# Antigravity CLI 提示詞：KG 建置改道（--from-pdca）+ Phase 8 期末考

> 用法：於專案根目錄啟動 antigravity CLI，貼入本檔全文（或指示其讀取本檔）。
> 前手（Codex CLI）已完成 Phase 0-6 與兩輪修訂，本提示詞自帶現況摘要，
> 但**權威規格仍是 `docs/specs/kg_hybrid_search_sdd.md`（v1.2）**，先完整閱讀它。

---

你是本專案（ISO 27001 Advisor，Python src layout）的實作工程師，接手前一位
工程師的工作。任務：完成 KG 建置改道與 Phase 8 期末考。

## 現況摘要（前手已完成，皆已驗證）

- Phase 0-6 完成：`core/hybrid_search.py`（rrf_fuse / HybridSearcher / 離線
  fallback / KG 1-hop）、`core/kg_gates.py`（G1-G4）、`scripts/build_embeddings.py`
  （已產出 `data/clause_embeddings.json`，129 筆）、`scripts/build_knowledge_graph.py`
  （候選清單提名法、checkpoint）、`scripts/eval_nominator.py`。
- `python3 -m pytest -q` 全綠，共 225 tests。
- 正式提名器評測後，LLM 提名產線已**暫停封存**（SDD §9）：gemma3:12b 引文
  誠實率僅 12.73%，觸發重新設計條件。**不要嘗試重啟或修復 LLM 提名產線。**
- `data/kg_gold_edges.json` 已產出（127 條，源自 pdca_graph）。
- `data/knowledge_graph.json` 尚未產出——這是你的任務。

## 絕對規則（違反即停止）

1. **SDD 為準**：`docs/specs/kg_hybrid_search_sdd.md` v1.2 是唯一權威規格，
   特別是 §9（改道決策）。實作與規格衝突時以規格為準；有歧義時停下列出問題，
   不自行猜測。
2. **TDD**：每項新功能先寫測試、確認失敗（紅），再實作到通過（綠），
   然後跑全套 `python3 -m pytest -q`（0 failed）才進下一步。
3. **全程離線**：只允許呼叫 `http://localhost:11434`（Ollama）。
   禁止其他網路請求、禁止安裝新套件。
4. **不碰既有邏輯**：不修改 `core/search_tool.py` 的檢索邏輯、既有測試、
   LV2/LV3 tools、app.py/main.py/agent.py。`eval/evaluation.py` 僅允許
   `--hybrid` 開關相關的新增（若前手已加好就不要再動）。
5. **驗證誠實**：沒實際執行的驗證不准回報通過；指標退步不得調參數湊數
   （G1 規則、degree cap ≤ 6、RRF k=60、kg_damp=0.5 以規格為準）。
6. **風格**：繁體中文註解與訊息（台灣用語），遵循專案既有慣例，
   不加規格外的功能。

## 任務（依序執行）

### 任務 0：基準確認
跑 `python3 -m pytest -q`，應為 225 tests 全綠。不綠就停下回報，不要修。

### 任務 1：--from-pdca 建圖模式（TDD）
為 `scripts/build_knowledge_graph.py` 新增 `--from-pdca` 模式（規格：SDD §9.2）：
- 從 `data/pdca_graph.json` 各節點的 `related` 欄位展開邊對（`next` 欄位不採用）
- `from < to` 字典序正規化去重
- 兩端 ID 皆需存在於 `data/iso27001_structure.json`
- 套 G1 結構規則 + degree cap ≤ 6（重用 `core/kg_gates.py`，不重寫）
- G2/G3/G4 跳過；邊的 `source` 標 `"pdca_graph"`、`evidence_*` 置空
- 報表附全部邊的 G3 相似度分布（用 `data/clause_embeddings.json` 計算，
  僅供參考，**不做過濾**）
- 輸出 schema 遵循 SDD §5.3（含 gate_report）

先寫測試（含：related 展開、去重、無效 ID 過濾、degree cap、next 不採用），
看紅，再實作到綠，跑全套。

### 任務 2：實跑建圖
`python3 scripts/build_knowledge_graph.py --from-pdca` 產出
`data/knowledge_graph.json`。回報：邊數、degree cap 砍掉幾條、相似度分布摘要。

### 任務 3：Phase 8 期末考
`python3 eval/evaluation.py --hybrid`（HybridSearcher + 上一步的 KG）與
keyword-only 基準對照，回報完整對照表：
Hit Rate@4 / Avg Recall@4 / Avg Precision@4 / MRR@4。
- 合併條件：Hit Rate = 100%、Recall ≥ 93.3%、MRR ≥ 0.9333（不退步）
- **退步時**：輸出退步題目清單（題目、期望條文、兩種模式各自檢索到什麼），
  然後停下。不修任何東西。
- 持平或提升也停下，回報後等使用者確認才算 Phase 8 完成。

### 任務 4（選配診斷，與主線互不阻塞，可最後做）
`python3 scripts/eval_nominator.py --sample 25 --models gemma4:12b-it-qat-16k`
（約 30 分鐘，100 次 Ollama 呼叫）。回報指標表（格式合格率／引文誠實率／
存活產量／黃金邊召回）。目的：鑑別「引文抄寫不可靠」是 gemma3 個體問題還是
12B 量級通病（SDD §9.3）。**僅記錄結果，不改變產線封存狀態、不做任何後續動作。**

## 完成後回報格式

1. 各任務的測試結果（新增測試數 / 全套 pytest 數字）
2. KG 建圖報表（邊數、gate_report、相似度分布）
3. 期末考對照表（keyword-only vs hybrid 四指標）
4. 選配診斷指標表（若執行）
5. 未解決問題與規格歧義清單（若有）
