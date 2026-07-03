# ISO 27001 Advisor Agent

離線版 ISO 27001 顧問助理。目前為 **v4.1 / src layout / demo-ready**。

## 快速啟動

```bash
# Web UI（推薦）
python3 app.py

# CLI 互動模式
python3 main.py

# CLI 單次查詢
python3 main.py "備份的稽核證據要準備什麼？"

# LV2 Agent（工具路由）
python3 agent.py
```

## 專案狀態

| 項目 | 狀態 |
|---|---|
| 主要入口 | `python3 app.py` |
| 預設後端 | Ollama 本地推理（`gemma4:e2b-mlx`） |
| Strict Offline | On（預設，不自動 fallback Gemini） |
| 測試 | **200 passed**（tests/ + eval/tests/） |
| LV3 評估 | ALL PASS / 7 項指標 100% |
| 規格文件 | `docs/specs/system_spec.html` |

## 能力分層

| 層級 | 狀態 | 代表能力 |
|---|---|---|
| LV1 | ✅ | RAG 條文問答 |
| LV2 | ✅ | Tool-based 顧問 Agent（qa / gap / evidence 自動路由） |
| LV2.5 | ✅ | Web Advisor（Strict Offline、回覆時間、agent logs） |
| LV3 | ✅ | 稽核準備交付物（SoA、稽核報告、問答包、30/60/90 計畫） |
| LV3 polish | ✅ | Demo-ready Web Advisor（Markdown 下載、badge、表格） |
| LV4 | ⏳ | Consultant Workspace（狀態管理、責任人、期限、證據連結） |
| LV5 | ⏳ | Multi-agent + Evaluation Flywheel |

## 🚧 進行中：v4.2 Hybrid Search + KG 自動把關產線（規劃完成，待實作）

> 2026-07-03 盤點發現：README v3.9 宣稱的 Hybrid Search（RRF）+ KG 1-hop
> 對應檔案（`knowledge_graph.json`、`embeddings.npy`、`build_embeddings.py`）
> **實際不存在於程式碼庫**，`search_tool.py` 為純關鍵字檢索。
> v4.2 目標為重建此能力，並升級為「程式自動把關」的建置產線。

**權威規格**：`docs/specs/kg_hybrid_search_sdd.md`（SDD + TDD 8 Phase 計畫）
**Codex CLI 提示詞**：`docs/specs/codex_kg_prompt.md`

### 設計決策記錄（2026-07-03 討論定案）

| 決策 | 結論 | 理由 |
|---|---|---|
| KG 建置品質把關 | 五道程式關卡，零人工審核 | 結構規則 → 引文字串比對（AI 編不出存在於原文的假引句）→ embedding 相似度地板 → 雙向互相提名 → 60 題評估回歸一票否決 |
| 提名模型 | **全地端**：gemma3:12b-16k + gemma4:e2b-mlx 雙提名器取聯集 | 品質下限由關卡保證、模型只影響產量（多輪提名免費補償）；未來機敏語料必須地端，現在就在目標條件下驗收架構（回推約束） |
| 融合演算法 | RRF（k=60） | 只比排名不比分數，免除跨檢索器分數正規化 |
| 提名器優劣評估 | 產線關卡通過率當評測儀：格式合格率 / 引文誠實率 / 存活邊產量 / 收斂輪數 + 黃金邊召回（cht.md 官方交叉引用）+ 期末考 | 通用 benchmark 測不出特化任務；決策規則預先寫死避免事後凹 |
| 資料流分級 | 建置期語料為公開 ISO 標準（🟢）；執行期 gap 分析輸入為公司文件（🔴 → Strict Offline 既有保護） | 「機敏資料不出地端、公開資料不設限」的精準政策 |
| 離線性 | 建置期與執行期 100% 離線（localhost Ollama）；離線退化：Ollama 不可用時自動退回純關鍵字檢索 | 延續 Strict Offline 核心約束 |

## 評估指標（top_k=4）

### 檢索評估

| 指標 | 數值 |
|---|---|
| Hit Rate @4 | **100.0%** |
| Avg Recall @4 | **93.3%** |
| Avg Precision @4 | **42.5%** |
| MRR @4 | **0.9333** |
| 單次檢索耗時 | **0.51 ms** |

### Faithfulness 評估（LLM-as-Judge）

| 指標 | 數值 |
|---|---|
| Citation Faithfulness | **91.8%** |
| Content Faithfulness | **98.9%** |
| 評估題數 | **60 題**（10 題基準 + 50 題擴充）|
| Judge | agy CLI |

## 架構

```
使用者問句
    │
    ▼
[Layer 0] 語意快取（semantic_cache.py）   ~2ms 命中
    └─ 未命中 ↓
[Layer 1] 混合檢索（search_tool.py）      Hybrid Search（關鍵字 + 向量 RRF）+ KG 1-hop
    ▼
[Layer 2] 推理引擎（main.py / agent.py）  一般 / Map-Reduce / Tool-routing
    ▼
[Layer 3] 合規推薦（recommendation.py）   PDCA 圖譜 → 2-3 推薦卡片
    ▼
回答 + 原文抽屜 + 推薦卡片
```

**Tools**：`iso_tools` / `gap_analysis_tools` / `evidence_tools` / `draft_tools`
**LV3 Tools**：`soa_tools` / `audit_report_tools` / `action_plan_tools` / `export_tools`

