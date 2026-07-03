"""faithfulness_evaluation.py — Faithfulness 評估腳本。

評估流程：
  Step 1: 對 eval_dataset.json 每題問題執行 RAG，生成 LLM 答案。
  Step 2: Citation Faithfulness（程式解析）— 答案引用的 [A.X.X] 是否都在 retrieved context 中？
  Step 3: Content Faithfulness（LLM-as-Judge）— 答案的事實聲明是否由 context 支撐？

執行：
  python3 faithfulness_evaluation.py --model gemma4:e2b-mlx
  python3 faithfulness_evaluation.py --gemini             # 使用 Gemini 生成答案與評判
  python3 faithfulness_evaluation.py --load-answers       # 跳過生成，直接評估已存答案
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from iso27001_advisor.core.search_tool import ISO27001Searcher
from iso27001_advisor.llm import call_ollama, call_gemini, build_prompt, get_system_prompt, load_dotenv


# ── 路徑設定 ──────────────────────────────────────────────────
DATASET_PATH = os.path.join(_BASE, "data", "eval_dataset.json")
ANSWERS_PATH = os.path.join(_BASE, "data", "faithfulness_answers.json")
RESULTS_PATH = os.path.join(_BASE, "data", "faithfulness_results.json")


# ── Step 1: 生成 RAG 答案 ─────────────────────────────────────

def _save_answers_checkpoint(answers):
    """每題生成後即時落盤，避免長批次中斷時完全不可觀測。"""
    with open(ANSWERS_PATH, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=2)


def generate_answers(dataset, searcher, model, host, use_gemini, api_key, gemini_model, top_k=4):
    """對每題問題執行 RAG 並呼叫 LLM 生成答案。

    Returns:
        (answers, error_count)
    """
    answers = []
    error_count = 0
    total = len(dataset)
    for i, item in enumerate(dataset, 1):
        q_id = item["id"]
        question = item["question"]
        print(f"[{i}/{total}] 生成答案 {q_id}: {question[:40]}...", flush=True)

        results = searcher.search(question, limit=top_k)
        retrieved_ids = [r["item"]["id"] for r in results]
        retrieved_contents = {r["item"]["id"]: r["item"]["content"] for r in results}

        prompt = build_prompt(question, results)
        system = get_system_prompt()
        error = None

        try:
            if use_gemini:
                answer = call_gemini(prompt, system, api_key, model=gemini_model)
            else:
                answer = call_ollama(prompt, system, model=model, host=host)
        except TimeoutError as e:
            # 首次 timeout 通常是模型冷啟動，等待後重試一次
            print(f"  ⚠️  Timeout，30 秒後重試: {e}", file=sys.stderr, flush=True)
            time.sleep(30)
            try:
                answer = call_ollama(prompt, system, model=model, host=host)
            except Exception as retry_e:
                print(f"  ❌  重試仍失敗: {retry_e}", file=sys.stderr, flush=True)
                error = str(retry_e)
                answer = ""
        except Exception as e:
            print(f"  ⚠️  生成失敗: {e}", file=sys.stderr, flush=True)
            error = str(e)
            answer = ""

        if not answer.strip():
            error_count += 1
            if error is None:
                error = "empty answer"

        answers.append({
            "id": q_id,
            "question": question,
            "retrieved_ids": retrieved_ids,
            "retrieved_contents": retrieved_contents,
            "answer": answer,
            "generation_error": error,
        })
        _save_answers_checkpoint(answers)
        print(f"  ✅ 已寫入 checkpoint；答案長度: {len(answer.strip())}", flush=True)

    return answers, error_count


# ── Step 2: Citation Faithfulness（程式解析）────────────────────

# ISO 27001 引用格式：
#   [A.8.13 名稱]   — Annex A 控制項（系統提示詞要求格式）
#   [4.3 名稱]      — 主條文（LLM 實際輸出格式，無 A. 前綴）
#   clause_X.X / control_X.X — 內部 ID 格式
_CITATION_PATTERN = re.compile(
    r'\[A\.(\d+\.\d+(?:\.\d+)?)[^\]]*\]'          # [A.8.13 名稱]
    r'|(?:clause|control)_(\d+\.\d+(?:\.\d+)?)'   # clause_8.13 / control_8.13
    r'|\[(\d+\.\d+(?:\.\d+)?)[^\]]*\]',            # [4.3 名稱]（主條文無前綴格式）
    re.IGNORECASE
)

def _parse_cited_ids(answer_text, id_index):
    """從答案文字解析 [A.X.X] / clause_X.X / control_X.X 形式的引用。

    回傳 (matched_ids, unresolved_raws)：
        matched_ids     — 成功對照到知識庫的標準化 ID set
        unresolved_raws — 解析到但找不到對應知識庫條目的原始字串 set（幻覺候選）
    """
    matched = set()
    unresolved = set()
    for m in _CITATION_PATTERN.finditer(answer_text):
        raw = m.group(1) or m.group(2) or m.group(3)
        found = False
        for prefix in ("clause", "control"):
            candidate = f"{prefix}_{raw}"
            if candidate in id_index:
                matched.add(candidate)
                found = True
                break
        if not found:
            unresolved.add(raw)
    return matched, unresolved


def compute_citation_faithfulness(answer_text, retrieved_ids, id_index):
    """計算 Citation Faithfulness。

    Returns:
        dict:
            cited_ids           — 答案中成功對照到知識庫的條文 ID
            cited_hallucinated_raw — 引用但找不到對應知識庫條目的原始字串（幻覺）
            cited_in_retrieved  — 引用且在 retrieved context 中的 ID
            cited_out_of_context — 引用存在於知識庫但不在 retrieved context 中
            citation_score      — cited_in_retrieved / max(total_cited, 1)
    """
    cited, unresolved = _parse_cited_ids(answer_text, id_index)
    retrieved_set = set(retrieved_ids)

    cited_in_retrieved = cited & retrieved_set
    cited_out_of_ctx = cited - retrieved_set

    total_cited = len(cited) + len(unresolved)
    score = len(cited_in_retrieved) / max(total_cited, 1) if total_cited > 0 else None

    return {
        "cited_ids": sorted(cited),
        "cited_hallucinated_raw": sorted(unresolved),
        "cited_in_retrieved": sorted(cited_in_retrieved),
        "cited_out_of_context": sorted(cited_out_of_ctx),
        "citation_score": round(score, 4) if score is not None else None,
        "no_citations_found": total_cited == 0,
    }


# ── agy CLI Judge ─────────────────────────────────────────────

def call_agy(prompt):
    """呼叫 agy CLI 作為 LLM Judge，無 API rate limit 限制。"""
    result = subprocess.run(
        ["agy", "--print", prompt],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "agy 回傳非零 exit code")
    return result.stdout.strip()


# ── Step 3: Content Faithfulness（LLM-as-Judge）────────────────

def build_judge_prompt(question, context_text, answer_text):
    """組裝給 LLM Judge 的評估 Prompt。

    評分哲學：「寬鬆但可溯源」
    - 允許合理推論（不等於條文原文），但每個建議必須能追溯至控制目標或標準精神
    - 條文編號錯誤屬技術性失誤（扣分輕），觀念正確但完全無可溯源依據屬系統性風險（扣分重）
    - 與 context 明顯矛盾的聲明才重扣分

    三層評分權重：
        觀念正確性（70%）: 風險識別正確、控制措施方向適切
        邏輯可追溯性（20%）: 建議能連結到 context 的控制目標或標準精神
        條文準確性（10%）: 引用的條文編號與 context 相符
    """
    return f"""你是一位嚴格但公正的 ISO 27001 顧問答案評審員。請根據以下三層標準評估答案的忠實性。

