"""包裝 ISO27001Searcher，提供 agent 使用的 search_iso / get_clause 工具函式。

使用 lazy initialization 確保 _searcher 單例只在第一次呼叫時建立，
避免模組 import 時就載入資料造成不必要的啟動成本。
"""

from typing import Optional, List, Dict

from iso27001_advisor.core.search_tool import ISO27001Searcher

_searcher: Optional[ISO27001Searcher] = None


_INTENT_RULES = [
    {
        "ids": ["control_8.15"],
        "keywords": ["日誌", "存錄", "登入", "登出", "操作行為", "siem", "syslog", "稽核日誌", "異常登入"],
    },
    {
        "ids": ["control_8.8"],
        "keywords": ["弱點", "脆弱性", "漏洞", "patch", "修補", "安全性修補程式", "作業系統更新", "cve"],
    },
    {
        "ids": ["clause_9.2"],
        "keywords": ["稽核員", "稽核計畫", "稽核報告", "稽核委員會", "不得稽核自己"],
    },
    {
        "ids": ["control_5.24", "control_6.8"],
        "keywords": ["資安事件", "事件通報", "事故", "通報信箱", "異常可發信", "security@"],
    },
    {
        "ids": ["control_5.19", "control_5.20", "control_5.21", "control_5.22"],
        "keywords": ["供應商", "供應者", "廠商", "第三方", "外包", "採購合約", "保密條款", "供應商管理"],
    },
    {
        "ids": ["control_8.24"],
        "keywords": ["加密", "金鑰", "aes", "tls", "憑證", "密碼技術"],
    },
    {
        "ids": ["control_5.34"],
        "keywords": ["個資", "pii", "隱私", "個人資料", "個人資料保護"],
    },
    {
        "ids": ["control_6.7"],
        "keywords": ["遠端工作", "居家辦公", "vpn", "remote work"],
    },
    {
        "ids": ["control_6.3"],
        "keywords": ["教育訓練", "資安意識", "釣魚郵件", "訓練", "簽到"],
    },
    {
        "ids": ["control_7.2", "control_7.1"],
        "keywords": ["門禁", "訪客", "感應卡", "機房", "辦公室", "訪客登記"],
    },
    {
        "ids": ["control_5.15"],
        "keywords": ["存取控制", "帳號", "權限", "主管核准", "定期覆核", "特權帳號"],
    },
    {
        "ids": ["control_8.13"],
        "keywords": ["備份", "還原", "備份檔", "nas"],
    },
]

_PARENT_ALIASES = {
    "clause_9.2.1": "clause_9.2",
    "clause_9.2.2": "clause_9.2",
}


def _get_searcher() -> ISO27001Searcher:
    """Lazy initialization：第一次呼叫時建立單例。"""
    global _searcher
    if _searcher is None:
        _searcher = ISO27001Searcher()
    return _searcher


def search_iso(query: str, top_k: int = 4) -> List[Dict]:
    """搜尋 ISO 27001 條文。

    Args:
        query: 自然語言搜尋關鍵字。
        top_k: 最多回傳幾筆，預設 4。

    Returns:
        list of dict，每筆含 id, type, section, subsection, title, content, score。
        所有欄位均為 JSON serializable。
    """
    searcher = _get_searcher()
    raw_results = searcher.search(query, limit=max(top_k, top_k + 8))

    output = []
    seen = set()
    for hit in raw_results:
        item = hit.get("item", {})
        score = hit.get("score", 0.0)
        item_id = item.get("id", "")
        seen.add(item_id.lower())
        output.append({
            "id": item_id,
            "type": item.get("type", ""),
            "section": item.get("section", ""),
            "subsection": item.get("subsection", ""),
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "score": round(float(score), 4),
        })

    query_lower = query.lower()
    primary_boosted_ids: List[str] = []
    secondary_boosted_ids: List[str] = []
    for rule in _INTENT_RULES:
        if any(keyword.lower() in query_lower for keyword in rule["keywords"]):
            ids = rule["ids"]
            if ids:
                primary_boosted_ids.append(ids[0])
                secondary_boosted_ids.extend(ids[1:])

    boosted_ids: List[str] = primary_boosted_ids + secondary_boosted_ids

    # 若檢索命中子條文，補上父條文讓 Level 2 gap rules 可以套用。
    for item in list(output):
        parent_id = _PARENT_ALIASES.get(item["id"].lower())
        if parent_id:
            boosted_ids.append(parent_id)

    for idx, item_id in enumerate(dict.fromkeys(boosted_ids)):
        normalized = item_id.lower()
        if normalized in seen:
            for item in output:
                if item["id"].lower() == normalized:
                    item["score"] = round(max(float(item.get("score", 0.0)), 1000.0 - idx), 4)
            continue
        item = searcher.get_by_id(item_id)
        if not item:
            continue
        seen.add(normalized)
        output.append({
            "id": item.get("id", ""),
            "type": item.get("type", ""),
            "section": item.get("section", ""),
            "subsection": item.get("subsection", ""),
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "score": round(1000.0 - idx, 4),
        })

    output.sort(key=lambda item: item["score"], reverse=True)
    return output[:top_k]


def get_clause(clause_id: str) -> Optional[Dict]:
    """依 ID 精確查詢條文（大小寫不敏感）。

    Args:
        clause_id: 條文 ID，如 'clause_4.1' 或 'control_5.1'。

    Returns:
        條文 dict，或 None（若找不到）。
    """
    searcher = _get_searcher()
    result = searcher.get_by_id(clause_id)
    if result is None:
        return None
    # 確保回傳值 JSON serializable
    return {
        "id": result.get("id", ""),
        "type": result.get("type", ""),
        "section": result.get("section", ""),
        "subsection": result.get("subsection", ""),
        "title": result.get("title", ""),
        "content": result.get("content", ""),
    }
