#!/usr/bin/env python3
"""將原有的 60 題評估集問句使用 gemma4:12b-it-qat-16k 進行改寫。"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = BASE_DIR / "data" / "eval_dataset.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "eval_dataset_paraphrase.json"
DEFAULT_MODEL = "gemma4:12b-it-qat-16k"
DEFAULT_HOST = "http://localhost:11434"


def has_overlap(original: str, paraphrased: str, min_len: int = 6) -> bool:
    """檢查 paraphrased 是否包含 original 中連續 >= min_len 的字元片段（忽略空白、標點符號與專有名詞/行業背景詞如 ISO 27001、ISMS、資訊安全、資安、控制措施）。"""
    ignored_patterns = [r"iso\s*27001", r"isms", r"資訊安全", r"資安", r"控制措施"]
    
    clean_orig = original.lower()
    clean_para = paraphrased.lower()
    
    for pat in ignored_patterns:
        clean_orig = re.sub(pat, "", clean_orig)
        clean_para = re.sub(pat, "", clean_para)
        
    # 清理字串，只保留中文、英文和數字
    clean_orig = "".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]+", clean_orig))
    clean_para = "".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]+", clean_para))
    
    if len(clean_orig) < min_len or len(clean_para) < min_len:
        return False
        
    for i in range(len(clean_orig) - min_len + 1):
        chunk = clean_orig[i : i + min_len]
        if chunk in clean_para:
            return True
    return False


def call_ollama_paraphraser(original_question: str, model: str, host: str) -> str:
    """呼叫本機 Ollama 將問句進行重寫。"""
    prompt = (
        "你是 ISO 27001 的專家。請將以下問句進行語意不變的重寫（改寫）。\n"
        "要求：\n"
        "1. 使用繁體中文（台灣用語），保持專業與自然的語調。\n"
        "2. 語意、情境與核心關切不變，但措辭、句型結構必須重新排列。\n"
        "3. 禁止照抄原問句中的連續 6 個字以上的片段。\n"
        "4. 請只輸出 JSON 物件，格式為：{\"paraphrased\": \"改寫後的問句\"}。\n\n"
        f"原問句：{original_question}"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.3},
    }
    url = f"{host}/api/generate"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        raw_response = data.get("response", "{}").strip()
        
    try:
        parsed = json.loads(raw_response)
        return parsed.get("paraphrased", "").strip()
    except json.JSONDecodeError:
        # 容忍 markdown code block 格式
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw_response, re.S | re.I)
        if fence_match:
            try:
                parsed = json.loads(fence_match.group(1).strip())
                return parsed.get("paraphrased", "").strip()
            except Exception:
                pass
        raise ValueError(f"無法解析 JSON 回應: {raw_response}")


def process_paraphrase(
    input_path=DEFAULT_INPUT_PATH,
    output_path=DEFAULT_OUTPUT_PATH,
    model=DEFAULT_MODEL,
    host=DEFAULT_HOST,
    sample=None,
):
    with open(input_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if sample is not None:
        dataset = dataset[:sample]

    new_dataset = []
    skipped_count = 0

    print(f"🚀 開始改寫評估集，共 {len(dataset)} 題...")
    for idx, item in enumerate(dataset, start=1):
        q_id = item["id"]
        original = item["question"]
        print(f"[{idx}/{len(dataset)}] 正在處理 {q_id}...")
        
        paraphrased = ""
        success = False
        
        for attempt in range(1, 5):  # 1次正常生成 + 最多 3 次重試 = 4 次嘗試
            try:
                paraphrased = call_ollama_paraphraser(original, model, host)
                # 驗證
                if not paraphrased:
                    print(f"  ⚠️  [嘗試 {attempt}] 生成內容為空，重試中...")
                    continue
                if has_overlap(original, paraphrased, min_len=6):
                    print(f"  ⚠️  [嘗試 {attempt}] 檢驗失敗（包含連續 >= 6 字重複片段），重試中...")
                    print(f"      - 生成: {paraphrased}")
                    continue
                
                success = True
                break
            except Exception as e:
                print(f"  ⚠️  [嘗試 {attempt}] Ollama 呼叫失敗: {e}，重試中...")
                time.sleep(1)

        if not success:
            print(f"  ❌ {q_id} 改寫失敗（重試已達上限），保留原題。")
            paraphrased = original
            skipped_count += 1
            skipped_status = True
        else:
            print(f"  ✅ {q_id} 改寫成功：")
            print(f"      - 原題: {original}")
            print(f"      - 改寫: {paraphrased}")
            skipped_status = False

        new_item = {
            "id": q_id,
            "category": item["category"],
            "original_question": original,
            "question": paraphrased,
            "expected_clauses": item["expected_clauses"],
            "skipped": skipped_status,
        }
        if "keywords" in item:
            new_item["keywords"] = item["keywords"]
            
        new_dataset.append(new_item)

    output_data = {
        "_meta": {
            "source": str(input_path),
            "model": model,
            "total_questions": len(dataset),
            "skipped_count": skipped_count,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "dataset": new_dataset,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print("\n🎉 改寫任務完成！")
    print(f"   總題數: {len(dataset)}")
    print(f"   跳過（失敗）題數: {skipped_count}")
    print(f"   結果已寫入: {output_path}")
    return output_data


def main():
    parser = argparse.ArgumentParser(description="使用 LLM 改寫評估問句")
    parser.add_argument("--input-path", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--sample", type=int, help="只測試前幾題")
    args = parser.parse_args()

    process_paraphrase(
        input_path=args.input_path,
        output_path=args.output_path,
        model=args.model,
        host=args.host,
        sample=args.sample,
    )


if __name__ == "__main__":
    main()
