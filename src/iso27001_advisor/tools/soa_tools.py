"""SoA（適用性聲明）草稿工具 — 不呼叫 LLM。

draft_soa_statement()  : 針對單一控制項產生 SoA 草稿列。
build_soa_matrix()     : 針對多控制項產生 SoA 矩陣（呼叫既有 tools）。
"""

from typing import Optional, List, Dict, Any

CONTROL_NAMES: Dict[str, str] = {
    "control_5.15": "存取控制",
    "control_5.16": "身分管理",
    "control_5.17": "鑑別資訊",
    "control_5.18": "存取權限",
    "control_5.19": "供應者關係資訊安全",
    "control_5.24": "資訊安全事故管理",
    "control_5.29": "業務持續（中斷期間資訊安全）",
    "control_5.34": "隱私及 PII 保護",
    "control_5.37": "書面紀錄運作程序",
    "control_6.3": "資訊安全認知及教育訓練",
    "control_7.1": "實體安全周界",
    "control_8.2": "特殊存取權限",
    "control_8.8": "技術脆弱性管理",
    "control_8.13": "資訊備份",
    "control_8.15": "存錄（日誌）",
    "control_8.24": "密碼技術",
    "clause_4.1": "組織全景",
    "clause_5.1": "領導力與承諾",
    "clause_6.1.2": "資訊安全風險評鑑",
    "clause_6.1.3": "資訊安全風險處理",
    "clause_9.2": "內部稽核",
    "clause_9.3": "管理審查",
    "clause_10.1": "持續改善",
    "clause_10.2": "不符合事項及矯正措施",
}

APPLICABILITY_REASONS: Dict[str, str] = {
    "control_8.13": "組織需保護資訊與系統可用性，備份為確保業務持續的必要控制。",
    "control_8.8": "組織需管理已知技術弱點，防止被利用導致安全事故。",
    "control_8.15": "組織需記錄系統活動以支援事件調查、合規查核與安全監控。",
    "control_5.15": "組織需控制人員對資訊資產的存取，以保護機密性與完整性。",
    "control_5.18": "組織需依職責授予適當存取權限，落實最小權限原則。",
    "control_5.16": "組織需管理人員身分識別生命週期，確保帳號資訊正確且及時更新。",
    "control_5.17": "組織需保護用於驗證身分的鑑別資訊（如密碼）。",
    "control_5.34": "組織處理個人資料，需符合隱私保護要求。",
    "clause_6.1.2": "組織需識別、評估資訊安全風險，作為控制措施選擇的依據。",
    "clause_9.2": "組織需定期驗證 ISMS 是否如預期運作，並符合 ISO 27001 要求。",
    "clause_9.3": "管理階層需定期審查 ISMS 績效，確保持續適切性與有效性。",
    "control_5.24": "組織需建立機制以偵測、回應及改善資安事件處理。",
    "control_5.19": "組織使用外部服務供應商，需管理供應鏈中的資訊安全風險。",
    "control_6.3": "組織人員為資安風險的重要環節，需建立意識與技能。",
    "control_7.1": "組織需保護實體資產與設施免於未授權存取。",
    "control_5.29": "組織需確保在重大中斷情況下資訊安全控制持續有效。",
    "control_8.24": "組織使用密碼技術保護資訊機密性、完整性或不可否認性。",
    "control_5.37": "組織需文件化資訊安全操作程序，確保作業一致性與可驗證性。",
    "control_8.2": "組織需限制特殊存取權限的配置與使用，降低特權帳號被濫用的風險。",
}


def _get_control_name(control_id: str) -> str:
    return CONTROL_NAMES.get(control_id.lower().strip(), control_id)


def _get_applicability_reason(control_id: str, organization_context: str) -> str:
    base = APPLICABILITY_REASONS.get(control_id.lower().strip(), "組織資訊安全管理需求。")
    if organization_context:
        return f"{base}（{organization_context.strip()[:60]}）"
    return base


def draft_soa_statement(
    control_id: str,
    organization_context: str = "",
    implementation_summary: str = "",
    gap_result: Optional[Dict] = None,
    evidence: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """針對單一控制項產生 SoA 草稿列（deterministic，不呼叫 LLM）。

    實作狀態判斷規則：
    - 有缺口（missing_signals 非空）→ 部分實作
    - 有涵蓋訊號且無缺口 → 已實作待驗證
    - 沒有任何描述 → 待確認

    Returns:
        JSON serializable dict，符合 SoA 草稿列規格。
    """
    cid = control_id.lower().strip()
    name = _get_control_name(cid)
    reason = _get_applicability_reason(cid, organization_context)

    missing_signals: List = (gap_result or {}).get("missing_signals", [])
    covered_signals: List = (gap_result or {}).get("covered_signals", [])

    gaps = [s.get("theme", str(s)) if isinstance(s, dict) else str(s) for s in missing_signals]

    if gaps:
        status = "部分實作"
    elif covered_signals or implementation_summary.strip():
        status = "已實作待驗證"
    else:
        status = "待確認"

    if gaps:
        gap_str = "、".join(gaps[:3]) + ("等" if len(gaps) > 3 else "")
        recommendation = f"補強以下缺口：{gap_str}。"
    else:
        recommendation = "建議維護相關文件並定期審查。"

    return {
        "control_id": cid,
        "control_name": name,
        "applicability": "適用",
        "applicability_reason": reason,
        "implementation_status": status,
        "implementation_summary": implementation_summary.strip() or "（待使用者補充）",
        "gaps": gaps,
        "evidence": list(evidence) if evidence else [],
        "recommendation": recommendation,
    }


def build_soa_matrix(
    clause_ids: List[str],
    document_text: str = "",
    organization_context: str = "",
) -> List[Dict[str, Any]]:
    """針對多控制項產生 SoA 矩陣（deterministic，不呼叫 LLM）。

    內部流程：
      analyze_document_coverage() → gap_result per control
      generate_audit_evidence_checklist() → evidence per control
      draft_soa_statement() per control → SoA row

    Returns:
        list of JSON serializable dicts，每筆為一個 SoA 草稿列。
    """
    from iso27001_advisor.tools.gap_analysis_tools import analyze_document_coverage, GAP_THEMES
    from iso27001_advisor.tools.evidence_tools import generate_audit_evidence_checklist

    normalized_ids = [cid.lower().strip() for cid in clause_ids]
    evidence_list = generate_audit_evidence_checklist(normalized_ids)
    evidence_by_id = {e["clause_id"]: e["evidence"] for e in evidence_list}

    rows: List[Dict[str, Any]] = []
    for cid in normalized_ids:
        if document_text and cid in GAP_THEMES:
            single_gap = analyze_document_coverage(document_text, [{"id": cid}])
        else:
            single_gap = {"covered_signals": [], "missing_signals": [], "risk_level": "low", "notes": []}

        row = draft_soa_statement(
            control_id=cid,
            organization_context=organization_context,
            implementation_summary="",
            gap_result=single_gap,
            evidence=evidence_by_id.get(cid, []),
        )
        rows.append(row)

    return rows
