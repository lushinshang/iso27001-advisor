# Test Design Document (TDD)
## ISO 27001 Advisor Agent — v1.2.0

**文件版本**：1.2.0  
**最後更新**：2026-06-25  
**測試框架**：pytest  

---

## 1. 測試目標 (Test Objectives)

本文件定義 ISO 27001 Advisor Agent 的測試策略，結合 **TDD (Test-Driven Development)** 與回歸測試，確保系統在持續優化時的效能、準確性與穩定度。

**主要測試目標**：
1. **搜尋引擎單元功能**：驗證 O(1) 查找、同義詞擴充、Soul-Word 加權、大章節降權等。
2. **評估指標單元測試**：驗證 `compute_recall()` 與 `compute_mrr()` 函式的計算正確性（包括各種邊界條件）。
3. **Recall@4 回歸防護**：保證在條文同義詞或權重調整時，10 題評估資料集之檢索 Recall@4 Hit Rate 為 100% 且無退化。
4. **提示詞構建與防護**：驗證 `build_prompt()` 的字數截斷防護邏輯，避免因超長條文損毀 LLM 上下文。
5. **CLI 入口防護**：確保指令列引數解析、無環境變數跳過（SKIP_DOTENV）、幫助說明等行為正確。

---

## 2. 測試範圍與架構 (Test Scope & Setup)

在 v1.2 中，我們建立了 `tests/conftest.py` 以提供 **Session Scope** 的共享 Fixtures（`searcher`、`eval_dataset`），顯著縮短測試載入並重複初始化 JSON 條文的耗時。

```
tests/
├── conftest.py               # 統一提供 Session Scope 共享 Fixture
├── test_search_tool.py       # 搜尋引擎功能單元測試 (28 項)
├── test_evaluation.py        # Recall/MRR 指標計算與評估 Schema 測試 (23 項)
├── test_recall_regression.py # 10 題核心場景 Recall@4 回歸測試 (15 項)
└── test_cli.py               # CLI 整合與提示詞截斷防護測試 (16 項)
                              ────────────────────────────────────────
                              總計 80 項測試 (全數通過)
```

---

## 3. 測試案例設計 (Test Cases)

### 3.1 `test_search_tool.py` — 搜尋引擎單元測試 (28 項)
涵蓋初始化、精確 ID 查找、搜尋邊界限制、篩選器、同義詞與 Soul-Word 的檢索分值等。

| 測試群組 | 測試 ID | 說明 | 預期結果 |
|---|---|---|---|
| 初始化與載入 | ST-01 | 成功載入條文與控制項結構 | 載入 144 筆 ISO 條文，不拋出例外 |
| 精確 O(1) 查找 | ST-02 | 精確 `get_by_id` 讀取 | `get_by_id("control_8.11")` 傳回資料遮蔽 |
| 精確 O(1) 查找 | ST-03 | 查找大小寫與空白處理 | 忽略大小寫與首尾空白仍可查得 |
| 精確 O(1) 查找 | ST-04 | 查找不存在之 ID | 回傳 `None`，不拋出例外 |
| 邊界限制與篩選 | ST-05/06 | 空查詢或 limit 限制 | 空字串傳回空列表； limit=0/1 等邊界皆正常 |
| 邊界限制與篩選 | ST-12 | `item_type` 篩選 | 指定 "control" 或 "clause" 回傳類型必定正確 |
| 同義詞與 Soul-Word | ST-07/08 | 同義詞擴充 (例如：個資、加密) | 相關條款加分並出現在 Top-4 中 |
| 同義詞與 Soul-Word | ST-09/10 | 核心主題詞加權 (例如：備份、遮罩) | 權重發揮作用，條款排在最前列 |
| 大章節降權 | ST-11 | 降權大章節 (無小數點 ID) | `clause_6` 比子條文分數低，避免佔用 Context |

### 3.2 `test_evaluation.py` — 評估指標單元測試 (23 項)
驗證 GRC 評估的核心指標計算法。