## 評分標準（總分 1.0）

**A. 觀念正確性（權重 70%）**
- 1.0：風險識別正確，控制措施方向與 context 一致
- 0.7：合理推論，超出 context 但符合 ISO 27001 精神，無矛盾
- 0.0：觀念與 context 明顯矛盾（例如建議不加密敏感資料）

**B. 邏輯可追溯性（權重 20%）**
- 1.0：每個建議都能連結到 context 中某條文的控制目標或要求精神
- 0.5：部分建議有追溯依據，部分建議為無根據的自由發揮
- 0.0：建議完全無法追溯至 context 的任何條文或控制目標

**C. 條文準確性（權重 10%）**
- 1.0：引用的條文編號完全在 context 中
- 0.5：編號有誤但觀念正確（技術性失誤）
- 0.0：引用大量不存在或錯誤的條文編號

**⚠️ 重要：條文 ID 格式對應說明**
以下格式是同一個條文的不同表示方式，不得視為引用錯誤：
- `[A.5.7 威脅情資]` = `control_5.7`（Annex A 控制措施的 ISO 標準格式 vs 系統內部 ID）
- `[A.7.7 桌面淨空]` = `control_7.7`
- `[4.3 範圍]` = `clause_4.3`（主條文的常見格式 vs 系統內部 ID）
評估條文準確性時，以條文的語義對應為準，**不以 ID 前綴格式差異扣分**。

