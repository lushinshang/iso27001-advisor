"""稽核報告工具 — 不呼叫 LLM。

build_audit_readiness_report() : 產生稽核準備報告結構化資料。
build_audit_question_pack()    : 針對控制項產生稽核問答包。
"""

from typing import List, Dict, Any

# 稽核員常見問題庫（每控制項至少 3 題）
AUDIT_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "control_8.13": {
        "name": "資訊備份",
        "questions": [
            "備份是否依政策定期執行？頻率為何？",
            "是否有定期還原測試紀錄？最近一次為何時？",
            "備份失敗時如何告警與處理？",
            "備份資料的保存期限是多久？",
            "備份資料是否加密存放或保存於異地？",
        ],
        "answer_points": [
            "說明備份排程、範圍與保存期限政策。",
            "展示最近一次還原測試紀錄（含日期、測試範圍、結果）。",
            "說明備份失敗告警機制與處理流程，展示相關紀錄。",
            "展示備份政策文件中保存期限的明確定義。",
            "展示備份加密設定截圖或異地儲存設定紀錄。",
        ],
        "common_followups": [
            "上次還原測試失敗過嗎？如何處理？",
            "誰負責監控備份作業？",
            "備份媒體或儲存帳號有存取控制嗎？",
        ],
    },
    "control_5.15": {
        "name": "存取控制",
        "questions": [
            "存取控制政策是否已書面化並定期審查？",
            "帳號申請與異動是否有正式核准流程？",
            "是否定期執行存取權限覆核？多久一次？",
            "員工離職後帳號如何處理？有無停用 SLA？",
            "是否遵循最小權限原則？",
        ],
        "answer_points": [
            "展示存取控制政策文件與最後審查日期。",
            "展示帳號申請單、異動單範本與核准紀錄。",
            "展示定期覆核紀錄（含覆核人、日期、結果）。",
            "展示離職員工帳號停用 SLA 規定與執行紀錄。",
            "說明如何在授權時落實最小權限原則。",
        ],
        "common_followups": [
            "過去 6 個月有無發現不當權限？如何處理？",
            "特殊權限帳號（admin）有多少？",
            "是否有孤兒帳號（無使用者對應）？",
        ],
    },
    "control_5.18": {
        "name": "存取權限",
        "questions": [
            "存取權限的授予流程為何？",
            "是否有存取權限矩陣或角色定義文件？",
            "權限異動（升遷、轉調）時如何處理？",
            "是否定期審查存取權限的適當性？",
        ],
        "answer_points": [
            "展示存取權限授予流程文件與申請單範本。",
            "展示存取矩陣或角色-權限對應表。",
            "說明人員異動時的權限調整程序與紀錄。",
            "展示定期審查紀錄。",
        ],
        "common_followups": [
            "誰有權核准存取權限？",
            "如何確保實際系統設定與申請單一致？",
        ],
    },
    "control_8.15": {
        "name": "存錄（日誌）",
        "questions": [
            "日誌保存期限是多久？保存在哪裡？",
            "誰負責定期審查日誌？審查頻率為何？",
            "日誌是否有防止竄改的保護措施？",
            "是否能提供特定時間段的日誌查詢範例？",
            "哪些系統產生日誌？涵蓋範圍為何？",
        ],
        "answer_points": [
            "展示日誌管理政策中保存期限與儲存位置定義。",
            "展示定期日誌審查紀錄（含審查人、日期、發現事項）。",
            "展示日誌完整性保護設定（如唯讀、SIEM 集中收集）。",
            "現場展示日誌查詢操作或提供查詢截圖。",
            "展示日誌收集範圍清冊。",
        ],
        "common_followups": [
            "發現異常日誌後如何處理？",
            "日誌儲存空間是否充足？是否有告警？",
        ],
    },
    "control_8.8": {
        "name": "技術脆弱性管理",
        "questions": [
            "弱點掃描多久執行一次？涵蓋哪些系統？",
            "高風險弱點的修補時限是多少天？",
            "若無法在期限內修補，如何處理？",
            "修補完成後是否執行複掃驗證？",
        ],
        "answer_points": [
            "展示弱點掃描工具設定與排程截圖。",
            "展示弱點管理程序中的修補時限規定。",
            "展示弱點豁免申請流程與核准紀錄範本。",
            "展示複掃報告與修補前後對比紀錄。",
        ],
        "common_followups": [
            "目前有多少未修補的高風險弱點？",
            "誰負責追蹤弱點修補進度？",
        ],
    },
    "clause_9.2": {
        "name": "內部稽核",
        "questions": [
            "內部稽核多久執行一次？",
            "稽核員是否具備獨立性（不稽核自己負責的範圍）？",
            "稽核發現事項如何追蹤改善？",
            "是否有年度稽核計畫文件？",
        ],
        "answer_points": [
            "展示年度稽核計畫（含範圍、頻率、稽核員）。",
            "說明稽核員指派方式，確認不自稽。",
            "展示不符合事項追蹤清單與矯正措施狀態。",
            "展示最近一次稽核報告。",
        ],
        "common_followups": [
            "上次稽核發現幾個不符合？目前狀態？",
            "管理階層是否審查稽核結果？",
        ],
    },
    "control_5.24": {
        "name": "資訊安全事故管理",
        "questions": [
            "資安事件如何定義與分類？",
            "發現事件後的通報流程為何？通報對象是誰？",
            "是否有事件回應時限規定（SLA）？",
            "過去 12 個月有無實際事件處理案例？",
            "是否執行過桌上演練或事件回應演練？",
        ],
        "answer_points": [
            "展示事件分類分級定義文件。",
            "展示事件通報流程圖與聯絡清單。",
            "展示事件回應 SLA 規定。",
            "展示事件處理紀錄（若有）。",
            "展示演練紀錄與改善事項。",
        ],
        "common_followups": [
            "是否有對外通報義務（如主管機關）？",
            "事件後的根本原因分析如何進行？",
        ],
    },
    "control_5.19": {
        "name": "供應者關係資訊安全",
        "questions": [
            "供應商名冊是否維護最新狀態？如何分級？",
            "合約中是否包含資安條款？",
            "供應商的存取帳號如何申請與管控？",
            "是否定期評估供應商的資安績效？",
        ],
        "answer_points": [
            "展示供應商名冊（含風險分級）。",
            "展示合約範本中的資安條款段落。",
            "展示供應商存取帳號申請與停用紀錄。",
            "展示供應商評估或稽核報告。",
        ],
        "common_followups": [
            "若供應商發生資安事件，如何通報？",
            "是否評估供應商的分包商風險？",
        ],
    },
    "control_6.3": {
        "name": "資訊安全認知及教育訓練",
        "questions": [
            "員工資安訓練多久執行一次？",
            "訓練效果如何評估？",
            "新進人員是否有資安入職訓練？",
            "是否有訓練完成率統計？",
        ],
        "answer_points": [
            "展示年度訓練計畫與出席紀錄。",
            "展示訓練測驗結果或完成率報表。",
            "展示新進人員資安訓練紀錄。",
            "說明未完成訓練者的後續追蹤機制。",
        ],
        "common_followups": [
            "釣魚郵件演練是否執行？結果如何？",
            "高風險職位是否有進階訓練？",
        ],
    },
    "control_5.29": {
        "name": "業務持續（中斷期間資訊安全）",
        "questions": [
            "是否有 BCP 或 DRP 文件？",
            "RTO 與 RPO 目標如何定義？",
            "BCP/DR 演練多久執行一次？",
            "關鍵系統清冊是否維護更新？",
        ],
        "answer_points": [
            "展示 BCP/DRP 文件與版本。",
            "展示 RTO/RPO 目標定義文件。",
            "展示演練計畫與演練結果紀錄。",
            "展示關鍵系統清冊。",
        ],
        "common_followups": [
            "上次演練有無發現問題？如何改善？",
            "替代作業程序是否已文件化？",
        ],
    },
    "control_8.24": {
        "name": "密碼技術",
        "questions": [
            "組織使用哪些加密演算法？是否有政策規定？",
            "金鑰如何管理（生成、儲存、輪換、銷毀）？",
            "憑證到期管理如何執行？",
            "TLS/SSL 版本設定是否符合最低要求？",
        ],
        "answer_points": [
            "展示密碼技術使用政策（含允許演算法清單）。",
            "展示金鑰管理程序書與金鑰保管紀錄。",
            "展示憑證清冊與到期提醒機制。",
            "展示系統 TLS 版本設定截圖。",
        ],
        "common_followups": [
            "金鑰保管責任人是誰？",
            "是否有已過期但仍在使用的憑證？",
        ],
    },
    "clause_9.3": {
        "name": "管理審查",
        "questions": [
            "管理審查多久執行一次？",
            "審查的輸入項目有哪些？",
            "審查決議如何追蹤執行？",
            "管理階層是否實際出席並簽核？",
        ],
        "answer_points": [
            "展示管理審查會議記錄（含出席人員、討論議題）。",
            "展示審查輸入文件（稽核結果、風險評鑑摘要、KPI）。",
            "展示審查決議追蹤清單。",
            "確認會議記錄有管理階層簽核。",
        ],
        "common_followups": [
            "ISMS 目標是否定期更新？達成狀況如何？",
            "上次管理審查有無決議改善事項？狀態為何？",
        ],
    },
}

