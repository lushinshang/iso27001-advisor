#!/usr/bin/env python3
"""
generate_faq.py - ISO 27001 FAQ 離線批次生成

兩階段流程（分階段執行，避免同時載入多個大型模型）：
  Stage 1 (Draft)  - draft_model (預設 gemma4:e4b-it-qat)：逐條草擬代表性問題
  Stage 2 (Refine) - refine_model (預設 gemma3:12b-16k)：RAG 流程生成高品質解答

輸出：faq_cache.json（含 iso_version、generated_at，供語意快取使用）
支援：--resume 中斷續跑、--limit 測試少量條文
"""
import json
import os
import re
import argparse
from datetime import datetime
from pathlib import Path

from iso27001_advisor.llm import call_ollama, build_prompt, get_system_prompt, load_dotenv
from iso27001_advisor.core.search_tool import ISO27001Searcher

_BASE = Path(__file__).resolve().parents[1]
CHECKPOINT_FILE = os.path.join(_BASE, "tmp", "faq_checkpoint.json")


def draft_questions(item, draft_model, host):
    """Stage 1：用輕量模型為單一條文草擬 1-2 個代表性問題。"""
    prompt = (
        f"【ISO 27001 條文】\n"
        f"編號：{item['id']}\n"
        f"名稱：{item['subsection']}\n"
        f"說明：{item['content']}\n\n"
        "請針對此條文，提出 1-2 個企業資安主管或合規經理最常詢問的實務問題。\n"
        "問題應具體可操作，直接從合規或稽核角度切入。\n"
        "格式（每行一個，不要額外解釋）：\n"
        "Q1: [問題]\n"
        "Q2: [問題]（若適合則提供，否則省略）"
    )
    system = "你是 ISO 27001 問題設計助理。請提出實務性的合規問題，避免過於抽象的問題。僅輸出問題，不要加說明。"
    response = call_ollama(prompt, system, model=draft_model, host=host)
    questions = []
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("Q1:") or line.startswith("Q2:"):
            q = line.split(":", 1)[1].strip()
            if q and len(q) > 5:
                questions.append(q)
    return questions


def generate_answer(question, searcher, refine_model, host):
    """Stage 2：走正常 RAG 流程，用重量模型生成完整解答。"""
    matched = searcher.search(question, limit=4)
    if not matched:
        return None, []
    prompt = build_prompt(question, matched)
    answer = call_ollama(prompt, get_system_prompt(), model=refine_model, host=host)
    clause_ids = [r["item"]["id"] for r in matched]
    return answer, clause_ids


_KNOWN_TERMS = [
    "備份", "加密", "存取控制", "身分管理", "脆弱性", "漏洞", "惡意軟體", "防毒",
    "日誌", "存錄", "稽核", "風險評鑑", "風險評估", "適用性聲明", "SoA",
    "資訊安全政策", "職務區隔", "變更管理", "事件回應", "業務持續", "BCP",
    "供應商", "第三方", "實體安全", "密碼", "憑證", "個資", "隱私", "PII",
    "資料遮罩", "資料分類", "資產管理", "人員安全", "資訊安全目標",
    "管理審查", "內部稽核", "矯正措施", "不符合事項", "持續改善",
]

def extract_keywords(text, max_kw=5):
    """從問題文字中提取 ISO 27001 相關關鍵詞，用於語意快取的第二層過濾。"""
    keywords = []
    text_lower = text.lower()
    for term in _KNOWN_TERMS:
        if term.lower() in text_lower and term not in keywords:
            keywords.append(term)
        if len(keywords) >= max_kw:
            break
    # 補充控制項 ID（如 A.8.13）
    ids = re.findall(r'[A-Z]\.\d+(?:\.\d+)?', text)
    for i in ids:
        if i not in keywords:
            keywords.append(i)
    return keywords[:max_kw]


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"processed_ids": [], "items": []}


