"""Deterministic 規則分析文件與 ISO 27001 條文的缺口，不呼叫 LLM。

根據預定義的 GAP_THEMES 規則表，檢查文件是否已涵蓋各控制項的關鍵要求，
並找出尚未提及的補強主題。
"""

from typing import Dict, List, Any

GAP_THEMES: Dict[str, Any] = {
    "control_8.13": {
        "name": "資訊備份",
        "covered_keywords": ["備份", "backup", "備份檔", "排程", "每日", "每週", "自動備份"],
        "missing_checks": [
            {"theme": "還原測試", "keywords": ["還原", "復原", "restore", "測試"]},
            {"theme": "備份保存期限", "keywords": ["保存期限", "保留期間", "retention", "幾天", "幾個月"]},
            {"theme": "備份保護（加密/異地）", "keywords": ["加密", "離線", "異地", "offsite", "存取控制"]},
            {"theme": "失敗告警機制", "keywords": ["失敗", "異常", "告警", "通報", "alert"]},
        ],
    },
    "control_8.8": {
        "name": "技術脆弱性管理",
        "covered_keywords": ["弱點掃描", "漏洞", "patch", "修補", "CVE", "CVSS", "脆弱性"],
        "missing_checks": [
            {"theme": "修補期限", "keywords": ["期限", "時限", "SLA", "天內", "修補時間"]},
            {"theme": "修補驗證", "keywords": ["驗證", "確認", "複掃", "rescan"]},
            {"theme": "例外處理", "keywords": ["例外", "豁免", "exception", "風險接受"]},
        ],
    },
    "control_8.15": {
        "name": "存錄（日誌）",
        "covered_keywords": ["日誌", "log", "存錄", "稽核軌跡", "audit trail", "記錄", "logging", "siem", "syslog", "事件紀錄"],
        "missing_checks": [
            {"theme": "日誌審查週期", "keywords": ["審查", "review", "定期", "每週", "每月"]},
            {"theme": "日誌保存期限", "keywords": ["保存", "retention", "幾個月", "幾年"]},
            {"theme": "日誌保護完整性", "keywords": ["保護", "竄改", "integrity", "不可修改"]},
        ],
    },
    "control_5.15": {
        "name": "存取控制",
        "covered_keywords": ["存取控制", "帳號", "權限", "access", "登入"],
        "missing_checks": [
            {"theme": "定期存取權限覆核", "keywords": ["定期", "覆核", "review", "每年", "審核"]},
            {"theme": "最小權限原則", "keywords": ["最小權限", "least privilege", "need-to-know"]},
            {"theme": "特權帳號管理", "keywords": ["特權", "admin", "root", "管理員"]},
            {"theme": "帳號停用程序", "keywords": ["離職", "停用", "刪除", "異動"]},
        ],
    },
    "control_5.34": {
        "name": "隱私及 PII 保護",
        "covered_keywords": ["個資", "PII", "隱私", "個人資料", "GDPR"],
        "missing_checks": [
            {"theme": "資料最小化", "keywords": ["最小化", "minimization", "必要"]},
            {"theme": "資料遮罩或匿名化", "keywords": ["遮罩", "匿名", "mask", "anonymize"]},
            {"theme": "同意書管理", "keywords": ["同意書", "consent", "撤回", "存檔"]},
        ],
    },
    "clause_6.1.2": {
        "name": "資訊安全風險評鑑",
        "covered_keywords": ["風險評鑑", "風險評估", "risk assessment", "風險"],
        "missing_checks": [
            {"theme": "風險評鑑準則", "keywords": ["準則", "標準", "criteria", "等級定義"]},
            {"theme": "風險擁有者", "keywords": ["擁有者", "owner", "負責人", "風險擁有"]},
            {"theme": "更新頻率", "keywords": ["更新", "重新評估", "重大變更", "臨時評鑑"]},
        ],
    },
    "clause_9.2": {
        "name": "內部稽核",
        "covered_keywords": ["內部稽核", "稽核計畫", "audit plan", "稽核"],
        "missing_checks": [
            {"theme": "稽核獨立性", "keywords": ["獨立", "independent", "不稽核自己"]},
            {"theme": "稽核頻率", "keywords": ["每年", "年度", "頻率", "週期"]},
            {"theme": "稽核結果追蹤", "keywords": ["追蹤", "改善", "矯正", "結果"]},
        ],
    },
    "control_5.24": {
        "name": "資訊安全事故管理",
        "covered_keywords": ["事件管理", "事故管理", "資安事件", "incident", "通報", "通知"],
        "missing_checks": [
            {"theme": "事件分類分級", "keywords": ["分類", "分級", "severity", "等級", "priority"]},
            {"theme": "回應時限", "keywords": ["時限", "SLA", "小時內", "天內", "回應時間"]},
            {"theme": "事件演練", "keywords": ["演練", "桌上演練", "tabletop", "drill"]},
        ],
    },
    "control_5.19": {
        "name": "供應者關係資訊安全",
        "covered_keywords": ["供應商", "廠商", "第三方", "vendor", "供應者", "外包"],
        "missing_checks": [
            {"theme": "供應商資安要求", "keywords": ["資安要求", "安全要求", "security requirement"]},
            {"theme": "供應商稽核或評估", "keywords": ["稽核", "評估", "audit", "assessment", "評核"]},
            {"theme": "供應商存取控制", "keywords": ["存取", "帳號", "VPN", "遠端存取"]},
        ],
    },
    "control_6.3": {
        "name": "資訊安全認知及教育訓練",
        "covered_keywords": ["教育訓練", "訓練", "意識", "awareness", "課程", "教學"],
        "missing_checks": [
            {"theme": "訓練效果評估", "keywords": ["測驗", "評估", "考試", "效果", "completion"]},
            {"theme": "訓練頻率", "keywords": ["每年", "定期", "年度", "頻率"]},
            {"theme": "訓練紀錄", "keywords": ["紀錄", "記錄", "完成紀錄", "出席"]},
        ],
    },
    "control_7.1": {
        "name": "實體安全周界",
        "covered_keywords": ["門禁", "實體安全", "感應卡", "badge", "周界", "機房"],
        "missing_checks": [
            {"theme": "訪客管理", "keywords": ["訪客", "visitor", "登記", "陪同", "訪客證"]},
            {"theme": "門禁紀錄保存", "keywords": ["紀錄", "保存", "log", "多久", "保留"]},
            {"theme": "安全區域審查", "keywords": ["審查", "定期", "review", "重新評估"]},
        ],
    },
    "control_5.29": {
        "name": "業務持續（中斷期間資訊安全）",
        "covered_keywords": ["業務持續", "BCP", "DR", "災難復原", "disaster recovery", "營運持續"],
        "missing_checks": [
            {"theme": "BCP/DR 演練", "keywords": ["演練", "測試", "drill", "failover"]},
            {"theme": "RTO/RPO 目標", "keywords": ["RTO", "RPO", "復原時間", "復原點", "目標"]},
            {"theme": "BCP 更新頻率", "keywords": ["更新", "定期", "審查", "每年"]},
        ],
    },
    "control_8.24": {
        "name": "密碼技術",
        "covered_keywords": ["加密", "encryption", "AES", "TLS", "SSL", "密碼", "憑證"],
        "missing_checks": [
            {"theme": "金鑰管理", "keywords": ["金鑰", "key management", "key store", "保管", "輪換"]},
            {"theme": "加密政策", "keywords": ["政策", "標準", "規定", "演算法", "policy"]},
            {"theme": "憑證管理", "keywords": ["憑證", "certificate", "到期", "更新", "CA"]},
        ],
    },
    "clause_9.3": {
        "name": "管理審查",
        "covered_keywords": ["管理審查", "management review", "高管審查", "董事會"],
        "missing_checks": [
            {"theme": "審查頻率", "keywords": ["每年", "定期", "年度", "頻率"]},
            {"theme": "審查輸入項目", "keywords": ["輸入", "input", "稽核結果", "風險", "KPI"]},
            {"theme": "審查決議追蹤", "keywords": ["決議", "追蹤", "action", "改善", "結果"]},
        ],
    },
    "control_5.37": {
        "name": "書面紀錄運作程序",
        "covered_keywords": ["程序書", "作業程序", "SOP", "操作手冊", "文件化"],
        "missing_checks": [
            {"theme": "程序書定期審查", "keywords": ["審查", "更新", "定期", "版本", "review"]},
            {"theme": "版本控制", "keywords": ["版本", "version", "修訂", "變更紀錄"]},
            {"theme": "程序書核准", "keywords": ["核准", "授權", "approval", "簽核"]},
        ],
    },
}