| 測試群組 | 測試 ID | 說明 | 預期結果 |
|---|---|---|---|
| Recall@K 計算 | REC-01 ~ 10 | 各種命中情況與邊界 (全命中、部分命中、未命中、重複項、空輸入) | 計算結果精確符合數學定義，重複檢索項不重複計入 |
| MRR@K 計算 | MRR-01 ~ 09 | 命中順序 (第一名命中為 1.0，第二名 0.5，第三名 0.33，無命中 0.0) | 順序加權結果正確，多個 expected 時以首個命中的位置為準 |
| 評估結果驗證 | EVAL-01 ~ 04 | `evaluation.py` 輸出 JSON Schema 格式及指標合理性 | 輸出 `eval_results.json` 包含 `mrr` 與 `avg_recall_percent` |

### 3.3 `test_recall_regression.py` — 回歸測試 (15 項)
確保條文優化後，針對 10 個最常見的 GRC 資安核心諮詢問題的召回品質絕不退化。

| 測試 ID | 問題場景 | 預期召回條款 | 成功標準 |
|---|---|---|---|
| REG-q1 | ISMS 範圍界定 | `clause_4.3` / `clause_4.1` / `clause_4.2` | Hit Rate = 1 |
| REG-q2 | 資訊安全風險評鑑 | `clause_6.1.2` | Hit Rate = 1 |
| REG-q3 | 管理階層領導力與承諾 | `clause_5.1` | Hit Rate = 1 |
| REG-q4 | 威脅情資之蒐集與分析 | `control_5.7` | Hit Rate = 1 |
| REG-q5 | 智慧財產權與合規性保護 | `control_5.32` | Hit Rate = 1 |
| REG-q6 | 內部稽核計畫之執行 | `clause_9.2.2` / `clause_9.2` | Hit Rate = 1 |
| REG-q7 | 資訊系統備份控制 | `control_8.13` | Hit Rate = 1 |
| REG-q8 | 桌面與螢幕淨空政策 | `control_7.7` | Hit Rate = 1 |
| REG-q9 | 管理審查會議 | `clause_9.3.2` / `clause_9.3` | Hit Rate = 1 |
| REG-q10 ⭐| 敏感性個資防護與防洩漏 | `control_8.11` 與 `control_8.12` | Recall@4 >= 67% (XPASS/同時檢索出遮蔽與DLP) |

### 3.4 `test_cli.py` — CLI 與提示詞截斷防護測試 (16 項)

| 測試 ID | 測試目標 | 說明與邊界條件 | 預期結果 |
|---|---|---|---|
| BP-01 | 字元截斷防護 | 單一條文 content 超過 `max_chars_per_item=600` 時 | 正確執行截斷，並補上 `...[已截斷]` 標記 |
| BP-02 | 短條文處理 | 條文 content 小於 600 字元 | 原樣保留，不進行截斷或增加標記 |
| BP-03 ~ 05 | 提示詞參數 | 自訂 limit 大小、多筆條文組裝與 Prompt 問句檢索 | 組裝後的提示詞 (Prompt) 完整包含問句與檢索條文資訊 |
| CLI-01 ~ 05 | CLI 整合與環境 | 幫助指令、錯誤引數、無 API Key 偵測、SKIP_DOTENV 環境變數 | exit code 符合預期，在無 API key 且未執行 Ollama 時正確報錯 |

---

## 4. 測試指令 (Test Commands)

```bash
# 執行全部測試 (80 項)
python -m pytest tests/ -v --tb=short

# 只執行搜尋引擎測試
python -m pytest tests/test_search_tool.py -v

# 只執行指標與 Schema 評估測試
python -m pytest tests/test_evaluation.py -v

# 只執行回歸測試 (Recall 防護)
python -m pytest tests/test_recall_regression.py -v
```

---

## 5. 品質控制閾 (Quality Gate)

在發布或完成新一輪重構時，必須在測試中達成以下指標：

| 指標 | 閾值 | 說明 |
|---|---|---|
| pytest 單元測試通過率 | **100%** (80/80 通過) | 所有測試均無失敗 (含預期的 XPASS) |
| Hit Rate @ 4 | **100%** (10/10 題) | 回歸測試集中 10 題核心場景至少命中一個預期條文 |
| Avg Recall @ 4 | **>= 90%** (目前為 93.3%) | 回歸測試集中 10 題的平均召回率 |
| MRR @ 4 | **>= 0.90** (目前為 0.9333) | Mean Reciprocal Rank，表示最相關條文的排序權重 |
| 檢索速度 | **< 2.0 ms** (目前為 0.51 ms) | 單次 search 呼叫的平均耗時 |
| 提示詞截斷長度 | **<= 600 chars** | 每項 Context 項目最大字元數 |