# 優先級對應（P0 = 高風險，P1 = 中風險，P2 = 低風險）
CONTROL_PRIORITY: Dict[str, str] = {
    "control_8.13": "P0",
    "control_5.15": "P0",
    "control_8.15": "P1",
    "control_8.8": "P0",
    "clause_9.2": "P1",
    "control_5.24": "P0",
    "control_5.19": "P1",
    "control_6.3": "P2",
    "control_5.29": "P1",
    "control_8.24": "P1",
    "clause_9.3": "P1",
    "control_5.18": "P0",
    "control_5.16": "P1",
    "control_5.17": "P1",
    "control_5.34": "P0",
    "clause_6.1.2": "P0",
    "control_5.37": "P2",
    "control_7.1": "P1",
    "control_8.2": "P0",
    "clause_10.2": "P1",
}


def _assign_priority(control_id: str, gap_count: int) -> str:
    base = CONTROL_PRIORITY.get(control_id.lower().strip(), "P2")
    if gap_count >= 3 and base == "P1":
        return "P0"
    return base


def build_audit_readiness_report(
    document_text: str,
    matched_items: List[Dict],
    gap_result: Dict,
    evidence_list: List[Dict],
    remediation_bullets: List[str],
) -> Dict[str, Any]:
    """產生稽核準備報告的結構化資料（deterministic，不呼叫 LLM）。

    Returns:
        JSON serializable dict，含 summary、control_matrix、quick_wins、open_questions。
    """
    missing_signals = gap_result.get("missing_signals", [])
    covered_signals = gap_result.get("covered_signals", [])
    risk_level = gap_result.get("risk_level", "low")

    # 建立 control_matrix
    evidence_by_id = {e["clause_id"]: e["evidence"] for e in evidence_list}
    control_matrix = []
    for item in matched_items:
        cid = item.get("id", "").lower().strip()
        # 收集此 control 相關的 missing_signals（依 GAP_THEMES 分類）
        from iso27001_advisor.tools.gap_analysis_tools import GAP_THEMES
        control_themes = set()
        if cid in GAP_THEMES:
            control_themes = {c["theme"] for c in GAP_THEMES[cid]["missing_checks"]}
        item_gaps = [
            s.get("theme", str(s)) if isinstance(s, dict) else str(s)
            for s in missing_signals
            if (isinstance(s, dict) and s.get("theme") in control_themes) or not control_themes
        ]
        gap_count = len(item_gaps)
        priority = _assign_priority(cid, gap_count)
        cname = item.get("subsection", item.get("name", cid))
        control_matrix.append({
            "control_id": cid,
            "control_name": cname,
            "gaps": item_gaps,
            "evidence": evidence_by_id.get(cid, []),
            "priority": priority,
        })

    # 依優先級排序
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    control_matrix.sort(key=lambda x: priority_order.get(x["priority"], 9))

    # Quick wins：缺口少於 2 且僅需補文件的控制項
    quick_wins = []
    doc_only_themes = {
        "日誌保存期限", "備份保存期限", "修補期限", "稽核頻率",
        "程序書定期審查", "版本控制", "審查頻率",
    }
    for sig in missing_signals:
        theme = sig.get("theme", "") if isinstance(sig, dict) else str(sig)
        if theme in doc_only_themes:
            quick_wins.append(f"補充 {theme} 規定文字至現有政策（文件補強即可）")

    # Open questions：需管理階層確認的事項
    open_questions = [
        "上述缺口的矯正措施負責人為何？",
        "是否有業務不適用的控制項需要明確聲明排除理由？",
        "預計稽核日期與準備期限為何？",
    ]

    return {
        "summary": {
            "risk_level": risk_level,
            "matched_control_count": len(matched_items),
            "gap_count": len(missing_signals),
            "covered_count": len(covered_signals),
        },
        "control_matrix": control_matrix,
        "quick_wins": quick_wins,
        "open_questions": open_questions,
        "remediation_highlights": remediation_bullets[:5],
    }


