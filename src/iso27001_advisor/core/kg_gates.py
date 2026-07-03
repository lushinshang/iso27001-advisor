"""Knowledge Graph 建置關卡。

所有函數保持純函數，供建置產線、評測與測試共同使用。
"""

import math
import re


def _compact(text):
    return re.sub(r"\s+", "", text or "")


def _suffix(item_id):
    return item_id.split("_", 1)[1] if "_" in item_id else item_id


def _is_parent_child(left_id, right_id):
    left = _suffix(left_id)
    right = _suffix(right_id)
    return right.startswith(left + ".") or left.startswith(right + ".")


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def normalize_edge(edge):
    """將無向邊正規化為 from < to，避免重複儲存。"""
    from_id = edge["from"]
    to_id = edge["to"]
    if from_id <= to_id:
        return dict(edge)

    normalized = dict(edge)
    normalized["from"] = to_id
    normalized["to"] = from_id
    if "evidence_from" in edge or "evidence_to" in edge:
        normalized["evidence_from"] = edge.get("evidence_to", "")
        normalized["evidence_to"] = edge.get("evidence_from", "")
    return normalized


def gate_structure(edge, id_index):
    """G1：無自環、兩端存在，且不得為父子章節。"""
    from_id = edge.get("from")
    to_id = edge.get("to")
    if not from_id or not to_id:
        return False
    if from_id == to_id:
        return False
    if from_id not in id_index or to_id not in id_index:
        return False
    if _is_parent_child(from_id, to_id):
        return False
    return True


def gate_evidence(edge, id_index):
    """G2：兩端引文須為各自 title/content 子字串，去空白後長度至少 6 字。"""
    for side, evidence_key in (("from", "evidence_from"), ("to", "evidence_to")):
        item = id_index.get(edge.get(side))
        evidence = _compact(edge.get(evidence_key, ""))
        if item is None or len(evidence) < 6:
            return False
        haystack = _compact(item.get("title", "") + item.get("content", ""))
        if evidence not in haystack:
            return False
    return True


def _embedding_map(emb_index):
    if isinstance(emb_index, dict) and "items" in emb_index:
        return {item["id"]: item["embedding"] for item in emb_index.get("items", [])}
    return emb_index


def gate_similarity(edge, emb_index, floor=0.5):
    """G3：兩端節點既有向量 cosine 必須達到 floor。"""
    embeddings = _embedding_map(emb_index)
    from_emb = embeddings.get(edge.get("from"))
    to_emb = embeddings.get(edge.get("to"))
    if from_emb is None or to_emb is None:
        return False
    return cosine_similarity(from_emb, to_emb) >= floor


def gate_bidirectional(edge, all_nominations):
    """G4：A 曾提名 B 且 B 曾提名 A。"""
    from_id = edge.get("from")
    to_id = edge.get("to")
    forward = False
    backward = False
    for nomination in all_nominations:
        n_from = nomination.get("from")
        n_to = nomination.get("to")
        if n_from == from_id and n_to == to_id:
            forward = True
        if n_from == to_id and n_to == from_id:
            backward = True
    return forward and backward


def apply_degree_cap(edges, cap=6):
    """依 similarity 由高到低保留，確保每個節點 degree 不超過 cap。"""
    degrees = {}
    kept = []
    sorted_edges = sorted(edges, key=lambda edge: edge.get("similarity", 0.0), reverse=True)
    for edge in sorted_edges:
        from_id = edge["from"]
        to_id = edge["to"]
        if degrees.get(from_id, 0) >= cap or degrees.get(to_id, 0) >= cap:
            continue
        kept.append(edge)
        degrees[from_id] = degrees.get(from_id, 0) + 1
        degrees[to_id] = degrees.get(to_id, 0) + 1
    return kept
