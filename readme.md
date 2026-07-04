# ISO 27001 Advisor Agent

離線版 ISO 27001 顧問助理。目前為 **v4.4 / src layout / demo-ready**。

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
| 測試 | **252 passed**（tests/ + eval/tests/，含雙資料集 gated 回歸護欄與 MCQ 回歸保護） |
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
| LV5 | 部分達成 ✅ | Multi-agent + Evaluation Flywheel（檢索層） |

## ✅ v4.2 完成：Hybrid Search + KG 自動把關產線

> 2026-07-03 盤點發現：README v3.9 宣稱的 Hybrid Search（RRF）+ KG 1-hop
> 對應檔案（`knowledge_graph.json`、`embeddings.npy`、`build_embeddings.py`）
> **實際不存在於程式碼庫**，`search_tool.py` 為純關鍵字檢索。
> v4.2 已重建此能力，並以雙資料集回歸護欄完成合併判定。

**權威規格**：`docs/specs/kg_hybrid_search_sdd.md`（SDD + TDD 8 Phase 計畫）
**Codex CLI 提示詞**：`docs/specs/codex_kg_prompt.md`

### 最終結果摘要（2026-07-04）

- `HybridSearcher` 預設採用信心閘門：keyword top-1 分數 ≥ 100 走純 keyword，否則走完整 RRF + KG。
- `data/knowledge_graph.json` 已由 pdca 關聯圖直建，含 125 條條文關聯邊。
- `data/eval_dataset_paraphrase.json` 已建立改寫題評估集，揭露 keyword 規則對原題過擬合。
- LLM 提名產線保留但封存；重啟條件與句子編號選擇法見 SDD §9.3。
- **下一步（v4.3）**：`app.py` / `main.py` / `agent.py` 的一般問答仍走純關鍵字檢索（`ISO27001Searcher`），接線至 `HybridSearcher`（gated 預設）為獨立變更。

## ✅ v4.4 完成：MCQ 多選支援與選項分解檢索

> 起因：真實使用者以附錄 A 實體控制措施**多選題**（正解 A/C/D）實測，
> 系統只答 A 且編造 C/D 的排除理由。診斷出兩個疊加 bug：
> MCQ 指令硬編碼單選；干擾項（選項 B「遠端工作」）觸發 intent boost 霸榜檢索，
> 正解條文 7.2/7.13 完全未進 context。規格見 SDD §12。

- **三態 MCQ 偵測**（`_mcq_mode`）：無選項 / 單選 / 多選（「哪些」「複選」等訊號）；單選行為與指令一字不變
- **選項分解檢索**（`core/mcq_search.py`）：題幹＋各選項分別檢索後聯集去重——干擾項無法再污染 context，實測 7.2/7.13 精準進榜
- **回歸保護**：回報原題寫入單元測試，永久看守
- **e2e 實測**：原題重問 → 「✅ 建議答案：A、C、D」，各項附 7.x 條文真實引句
- 教訓：評估集無多選題，此缺陷從未被指標照到——**真實使用者是最好的評估集擴充來源**（MCQ 專屬評估集列入後續）

### 設計決策記錄

| 決策 | 結論 | 理由 |
|---|---|---|
| KG 建置品質把關 | 產線保留；v4.2 正式 KG 由 pdca_graph 直建 | LLM 引文抄寫可靠度不足，G2/G4 對人工整理邊不適用；以既有人工 PDCA 關聯作為正式 KG 來源 |
| 提名模型 | LLM 提名產線封存 | gemma4:12b-it-qat-16k 診斷優於 gemma3，但仍需句子編號選擇法後才能重啟 |
| 融合演算法 | RRF（k=60） | 只比排名不比分數，免除跨檢索器分數正規化 |
| 信心閘門 | keyword top-1 ≥ 100 走純 keyword，否則走 full（RRF + KG） | 保留高信心規則命中，讓低信心語意題交給向量與 KG；門檻預先固定，不依結果調整 |
| 合併判定 | 選項 A：合併 | 原題 Hit Rate 接受 98.3% 下限；改寫題 gated 四指標全面提升，Hit Rate +5.0pp |
| 資料流分級 | 建置期語料為公開 ISO 標準（🟢）；執行期 gap 分析輸入為公司文件（🔴 → Strict Offline 既有保護） | 「機敏資料不出地端、公開資料不設限」的精準政策 |
| 離線性 | 建置期與執行期 100% 離線（localhost Ollama）；離線退化：Ollama 不可用時自動退回純關鍵字檢索 | 延續 Strict Offline 核心約束 |

## 評估指標（top_k=4）

### 檢索評估（雙資料集實測）

