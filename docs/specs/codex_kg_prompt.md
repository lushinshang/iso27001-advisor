# Codex CLI 提示詞：Hybrid Search + KG 自動把關產線實作

> 用法（於專案根目錄執行）：
>
> ```bash
> codex exec -s workspace-write "$(cat docs/specs/codex_kg_prompt.md)"
> ```
>
> 建議先以 read-only 讓 Codex 讀規格確認理解，再切 workspace-write 實作。

---

你是本專案（ISO 27001 Advisor，Python src layout）的實作工程師。
你的任務：依照權威規格 `docs/specs/kg_hybrid_search_sdd.md` 完成
Hybrid Search（RRF）+ Knowledge Graph 1-hop 與 KG 自動把關產線。

## 絕對規則（違反即停止）

1. **SDD**：`docs/specs/kg_hybrid_search_sdd.md` 是唯一權威規格。實作與規格衝突時，以規格為準；規格有歧義時，停下來在輸出中列出問題，不要自行猜測。
2. **TDD**：嚴格依規格 §7 的 Phase 順序執行。每個 Phase 必須：
   a. 先寫測試，執行並確認失敗（紅）
   b. 實作到測試通過（綠）
   c. 跑全套 `python3 -m pytest -q`，0 failed 才能進入下一 Phase
   d. 在輸出中回報該 Phase 的測試數與結果
3. **全程離線**：只允許呼叫 `http://localhost:11434`（Ollama）。禁止任何其他網路請求、禁止安裝新套件（標準庫 + 專案既有依賴即可）。
4. **不碰既有邏輯**：不得修改 `src/iso27001_advisor/core/search_tool.py` 的檢索邏輯、不得修改任何既有測試、不得修改 LV2/LV3 tools 與 app.py/main.py/agent.py。`eval/evaluation.py` 只允許新增 `--hybrid` 開關（不改變預設行為）。
5. **驗證誠實**：沒跑過的驗證不准回報通過。測試失敗就如實回報失敗原因。禁止為了讓指標好看而調鬆關卡參數（G3 floor、degree cap、RRF k 值以規格為準）。
6. **程式風格**：繁體中文註解與訊息（台灣用語）、遵循專案既有慣例（參考 `semantic_cache.py` 的錯誤處理與 checkpoint 模式）、不加規格外的功能與抽象。

## 執行步驟

1. 完整閱讀 `docs/specs/kg_hybrid_search_sdd.md`（規格）與以下既有程式碼：
   - `src/iso27001_advisor/core/search_tool.py`（關鍵字檢索，將被包裝）
   - `src/iso27001_advisor/core/semantic_cache.py`（embedding 呼叫與 E5 prefix 慣例，直接重用其模式）
   - `eval/evaluation.py`（期末考基準）
   - `tests/conftest.py` 與任一既有測試檔（測試慣例）
2. 執行 Phase 0：跑 `python3 -m pytest -q` 記錄基準（應全綠），並以 `ollama list` 確認 `gemma3:12b-16k`、`gemma4:e2b-mlx`、`jeffh/intfloat-multilingual-e5-large-instruct:f16` 存在；缺模型則回報並停止。
3. 依序執行 Phase 1 → 8，每 Phase 遵守上述 TDD 鐵律。
4. Phase 7（實跑建置）與 Phase 8（期末考）耗時較長（雙模型 × 3 輪 × 144 節點），使用規格要求的 checkpoint 續跑機制；若指標退步，輸出退步題目清單與分析後**停止**，不要自行修補。

## 完成後回報格式

- 各 Phase 測試結果表（Phase / 新增測試數 / 全套 pytest 結果）
- `data/knowledge_graph.json` 的 gate_report 數字
- `eval_nominator.py` 指標表（兩個提名模型對照）
- 期末考對照表：keyword-only vs hybrid 的 Hit Rate / Recall / Precision / MRR
- 未解決問題與規格歧義清單（若有）
