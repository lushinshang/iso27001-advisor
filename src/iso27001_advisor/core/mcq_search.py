"""MCQ 選項分解檢索協調器。"""

import re


_OPTION_MARKER_RE = re.compile(r"(?<![A-Za-z0-9])(?:\()?([A-Z])[\.)）]\s*")


def split_mcq_options(query: str) -> dict:
    """將選擇題拆成題幹與選項 dict。

    支援 `(A)`、`A.`、`A）` 與既有 `A)` 格式。
    """
    markers = list(_OPTION_MARKER_RE.finditer(query or ""))
    if not markers:
        return {"stem": (query or "").strip(), "options": {}}

    stem = query[: markers[0].start()].strip()
    options = {}
    for index, marker in enumerate(markers):
        label = marker.group(1)
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(query)
        text = query[start:end].strip()
        if text:
            options[label] = text

    return {"stem": stem, "options": options}


def mcq_union_search(searcher, query: str, limit: int = 4, per_option: int = 2) -> list:
    """題幹與各選項分別檢索後聯集去重，同 ID 保留最高分並重排。"""
    parsed = split_mcq_options(query)
    parts = [(parsed["stem"], limit)]
    parts.extend((option_text, per_option) for option_text in parsed["options"].values())

    by_id = {}
    for part_query, part_limit in parts:
        if not part_query:
            continue
        for result in searcher.search(part_query, limit=part_limit):
            item_id = result.get("item", {}).get("id")
            if not item_id:
                continue
            current = by_id.get(item_id)
            if current is None or result.get("score", 0) > current.get("score", 0):
                by_id[item_id] = result

    return sorted(by_id.values(), key=lambda result: result.get("score", 0), reverse=True)