def build_audit_question_pack(clause_ids: List[str]) -> List[Dict[str, Any]]:
    """針對指定控制項產生稽核問答包（deterministic，不呼叫 LLM）。

    Args:
        clause_ids: 控制項 ID 清單，如 ['control_8.13', 'control_5.15']。

    Returns:
        list of JSON serializable dicts，每筆含 control_id、questions、
        answer_points、common_followups、evidence。
    """
    from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist

    normalized = [cid.lower().strip() for cid in clause_ids]
    evidence_list = generate_audit_evidence_checklist(normalized)
    evidence_by_id = {e["clause_id"]: e["evidence"] for e in evidence_list}

    result = []
    for cid in normalized:
        if cid in AUDIT_QUESTIONS:
            entry = AUDIT_QUESTIONS[cid]
            result.append({
                "control_id": cid,
                "control_name": entry["name"],
                "questions": list(entry["questions"]),
                "answer_points": list(entry["answer_points"]),
                "common_followups": list(entry.get("common_followups", [])),
                "evidence": evidence_by_id.get(cid, []),
            })
        else:
            # 控制項不在問題庫時，產生通用問題包
            result.append({
                "control_id": cid,
                "control_name": cid,
                "questions": [
                    f"{cid} 的控制措施是否已書面化？",
                    "相關程序是否定期審查？",
                    "是否有執行紀錄可供查驗？",
                ],
                "answer_points": [
                    "展示相關政策或程序書文件。",
                    "展示定期審查紀錄。",
                    "展示執行紀錄（如適用）。",
                ],
                "common_followups": [],
                "evidence": evidence_by_id.get(cid, []),
            })

    return result