_NEGATION_WORDS = [
    "沒有", "未", "缺乏", "缺少", "沒", "無", "尚未", "並未", "不曾",
    "no ", "not ", "without ", "lack", "missing",
]
_NEGATION_WINDOW = 15  # 關鍵字前幾個字元內若出現否定詞，視為被否定


def _keyword_negated(text: str, keyword: str) -> bool:
    """檢查 text 中所有出現 keyword 的位置，若前綴視窗內有否定詞則回傳 True。"""
    text_lower = text.lower()
    kw_lower = keyword.lower()
    idx = 0
    while True:
        pos = text_lower.find(kw_lower, idx)
        if pos == -1:
            break
        prefix = text_lower[max(0, pos - _NEGATION_WINDOW):pos]
        if any(neg in prefix for neg in _NEGATION_WORDS):
            return True
        idx = pos + 1
    return False


def _text_contains_any(text: str, keywords: List[str]) -> bool:
    """不分大小寫，檢查 text 是否包含 keywords 中任一字串。"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _text_contains_any_unnegated(text: str, keywords: List[str]) -> bool:
    """檢查 text 是否包含 keywords 中任一字串，且該出現位置未被否定詞修飾。"""
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in text_lower:
            continue
        if not _keyword_negated(text, kw):
            return True
    return False


def _find_evidence_snippet(text: str, keywords: List[str]) -> str:
    """從 text 中找出包含 keyword 的第一個片段（前後各 20 字元）。"""
    text_lower = text.lower()
    for kw in keywords:
        idx = text_lower.find(kw.lower())
        if idx != -1:
            start = max(0, idx - 20)
            end = min(len(text), idx + len(kw) + 20)
            return text[start:end].strip()
    return ""


_INSUFFICIENT_PATTERNS: Dict[str, List[str]] = {
    "還原測試": ["唯一知道如何還原", "尚未文件化"],
    "備份保存期限": ["保存 30 天", "保存30天"],
    "備份保護（加密/異地）": ["任何人都可以存取", "沒有特別設定權限"],
    "失敗告警機制": ["偶爾有失敗", "由 it 工程師", "由it工程師"],
    "修補驗證": ["修補程式", "patch 安裝紀錄", "patch安裝紀錄"],
    "例外處理": ["無法及時修補", "相容性問題"],
    "日誌審查週期": ["沒有人定期查看", "無人定期查看"],
    "日誌保存期限": ["保存 30 天", "保存30天", "保存 90 天", "保存90天"],
    "日誌保護完整性": ["保存 6 個月", "保存6個月"],
    "定期存取權限覆核": ["沒有定期覆核", "未定期覆核", "缺少定期覆核"],
    "特權帳號管理": ["沒有明確規定離職", "離職後多久"],
    "帳號停用程序": ["沒有明確規定離職", "離職後多久"],
    "資料最小化": ["姓名、電話、地址、生日、職業、興趣愛好", "委外", "第三方廠商"],
    "資料遮罩或匿名化": ["真實個資測試", "使用真實個資"],
    "同意書管理": ["未整理個資盤點清冊", "沒有個資盤點清冊"],
    "風險評鑑準則": ["評估可能的衝擊", "擬定風險處理計畫"],
    "風險擁有者": ["未指定風險擁有者", "沒有指定風險擁有者"],
    "更新頻率": ["三年來沒有更新", "沒有更新", "未更新", "只做一次"],
    "稽核獨立性": ["資安部門人員負責執行"],
    "稽核頻率": ["每兩年"],
    "稽核結果追蹤": ["稽核報告提呈", "提呈管理階層"],
}


def _has_insufficient_signal(text: str, theme: str) -> bool:
    text_lower = text.lower()
    return any(pattern.lower() in text_lower for pattern in _INSUFFICIENT_PATTERNS.get(theme, []))


def analyze_document_coverage(
    document_text: str,
    matched_items: List[Dict],
) -> Dict:
    """分析文件對 ISO 27001 條文的涵蓋程度，找出缺口主題。

    Args:
        document_text: 待分析的原始文件內容。
        matched_items: search_iso() 或 get_clause() 回傳的條文清單，
                       每筆至少含 "id" 欄位。

    Returns:
        dict，包含：
          - covered_signals: list[dict] 已涵蓋的關鍵字與佐證片段
          - missing_signals: list[dict] 缺漏的控制主題與原因說明
          - risk_level: "low" | "medium" | "high"
          - notes: list[str] 補充說明
    """
    covered_signals: List[Dict] = []
    missing_signals: List[Dict] = []
    notes: List[str] = []

    # 找出 matched_items 中有 GAP_THEMES 定義的 clause_id
    relevant_ids = []
    for item in matched_items:
        item_id = item.get("id", "").lower()
        if item_id in GAP_THEMES:
            relevant_ids.append(item_id)

    if not relevant_ids:
        notes.append("matched_items 中沒有符合 GAP_THEMES 定義的條文 ID，無法執行缺口分析。")
        return {
            "covered_signals": covered_signals,
            "missing_signals": missing_signals,
            "risk_level": "low",
            "notes": notes,
        }

    for clause_id in relevant_ids:
        theme_def = GAP_THEMES[clause_id]

        # 檢查 covered_keywords 是否出現在文件中
        for kw in theme_def["covered_keywords"]:
            if kw.lower() in document_text.lower():
                snippet = _find_evidence_snippet(document_text, [kw])
                covered_signals.append({
                    "keyword": kw,
                    "evidence": snippet,
                })
                break  # 找到一個就代表此 clause 有涵蓋，不重複記錄

        # 逐項檢查 missing_checks
        for check in theme_def["missing_checks"]:
            has_unnegated_keyword = _text_contains_any_unnegated(document_text, check["keywords"])
            has_insufficient_signal = _has_insufficient_signal(document_text, check["theme"])
            if not has_unnegated_keyword or has_insufficient_signal:
                reason = (
                    f"文件雖提及 {check['theme']} 相關內容，但描述可能不足或存在反向訊號"
                    if has_insufficient_signal
                    else f"文件未描述 {check['theme']}（未找到關鍵字：{', '.join(check['keywords'])}）"
                )
                missing_signals.append({
                    "theme": check["theme"],
                    "reason": reason,
                })

    # 計算 risk_level
    missing_count = len(missing_signals)
    if missing_count == 0:
        risk_level = "low"
    elif missing_count <= 2:
        risk_level = "medium"
    else:
        risk_level = "high"

    return {
        "covered_signals": covered_signals,
        "missing_signals": missing_signals,
        "risk_level": risk_level,
        "notes": notes,
    }