## 嚴重程度判斷
- 輕微（扣 10-20%）：條文編號錯誤，但觀念正確且可追溯
- 嚴重（扣 50-70%）：觀念看似正確，但完全無法追溯至任何條文依據
- 重大（扣 80-100%）：建議與 context 明顯矛盾，可能誤導客戶

---

## 待評估資料

【使用者問題】
{question}

【RAG 檢索到的 ISO 27001 條文 Context】
{context_text}

【待評估的顧問答案】
{answer_text}

---

## 輸出要求

請輸出以下 JSON，不要加任何額外文字：
{{
  "concept_score": 0.0到1.0,
  "traceability_score": 0.0到1.0,
  "citation_accuracy_score": 0.0到1.0,
  "faithfulness_score": 加權總分（concept*0.7 + traceability*0.2 + citation*0.1）,
  "unfaithful_claims": ["無法追溯或矛盾的具體聲明（若無則空陣列）"],
  "reasoning": "一句話說明最主要的扣分原因，若滿分則說明為何忠實"
}}"""


def evaluate_content_faithfulness(answer_item, model, host, use_gemini, api_key, gemini_model, id_index, use_agy=False):
    """呼叫 LLM judge 評估單題的 content faithfulness。"""
    context_parts = []
    for clause_id, content in answer_item["retrieved_contents"].items():
        context_parts.append(f"[{clause_id}]\n{content[:400]}")
    context_text = "\n\n".join(context_parts)

    try:
        judge_prompt = build_judge_prompt(
            answer_item["question"],
            context_text,
            answer_item["answer"],
        )
    except NotImplementedError as e:
        return {"error": str(e), "faithfulness_score": None}

    system = "你是一位嚴格且公正的 ISO 27001 答案忠實性評審員，只根據提供的評估規則輸出 JSON。"

    try:
        if use_agy:
            raw = call_agy(judge_prompt)
        elif use_gemini:
            raw = call_gemini(judge_prompt, system, api_key, model=gemini_model)
        else:
            raw = call_ollama(judge_prompt, system, model=model, host=host)
    except Exception as e:
        return {"error": str(e), "faithfulness_score": None}

    # 解析 LLM 輸出的 JSON
    try:
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"raw_output": raw, "faithfulness_score": None}


# ── 主流程 ────────────────────────────────────────────────────

def run_faithfulness_evaluation(args):
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")

    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    searcher = ISO27001Searcher()
    id_index = {item["id"] for item in searcher.items}

    # Step 1: 生成或載入答案
    if args.load_answers and os.path.exists(ANSWERS_PATH):
        print(f"📂 載入已存答案：{ANSWERS_PATH}", flush=True)
        with open(ANSWERS_PATH, encoding="utf-8") as f:
            answers = json.load(f)
        generation_error_count = sum(1 for item in answers if item.get("generation_error"))
    else:
        print(f"\n{'='*52}", flush=True)
        print(f"🤖 Step 1: 生成 RAG 答案（模型：{args.model}）", flush=True)
        print(f"{'='*52}", flush=True)
        answers, generation_error_count = generate_answers(
            dataset, searcher,
            model=args.model, host=args.host,
            use_gemini=args.gemini, api_key=api_key,
            gemini_model=args.gemini_model, top_k=args.top_k,
        )
        print(f"✅ 答案已儲存：{ANSWERS_PATH}\n", flush=True)
        if generation_error_count:
            print(f"❌ 生成階段有 {generation_error_count} 題空答案或錯誤，停止評估。", file=sys.stderr, flush=True)
            sys.exit(1)

    # Step 2 & 3: 評估
    judge_label = "agy CLI" if args.agy else ("Gemini" if args.gemini else "Ollama")
    print(f"\n{'='*52}", flush=True)
    print("📊 Step 2: Citation Faithfulness（程式解析）", flush=True)
    if not args.skip_content:
        print(f"🧑‍⚖️  Step 3: Content Faithfulness（Judge: {judge_label}）", flush=True)
    print(f"{'='*52}\n", flush=True)

    results = []
    sum_citation = 0.0
    sum_content = 0.0
    content_count = 0

    for item in answers:
        q_id = item["id"]
        print(f"[{q_id}] {item['question'][:50]}...", flush=True)

        # 空答案直接判 0 分，計入分母（不排除，不能讓分子縮水）
        if not item["answer"].strip():
            print(f"  ⚠️  答案為空，Citation 與 Content Faithfulness 判定為 0.0", flush=True)
            empty_citation = {
                "cited_ids": [], "cited_hallucinated_raw": [],
                "cited_in_retrieved": [], "cited_out_of_context": [],
                "citation_score": 0.0, "no_citations_found": True, "empty_answer": True,
            }
            empty_content = {"faithfulness_score": 0.0, "reasoning": "答案為空，LLM 未生成有效回答"}
            sum_citation += 0.0
            sum_content += 0.0
            content_count += 1
            print(flush=True)
            results.append({
                "id": q_id, "question": item["question"],
                "retrieved_ids": item["retrieved_ids"], "answer_preview": "",
                "citation_faithfulness": empty_citation, "content_faithfulness": empty_content,
            })
            continue

        citation = compute_citation_faithfulness(item["answer"], item["retrieved_ids"], id_index)

        content = {}
        if not args.skip_content:
            content = evaluate_content_faithfulness(
                item, args.model, args.host, args.gemini, api_key, args.gemini_model, id_index,
                use_agy=args.agy,
            )
            # agy 無 rate limit，不需 sleep
            # gemini-3.1-flash-lite: RPM=15, RPD=500；gemini-2.5-flash: RPM=5, RPD=20
            if args.gemini and not args.agy and content.get("faithfulness_score") is not None:
                rpm_limit = 15 if "3.1" in args.gemini_model or "3-" in args.gemini_model else 5
                sleep_sec = 5 if rpm_limit >= 15 else 15
                time.sleep(sleep_sec)

        # 顯示結果
        cs = citation["citation_score"]
        if citation["no_citations_found"]:
            print(f"  Citation: ⚠️  答案未包含任何條文引用", flush=True)
        else:
            print(f"  Citation score: {cs:.2f}  引用: {citation['cited_ids']}", flush=True)
            if citation["cited_hallucinated_raw"]:
                print(f"  ❌ 幻覺 ID: {citation['cited_hallucinated_raw']}", flush=True)
            if citation["cited_out_of_context"]:
                print(f"  ⚠️  超出 context: {citation['cited_out_of_context']}", flush=True)

        if content.get("faithfulness_score") is not None:
            fs = content["faithfulness_score"]
            c_score = content.get("concept_score", "?")
            t_score = content.get("traceability_score", "?")
            a_score = content.get("citation_accuracy_score", "?")
            print(f"  Content score: {fs:.2f}  [觀念={c_score} 可溯={t_score} 編號={a_score}]", flush=True)
            print(f"  理由: {content.get('reasoning','')[:80]}", flush=True)
            if content.get("unfaithful_claims"):
                for claim in content["unfaithful_claims"][:2]:
                    print(f"  ⚠️  {claim[:70]}", flush=True)
            sum_content += fs
            content_count += 1
        elif content.get("error"):
            print(f"  ⚠️  Content 評估失敗（API 錯誤，不計入平均）: {str(content.get('error',''))[:80]}", flush=True)

        if cs is not None:
            sum_citation += cs

        print(flush=True)
        results.append({
            "id": q_id,
            "question": item["question"],
            "retrieved_ids": item["retrieved_ids"],
            "answer_preview": item["answer"][:200],
            "citation_faithfulness": citation,
            "content_faithfulness": content,
        })

    # 彙總
    valid_citation = [r for r in results if r["citation_faithfulness"]["citation_score"] is not None]
    avg_citation = sum_citation / len(valid_citation) if valid_citation else None
    avg_content = sum_content / content_count if content_count else None

    content_details = [r["content_faithfulness"] for r in results if r["content_faithfulness"].get("faithfulness_score") is not None]
    avg_concept = sum(d.get("concept_score", 0) for d in content_details) / max(len(content_details), 1) if content_details else None
    avg_trace = sum(d.get("traceability_score", 0) for d in content_details) / max(len(content_details), 1) if content_details else None
    avg_accuracy = sum(d.get("citation_accuracy_score", 0) for d in content_details) / max(len(content_details), 1) if content_details else None

    print(f"\n{'='*52}", flush=True)
    print("📈 Faithfulness 評估總結", flush=True)
    print(f"{'='*52}", flush=True)
    print(f"題數: {len(results)}", flush=True)
    empty_count = sum(1 for r in results if r.get("citation_faithfulness", {}).get("empty_answer"))
    error_count = sum(1 for r in results if r.get("content_faithfulness", {}).get("error"))
    if empty_count:
        print(f"⚠️  空答案題數: {empty_count}（計入分母，分數 = 0.0）", flush=True)
    if error_count:
        print(f"⚠️  API 錯誤題數: {error_count}（不計入 Content 平均）", flush=True)
    print(f"有效 Content 評估題數: {content_count}/{len(results)}", flush=True)
    if avg_citation is not None:
        print(f"Avg Citation Faithfulness:  {avg_citation:.4f}  ({avg_citation*100:.1f}%)", flush=True)
    if avg_content is not None:
        print(f"Avg Content Faithfulness:   {avg_content:.4f}  ({avg_content*100:.1f}%)", flush=True)
        print(f"  ├─ 觀念正確性（70%）:  {avg_concept:.4f}", flush=True)
        print(f"  ├─ 邏輯可追溯性（20%）: {avg_trace:.4f}", flush=True)
        print(f"  └─ 條文準確性（10%）:  {avg_accuracy:.4f}", flush=True)

    summary = {
        "model": args.model,
        "top_k": args.top_k,
        "avg_citation_faithfulness": round(avg_citation, 4) if avg_citation is not None else None,
        "avg_content_faithfulness": round(avg_content, 4) if avg_content is not None else None,
        "avg_concept_score": round(avg_concept, 4) if avg_concept is not None else None,
        "avg_traceability_score": round(avg_trace, 4) if avg_trace is not None else None,
        "avg_citation_accuracy_score": round(avg_accuracy, 4) if avg_accuracy is not None else None,
        "details": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n詳細報告已儲存至：{RESULTS_PATH}", flush=True)
    if empty_count:
        print(f"❌ 偵測到 {empty_count} 題空答案，驗證失敗。", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ISO 27001 Faithfulness 評估")
    parser.add_argument("--model", default="gemma4:e2b-mlx", help="Ollama 模型")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama API 位址")
    parser.add_argument("--gemini", action="store_true", help="使用 Gemini API")
    # gemini-2.5-flash free tier: RPM=5, RPD=20（容易超限）
    # gemini-3.1-flash-lite free tier: RPM=15, RPD=500（Judge 首選）
    parser.add_argument("--gemini-model", default="gemini-3.1-flash-lite", help="Gemini 模型")
    parser.add_argument("--top-k", type=int, default=4, help="RAG top-k")
    parser.add_argument("--load-answers", action="store_true", help="跳過生成，載入已存答案")
    parser.add_argument("--agy", action="store_true", help="使用 agy CLI 作為 LLM Judge（無 rate limit）")
    parser.add_argument("--skip-content", action="store_true", help="只跑 Citation，跳過 LLM Judge")
    args = parser.parse_args()

    run_faithfulness_evaluation(args)