## 目錄結構

```
iso27001-advisor/
├── pyproject.toml               # 套件定義（src layout，pip install -e .）
├── app.py / main.py / agent.py  # 入口點
├── src/iso27001_advisor/        # 可安裝套件
│   ├── core/                    # search_tool / semantic_cache / recommendation
│   ├── llm/                     # call_ollama / call_gemini / build_prompt 等
│   └── tools/                   # LV2 + LV3 工具（8 個模組）
├── eval/                        # 評估套件
│   ├── evaluation.py            # Hit Rate / Recall / Precision / MRR
│   ├── faithfulness_evaluation.py
│   ├── level2_evaluation.py / level3_evaluation.py
│   └── tests/
├── scripts/                     # 維運工具
│   ├── parse_iso.py             # ISO 27001 條文解析
│   ├── generate_faq.py          # FAQ 批次生成
│   ├── build_embeddings.py      # ⚠️ 缺失，v4.2 重建（向量索引建立）
│   └── build_new_advisor.py     # 移植新領域用的 ETL 工具
├── index.html                   # Web Chat UI
├── data/                        # 知識庫與評估資料（版控）
│   ├── iso27001_structure.json  # 144 個條文節點
│   ├── pdca_graph.json          # PDCA 合規推薦圖譜
│   ├── knowledge_graph.json     # ⚠️ 缺失，v4.2 重建（條文關聯邊，KG 1-hop）
│   ├── clause_embeddings.json   # ⚠️ 缺失，v4.2 重建（Hybrid Search 向量索引）
│   ├── eval_dataset.json        # 60 題評估題目
│   └── faithfulness_*.json      # 評估答案與結果快取
├── tmp/                         # 暫存（.gitignore 排除）
├── docs/
│   ├── specs/
│   │   ├── system_spec.html     # 權威規格文件
│   │   ├── architecture.html    # 系統架構 / 流程 / 使用者旅程圖
│   │   ├── faithfulness_improvement_plan.html
│   │   └── refactor_plan.html
│   └── guides/
│       ├── porting_guide.html   # 移植新領域新手指南
│       └── user_manual.md
└── tests/                       # pytest 測試套件
```

## 評估指令

```bash
# 檢索評估
python3 eval/evaluation.py

# Faithfulness 評估（需 Ollama）
python3 eval/faithfulness_evaluation.py --model gemma4:e2b-mlx

# Faithfulness 評估（agy Judge，無 rate limit）
python3 eval/faithfulness_evaluation.py --load-answers --agy

# Faithfulness 評估（Gemini Judge）
python3 eval/faithfulness_evaluation.py --load-answers --gemini

# 測試套件（tests/ + eval/tests/）
python3 -m pytest -q
```

## 版本演進

| 版本 | 日期 | 主要變更 |
|---|---|---|
| v4.2（規劃） | 2026-07-03 | Hybrid Search + KG 重建計畫定案：盤點發現 v3.9 宣稱的 hybrid/KG 檔案缺失；設計 KG 五道自動把關產線（結構規則/引文驗證/相似度地板/雙向一致/評估回歸）；決策全地端雙提名器（gemma3+gemma4 聯集）；SDD+TDD 8 Phase 計畫與 Codex CLI 提示詞完成（`docs/specs/kg_hybrid_search_sdd.md`） |
| v1.0 | 2026-06-24 | 解析器、關鍵字檢索、Ollama+Gemini 雙後端 |
| v1.1 | 2026-06-24 | 同義詞擴充、Soul-Word，Hit Rate 100% |
| v1.2 | 2026-06-25 | O(1) 查找（0.51ms）、MRR@4、截斷防護 |
| v1.4 | 2026-06-26 | src layout 套件化（pyproject.toml）、消除 14 處 sys.path、eval/ scripts/ 分層 |
| v1.3 | 2026-06-26 | Faithfulness 評估、Precision@4、三層引用 System Prompt、目錄重整 |
| v2.x | 2026-06-24~25 | 深度分析 Map-Reduce、FAQ 快取、語意快取、合規推薦 |
| v2.1~v2.2 | 2026-06-25 | LV2 agent.py、4 個 tools、Web Advisor Strict Offline |
| v3.0~v3.2 | 2026-06-25 | LV3 稽核交付物（SoA、稽核報告、問答包、行動計畫） |
| v4.1 | 2026-06-29 | 多輪對話情境感知（Sliding Window 3 輪）；所有模式附帶 conversationHistory；否定詞偵測修正（還原測試/保存期限不再誤判）；200 tests passed |
| v4.0 | 2026-06-29 | Roadmap Context Passthrough：gap_result SSE event + context_gap_result 傳遞；roadmap 銜接第一次缺口分析，不重算 |
| v3.9 | 2026-06-26 | Hybrid Search（RRF）+ Knowledge Graph 1-hop + System Prompt 重構（per-claim 引用 + 消歧表 + 閉卷約束）+ 選擇題自動偵測（MCQ → 注入建議答案指令）；Content Faithfulness **98.9%** |
| v3.8 | 2026-06-26 | eval checkpoint 逐題寫入、生成失敗非零 exit、intent boost（離職/組態/雲端）；187 tests passed |
| v3.3~v3.7 | 2026-06-25~26 | LV3 Polish、done event、Markdown 下載、模型選單 |

> 完整規格見 [`docs/specs/system_spec.html`](docs/specs/system_spec.html)
