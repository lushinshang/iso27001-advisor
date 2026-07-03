#!/usr/bin/env python3
"""
semantic_cache.py - ISO 27001 語意快取

流程：
  1. build_index()：批次嵌入所有 FAQ 問題 → 存入 faq_index.json
  2. search(query)：嵌入查詢 → 餘弦相似度 → 雙重過濾 → 命中回傳 / 未命中回 None

E5-instruct 正確用法：
  Query 端：Instruct: ...\nQuery: {question}
  Document 端（FAQ 問題）：不加任何 prefix
"""
import json
import os
import math
import urllib.request
import urllib.error
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

_BASE = Path(__file__).resolve().parents[3]
FAQ_PATH    = os.path.join(_BASE, "tmp", "faq_cache.json")
INDEX_PATH  = os.path.join(_BASE, "tmp", "faq_index.json")
EMBED_MODEL = "jeffh/intfloat-multilingual-e5-large-instruct:f16"
OLLAMA_HOST = "http://localhost:11434"

# E5-instruct 官方 query prefix
_QUERY_INSTRUCTION = (
    "Instruct: Given an ISO 27001 compliance question, "
    "retrieve the relevant control clauses\nQuery: "
)


def cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_embedding(text: str, model: str, host: str) -> list:
    """呼叫 Ollama /api/embeddings 取得向量。"""
    url = f"{host}/api/embeddings"
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["embedding"]


class SemanticCache:
    def __init__(
        self,
        faq_path: str = FAQ_PATH,
        index_path: str = INDEX_PATH,
        embed_model: str = EMBED_MODEL,
        host: str = OLLAMA_HOST,
        threshold: float = 0.92,
    ):
        self.faq_path   = faq_path
        self.index_path = index_path
        self.embed_model = embed_model
        self.host       = host
        self.threshold  = threshold
        self._index     = []   # list of {faq_id, question, answer, clause_ids, keywords, embedding}
        self._ready     = False
        self._load()

    def _load(self):
        """載入預建索引（若存在且與 FAQ 同步）。"""
        if not os.path.exists(self.faq_path):
            return
        if not os.path.exists(self.index_path):
            return
        with open(self.faq_path, encoding="utf-8") as f:
            faq = json.load(f)
        with open(self.index_path, encoding="utf-8") as f:
            idx = json.load(f)
        # 檢查索引是否與 FAQ 同步（generated_at 一致）
        if idx.get("faq_generated_at") != faq.get("generated_at"):
            print("⚠️  [SemanticCache] 索引與 FAQ 版本不符，請重新執行 build_index()", file=sys.stderr)
            return
        # 合併 FAQ 答案到索引項目
        faq_map = {item["id"]: item for item in faq.get("items", [])}
        self._index = []
        for entry in idx.get("items", []):
            faq_item = faq_map.get(entry["faq_id"])
            if faq_item:
                self._index.append({
                    "faq_id":    entry["faq_id"],
                    "question":  entry["question"],
                    "answer":    faq_item["answer"],
                    "clause_ids": faq_item.get("clause_ids", []),
                    "keywords":  faq_item.get("keywords", []),
                    "embedding": entry["embedding"],
                })
        self._ready = len(self._index) > 0
        if self._ready:
            print(f"✅ [SemanticCache] 已載入 {len(self._index)} 條 FAQ 索引", file=sys.stderr)

    @property
    def is_ready(self) -> bool:
        return self._ready

    def build_index(self):
        """批次嵌入所有 FAQ 問題，儲存至 faq_index.json。"""
        if not os.path.exists(self.faq_path):
            print(f"❌ 找不到 {self.faq_path}，請先執行 generate_faq.py", file=sys.stderr)
            return
        with open(self.faq_path, encoding="utf-8") as f:
            faq = json.load(f)

        items = faq.get("items", [])
        print(f"📋 共 {len(items)} 條 FAQ 待嵌入（模型：{self.embed_model}）")

        index_items = []
        for i, item in enumerate(items, 1):
            print(f"  [{i}/{len(items)}] {item['id']} 嵌入中...", end="\r", flush=True)
            try:
                # Document 端不加 prefix（E5-instruct 規範）
                emb = get_embedding(item["question"], self.embed_model, self.host)
                index_items.append({
                    "faq_id":    item["id"],
                    "question":  item["question"],
                    "embedding": emb,
                })
            except Exception as e:
                print(f"\n  ⚠️  {item['id']} 嵌入失敗：{e}")

        output = {
            "embed_model":       self.embed_model,
            "built_at":          datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "faq_generated_at":  faq.get("generated_at", ""),
            "total":             len(index_items),
            "items":             index_items,
        }
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False)

        print(f"\n✅ 索引完成，共 {len(index_items)} 條 → {self.index_path}")
        self._load()

    def search(self, query: str) -> Optional[dict]:
        """
        查詢語意快取。
        回傳命中的 FAQ item dict（含 question/answer/clause_ids），或 None（未命中）。

        雙重過濾：
          1. 餘弦相似度 >= threshold
          2. clause_ids 或 keywords 與查詢有交集
        """
        if not self._ready:
            return None

        # Query 端加 E5-instruct prefix
        query_emb = get_embedding(_QUERY_INSTRUCTION + query, self.embed_model, self.host)

        # 計算所有 FAQ 的相似度
        scored = []
        for entry in self._index:
            sim = cosine_similarity(query_emb, entry["embedding"])
            if sim >= self.threshold:
                scored.append((sim, entry))

        if not scored:
            return None

        # 依相似度排序，取最高分者做第二層過濾
        scored.sort(key=lambda x: x[0], reverse=True)
        query_lower = query.lower()

        for sim, entry in scored:
            # 第二層：keywords 或 clause_id 出現在查詢中
            keyword_hit = any(kw.lower() in query_lower for kw in entry["keywords"])
            id_hit = any(cid.replace("_", ".").lower() in query_lower
                         for cid in entry["clause_ids"])
            if keyword_hit or id_hit:
                return {
                    "hit":       True,
                    "similarity": round(sim, 4),
                    "faq_id":    entry["faq_id"],
                    "question":  entry["question"],
                    "answer":    entry["answer"],
                    "clause_ids": entry["clause_ids"],
                }

        # 相似度達標但第二層未通過 → 未命中（防止偽命中）
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="語意快取索引管理")
    parser.add_argument("--build", action="store_true", help="建立/重建嵌入索引")
    parser.add_argument("--test", type=str, metavar="QUERY", help="測試查詢（需已建立索引）")
    parser.add_argument("--threshold", type=float, default=0.92)
    parser.add_argument("--host", default=OLLAMA_HOST)
    parser.add_argument("--model", default=EMBED_MODEL)
    args = parser.parse_args()

    cache = SemanticCache(embed_model=args.model, host=args.host, threshold=args.threshold)

    if args.build:
        cache.build_index()

    if args.test:
        if not cache.is_ready:
            print("❌ 索引未建立，請先執行 --build")
        else:
            print(f"\n🔍 測試查詢：{args.test}")
            result = cache.search(args.test)
            if result:
                print(f"✅ 命中！相似度：{result['similarity']}")
                print(f"   FAQ：{result['faq_id']} - {result['question']}")
                print(f"   引用：{result['clause_ids']}")
            else:
                print("❌ 未命中（無需快取，走正常 RAG）")
