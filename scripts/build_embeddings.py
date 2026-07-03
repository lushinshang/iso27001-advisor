#!/usr/bin/env python3
"""建立 ISO 27001 條文向量索引。"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from iso27001_advisor.core.semantic_cache import (  # noqa: E402
    EMBED_MODEL,
    OLLAMA_HOST,
    get_embedding,
)

DEFAULT_STRUCTURE_PATH = BASE_DIR / "data" / "iso27001_structure.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "clause_embeddings.json"


def _is_parent_section(item_id):
    if "_" not in item_id:
        return False
    suffix = item_id.split("_", 1)[1]
    return "." not in suffix


def _embedding_text(item):
    return "\n".join(
        [
            item.get("subsection", ""),
            item.get("title", ""),
            item.get("content", ""),
        ]
    )


def load_embedding_index(path=DEFAULT_OUTPUT_PATH):
    """載入向量索引，缺檔時提供明確錯誤訊息。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到向量索引：{path}，請先執行 scripts/build_embeddings.py")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_clause_embeddings(
    structure_path=DEFAULT_STRUCTURE_PATH,
    output_path=DEFAULT_OUTPUT_PATH,
    embed_model=EMBED_MODEL,
    host=OLLAMA_HOST,
    embedding_func=get_embedding,
):
    """建立排除父章節後的條文向量索引。"""
    structure_path = Path(structure_path)
    output_path = Path(output_path)
    if not structure_path.exists():
        raise FileNotFoundError(f"找不到 ISO 27001 結構檔：{structure_path}")

    with structure_path.open("r", encoding="utf-8") as f:
        source_items = json.load(f)

    index_items = []
    dimension = None
    for item in source_items:
        item_id = item.get("id", "")
        if _is_parent_section(item_id):
            continue

        emb = embedding_func(_embedding_text(item), embed_model, host)
        if dimension is None:
            dimension = len(emb)
        elif len(emb) != dimension:
            raise ValueError(
                f"向量維度不一致：{item_id} 維度 {len(emb)}，預期 {dimension}"
            )

        index_items.append({"id": item_id, "embedding": emb})

    output = {
        "embed_model": embed_model,
        "built_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source_file": str(structure_path),
        "dimension": dimension or 0,
        "items": index_items,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return output


def main():
    parser = argparse.ArgumentParser(description="建立 ISO 27001 條文向量索引")
    parser.add_argument("--structure-path", default=str(DEFAULT_STRUCTURE_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--model", default=EMBED_MODEL)
    parser.add_argument("--host", default=OLLAMA_HOST)
    args = parser.parse_args()

    index = build_clause_embeddings(
        structure_path=args.structure_path,
        output_path=args.output_path,
        embed_model=args.model,
        host=args.host,
    )
    print(f"✅ 向量索引完成：{len(index['items'])} 筆 → {args.output_path}")


if __name__ == "__main__":
    main()