| 考場 | 模式 | Hit Rate @4 | Avg Recall @4 | Avg Precision @4 | MRR @4 |
|---|---|---:|---:|---:|---:|
| 原 60 題 | keyword | **100.0%** | 79.7% | 37.1% | 0.8597 |
| 原 60 題 | gated | 98.3% | **80.2%** | **37.5%** | **0.8764** |
| 改寫 60 題 | keyword | 71.7% | 54.2% | 22.9% | 0.5931 |
| 改寫 60 題 | gated | **76.7%** | **58.1%** | **24.6%** | **0.6222** |

> 舊 README 的 Recall 93.3% / MRR 0.9333 為早期 10 題基準集數字，已過期作廢。

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
[Layer 1] 混合檢索（hybrid_search.py）    信心閘門：keyword top-1 ≥ 100 走純關鍵字（search_tool.py），
                                          否則 Hybrid（關鍵字 + 向量 RRF + KG 1-hop）
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
│   ├── core/                    # search_tool / hybrid_search（gated）/ kg_gates / mcq_search / semantic_cache / recommendation
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
│   ├── build_embeddings.py      # Hybrid Search 向量索引建立
│   ├── build_knowledge_graph.py # KG 建置產線（pdca 直建 + 封存 LLM 提名流程）
│   ├── eval_nominator.py        # LLM 提名器診斷評測
│   ├── generate_paraphrase_eval.py # 改寫題評估集生成
│   └── build_new_advisor.py     # 移植新領域用的 ETL 工具
├── index.html                   # Web Chat UI
├── data/                        # 知識庫與評估資料（版控）
│   ├── iso27001_structure.json  # 144 個條文節點
│   ├── pdca_graph.json          # PDCA 合規推薦圖譜
│   ├── knowledge_graph.json     # pdca-KG 條文關聯邊（125 邊，供 KG 1-hop）
│   ├── clause_embeddings.json   # Hybrid Search 向量索引
│   ├── eval_dataset.json        # 60 題評估題目
│   ├── eval_dataset_paraphrase.json # 60 題改寫評估題目
│   └── faithfulness_*.json      # 評估答案與結果快取
├── tmp/                         # 暫存（.gitignore 排除）
├── docs/
│   ├── specs/
│   │   ├── system_spec.html     # 權威規格文件（Spec v1.6 / System v4.2）
│   │   ├── architecture.html    # 系統架構 / 流程 / 使用者旅程圖（v4.2 信心閘門）
│   │   ├── kg_hybrid_search_sdd.md / .html  # v4.2/v4.4 SDD（完整決策軌跡，HTML 含資訊圖）
│   │   ├── codex_kg_prompt.md / antigravity_kg_prompt.md / codex_merge_prompt.md / codex_mcq_prompt.md  # 各階段執行代理提示詞
│   │   ├── faithfulness_improvement_plan.html  # 已歸檔（v3.9 完成）
│   │   └── refactor_plan.html   # 已歸檔（v1.4 src layout 完成）
│   └── guides/
│       ├── porting_guide.html   # 移植新領域新手指南
│       └── user_manual.md / .html  # 使用者手冊 v4.2（HTML 含資訊圖）
└── tests/                       # pytest 測試套件
```

## 評估指令

```bash
# 檢索評估（keyword 基準）
python3 eval/evaluation.py

# 檢索評估：消融/閘門模式（keyword / keyword+KG / keyword+RRF / full / gated）
python3 eval/evaluation.py --mode gated

# 檢索評估：改寫題考場
python3 eval/evaluation.py --mode gated --dataset-path data/eval_dataset_paraphrase.json

# 雙資料集回歸護欄（需 Ollama，不可達時自動 skip）
python3 -m pytest tests/test_gated_recall_regression.py -q

# 向量索引重建（129 節點 → data/clause_embeddings.json）
python3 scripts/build_embeddings.py

# KG 重建（pdca 直建，125 邊）
python3 scripts/build_knowledge_graph.py --from-pdca

# 改寫題評估集重生成（gemma4:12b-it-qat-16k）
python3 scripts/generate_paraphrase_eval.py

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
| v4.4（完成） | 2026-07-04 | MCQ 多選支援：三態偵測（無選項/單選/多選）＋選項分解聯集檢索（干擾項不再污染 context）；真實回報題（附錄 A 實體控制多選）e2e 修復並入回歸測試；252 tests passed |
| v4.2（完成） | 2026-07-04 | Hybrid Search + KG 收尾完成：消融實驗定位 RRF 稀釋高信心規則命中；信心閘門成為預設；pdca-KG 125 邊接入；改寫題揭露 keyword 原題過擬合（100%→71.7%）；gated 在改寫考場 Hit Rate +5.0pp 且四指標全面提升；雙資料集回歸護欄納入 pytest |
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