def save_checkpoint(cp):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="ISO 27001 FAQ 離線批次生成")
    parser.add_argument("--draft-model", default="gemma4:e4b-it-qat",
                        help="Stage 1 草擬問題用模型（輕量），預設 gemma4:e4b-it-qat")
    parser.add_argument("--refine-model", default="gemma3:12b-16k",
                        help="Stage 2 生成解答用模型（重量），預設 gemma3:12b-16k")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama API 位址")
    parser.add_argument("--output", default=os.path.join(_BASE, "tmp", "faq_cache.json"),
                        help="輸出 FAQ JSON 路徑，預設 tmp/faq_cache.json")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制處理筆數（0=全部；測試時可設為 5）")
    parser.add_argument("--resume", action="store_true",
                        help="從 checkpoint 續跑（中斷後繼續）")
    parser.add_argument("--only-controls", action="store_true",
                        help="只處理 Annex A 控制措施，略過 Clause 4-10")
    args = parser.parse_args()

    searcher = ISO27001Searcher()

    # 載入條文資料，篩選有實質內容的子條文
    base_dir = str(_BASE)
    with open(os.path.join(base_dir, "data", "iso27001_structure.json"), encoding="utf-8") as f:
        all_items = json.load(f)

    candidates = [
        i for i in all_items
        if i["content"].strip()
        and "_" in i["id"]
        and "." in i["id"].split("_")[1]   # 排除大章節 header（如 clause_4, control_5）
        and (not args.only_controls or i["type"] == "control")
    ]

    if args.limit > 0:
        candidates = candidates[:args.limit]

    # 載入或初始化 checkpoint
    cp = load_checkpoint() if args.resume else {"processed_ids": [], "items": []}
    processed_ids = set(cp["processed_ids"])
    faq_items = cp["items"]
    remaining = [i for i in candidates if i["id"] not in processed_ids]

    print(f"📋 候選條文：{len(candidates)} 筆  |  已完成：{len(processed_ids)} 筆  |  待處理：{len(remaining)} 筆")
    print(f"🤖 Stage 1（草擬）：{args.draft_model}")
    print(f"🤖 Stage 2（解答）：{args.refine_model}")
    print("=" * 60)

    faq_counter = len(faq_items) + 1

    for idx, item in enumerate(remaining, 1):
        print(f"\n[{idx}/{len(remaining)}] {item['id']}  {item['subsection']}")

        try:
            # Stage 1：草擬問題
            print(f"  ⚙️  Stage 1 草擬中...")
            questions = draft_questions(item, args.draft_model, args.host)

            if not questions:
                print("  ⚠️  未能生成問題，跳過")
                cp["processed_ids"].append(item["id"])
                save_checkpoint(cp)
                continue

            for q in questions:
                print(f"  ❓ {q}")

            # Stage 2：為每個問題生成解答
            print(f"  ⚙️  Stage 2 生成解答中...")
            for q in questions:
                answer, clause_ids = generate_answer(q, searcher, args.refine_model, args.host)
                if not answer:
                    print(f"  ⚠️  「{q[:30]}...」無法生成解答，跳過")
                    continue
                entry = {
                    "id": f"faq_{faq_counter:04d}",
                    "question": q,
                    "answer": answer,
                    "clause_ids": clause_ids,
                    "keywords": extract_keywords(q),
                    "source_clause": item["id"]
                }
                faq_items.append(entry)
                faq_counter += 1
                print(f"  ✅ {entry['id']} 已生成")

        except KeyboardInterrupt:
            print("\n⏸️  使用者中斷。已儲存 checkpoint，可用 --resume 繼續。")
            cp["processed_ids"].append(item["id"])
            cp["items"] = faq_items
            save_checkpoint(cp)
            sys.exit(0)
        except Exception as e:
            print(f"  ❌ 處理失敗：{e}")

        # 每條完成後立即存 checkpoint
        cp["processed_ids"].append(item["id"])
        cp["items"] = faq_items
        save_checkpoint(cp)

    # 輸出最終 faq_cache.json
    output_data = {
        "iso_version": "27001:2022",
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "draft_model": args.draft_model,
        "refine_model": args.refine_model,
        "total": len(faq_items),
        "items": faq_items
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！共生成 {len(faq_items)} 條 FAQ → {args.output}")

    # 清除 checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("🗑️  checkpoint 已清除")


if __name__ == "__main__":
    main()
