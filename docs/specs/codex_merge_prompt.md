# Codex CLI 提示詞：v4.2 收尾（選項 A 合併執行）

> 用法（專案根目錄，現已是 git repo，不需 --skip-git-repo-check）：
>
> ```bash
> codex exec -s workspace-write "$(cat docs/specs/codex_merge_prompt.md)"
> ```

---

你是本專案（ISO 27001 Advisor，Python src layout）的實作工程師，接手收尾。
**權威規格：`docs/specs/kg_hybrid_search_sdd.md`（v1.4），先完整閱讀,
特別是 §10.6（判定依據）與 §10.7（你的工作清單）。**

## 現況摘要（前手已完成，皆已驗證並 commit）

- Phase 0-8 + 任務 A-D 全部完成，最新 commit 92be941，pytest 全綠（226+ tests）。
- 擁有者已追認**選項 A：合併**——gated 信心閘門模式（keyword top-1 ≥ 100 走純
  keyword，否則走 full RRF+KG）在改寫題考場四指標全面提升，正式採用。
- 已存在且不要重建：`data/knowledge_graph.json`（125 邊）、
  `data/clause_embeddings.json`、`data/eval_dataset_paraphrase.json`、
  `HybridSearcher`（含 gated 模式）、`eval/evaluation.py` 消融開關。
- LLM 提名產線封存中（SDD §9.3），**不要碰它**。

## 絕對規則（違反即停止）

1. SDD v1.4 為唯一權威；歧義時停下列出問題，不猜測。
2. TDD：先寫測試看紅，再實作到綠，每步跑全套 `python3 -m pytest -q`。
3. 全程離線：只允許 `http://localhost:11434`，禁裝新套件。
4. 不碰：`search_tool.py` 檢索邏輯、LV2/LV3 tools、`app.py`/`main.py`/`agent.py`
   （接線是 v4.3 的事，SDD §2）、LLM 提名產線相關程式碼。
5. 驗證誠實：沒跑過不准報過；門檻 100、rrf_k=60、kg_damp=0.5 不得調整。
6. 繁體中文（台灣用語）註解與訊息，遵循既有慣例。
7. 每完成一個任務即本地 `git commit`（不設遠端、不 push）。

## 任務（依序）

### 任務 1：gated 設為預設
TDD 修改 `HybridSearcher.search()` 預設走 gated 模式；`mode="keyword"` /
`mode="full"` 保留為顯式參數。既有呼叫端行為不受影響（目前無生產呼叫端）。

### 任務 2：雙資料集回歸護欄
新增回歸測試（可用小型 fixture 或標記 slow 的整合測試，遵循
`tests/test_recall_regression.py` 既有慣例）：
- 原 60 題：gated Hit Rate ≥ 98.3%
- 改寫 60 題：gated Hit Rate ≥ 76.7%
（實測值為下限；測試需可在無 Ollama 時 skip 而非 fail，遵循離線退化慣例）

### 任務 3：README 更新
`readme.md`：
a. 「評估指標」區改為雙軌實測表（原題/改寫題 × keyword/gated 四指標），
   附註：舊 Recall 93.3% / MRR 0.9333 為早期 10 題基準集數字，已過期作廢。
b. 「🚧 進行中：v4.2」區段改為「✅ v4.2 完成」，補充最終結果摘要
   （信心閘門、pdca-KG 125 邊、改寫題評估集、LLM 產線封存）。
c. 版本演進表：v4.2 列改為完成（2026-07-04），摘要含：消融實驗、信心閘門、
   改寫題揭露過擬合（100%→71.7%）、gated 改寫考場 +5.0pp。
d. 目錄結構：「⚠️ 缺失，v4.2 重建」標記移除，改為實際檔名與說明
   （knowledge_graph.json / clause_embeddings.json / build_embeddings.py /
   build_knowledge_graph.py / eval_nominator.py / generate_paraphrase_eval.py /
   eval_dataset_paraphrase.json）。
e. 能力分層表：LV5 的 Evaluation Flywheel 可標註「部分達成 ✅（檢索層）」。

### 任務 4：最終驗證與回報
- `python3 -m pytest -q` 全綠
- `git log --oneline` 確認各任務 commit
- 回報：最終測試總數、README 主要變更摘要、
  未解決問題清單（若有）——v4.2 至此完成。
