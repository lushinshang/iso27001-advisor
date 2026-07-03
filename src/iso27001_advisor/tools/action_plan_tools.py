"""改善計畫工具 — 不呼叫 LLM。

build_remediation_roadmap() : 將缺口轉為 30/60/90 天改善路線圖。
"""

from typing import Dict, List, Any

# 各缺口主題的改善時限與負責團隊（靜態規則）
THEME_PLAN: Dict[str, Dict[str, str]] = {
    # P0：30 天內必須完成
    "還原測試":             {"window": "days_30", "owner": "IT"},
    "定期存取權限覆核":     {"window": "days_30", "owner": "IT"},
    "帳號停用程序":         {"window": "days_30", "owner": "IT"},
    "修補期限":             {"window": "days_30", "owner": "IT"},
    "事件分類分級":         {"window": "days_30", "owner": "資安"},
    "回應時限":             {"window": "days_30", "owner": "資安"},
    "風險評鑑準則":         {"window": "days_30", "owner": "資安"},
    "風險擁有者":           {"window": "days_30", "owner": "資安"},
    "資料最小化":           {"window": "days_30", "owner": "合規"},
    "同意書管理":           {"window": "days_30", "owner": "合規"},
    "特殊存取權限管理":     {"window": "days_30", "owner": "IT"},
    "特權帳號管理":         {"window": "days_30", "owner": "IT"},
    # P1：60 天內完成
    "備份保存期限":         {"window": "days_60", "owner": "IT"},
    "備份保護（加密/異地）":{"window": "days_60", "owner": "IT"},
    "失敗告警機制":         {"window": "days_60", "owner": "IT"},
    "日誌審查週期":         {"window": "days_60", "owner": "資安"},
    "日誌保存期限":         {"window": "days_60", "owner": "IT"},
    "日誌保護完整性":       {"window": "days_60", "owner": "IT"},
    "修補驗證":             {"window": "days_60", "owner": "IT"},
    "例外處理":             {"window": "days_60", "owner": "資安"},
    "最小權限原則":         {"window": "days_60", "owner": "IT"},
    "供應商資安要求":       {"window": "days_60", "owner": "合規"},
    "供應商稽核或評估":     {"window": "days_60", "owner": "合規"},
    "供應商存取控制":       {"window": "days_60", "owner": "IT"},
    "金鑰管理":             {"window": "days_60", "owner": "IT"},
    "加密政策":             {"window": "days_60", "owner": "資安"},
    "憑證管理":             {"window": "days_60", "owner": "IT"},
    "更新頻率":             {"window": "days_60", "owner": "資安"},
    "訓練效果評估":         {"window": "days_60", "owner": "HR"},
    "訓練頻率":             {"window": "days_60", "owner": "HR"},
    "稽核結果追蹤":         {"window": "days_60", "owner": "合規"},
    # P2：90 天內完成
    "訪客管理":             {"window": "days_90", "owner": "IT"},
    "門禁紀錄保存":         {"window": "days_90", "owner": "IT"},
    "安全區域審查":         {"window": "days_90", "owner": "IT"},
    "BCP/DR 演練":          {"window": "days_90", "owner": "IT"},
    "RTO/RPO 目標":         {"window": "days_90", "owner": "IT"},
    "BCP 更新頻率":         {"window": "days_90", "owner": "資安"},
    "事件演練":             {"window": "days_90", "owner": "資安"},
    "訓練紀錄":             {"window": "days_90", "owner": "HR"},
    "程序書定期審查":       {"window": "days_90", "owner": "合規"},
    "版本控制":             {"window": "days_90", "owner": "合規"},
    "程序書核准":           {"window": "days_90", "owner": "合規"},
    "稽核獨立性":           {"window": "days_90", "owner": "合規"},
    "稽核頻率":             {"window": "days_90", "owner": "合規"},
    "審查頻率":             {"window": "days_90", "owner": "合規"},
    "審查輸入項目":         {"window": "days_90", "owner": "合規"},
    "審查決議追蹤":         {"window": "days_90", "owner": "合規"},
    "資料遮罩或匿名化":     {"window": "days_90", "owner": "IT"},
}

# 控制項所屬負責團隊（當 theme 不在 THEME_PLAN 時的 fallback）
CONTROL_DEFAULT_OWNER: Dict[str, str] = {
    "control_8.13": "IT",
    "control_8.8": "IT",
    "control_8.15": "IT",
    "control_5.15": "IT",
    "control_5.18": "IT",
    "control_5.16": "IT",
    "control_5.17": "IT",
    "control_5.24": "資安",
    "control_5.19": "合規",
    "control_6.3": "HR",
    "control_7.1": "IT",
    "control_5.29": "IT",
    "control_8.24": "IT",
    "control_5.34": "合規",
    "clause_6.1.2": "資安",
    "clause_9.2": "合規",
    "clause_9.3": "合規",
    "control_5.37": "合規",
    "control_8.2": "IT",
}


def build_remediation_roadmap(gap_result: Dict, clause_ids: List[str]) -> Dict[str, Any]:
    """將缺口分析結果轉為 30/60/90 天改善路線圖（deterministic，不呼叫 LLM）。

    Args:
        gap_result  : analyze_document_coverage() 的回傳值。
        clause_ids  : 相關控制項 ID 清單。

    Returns:
        JSON serializable dict，含 days_30、days_60、days_90、owners、summary。
    """
    missing_signals = gap_result.get("missing_signals", [])
    risk_level = gap_result.get("risk_level", "low")

    days_30: List[str] = []
    days_60: List[str] = []
    days_90: List[str] = []
    owners_set: set = set()

    for sig in missing_signals:
        theme = sig.get("theme", str(sig)) if isinstance(sig, dict) else str(sig)
        plan = THEME_PLAN.get(theme)
        if plan:
            window = plan["window"]
            owner = plan["owner"]
            item = f"【{owner}】{theme}：{_get_action_text(theme)}"
            owners_set.add(owner)
            if window == "days_30":
                days_30.append(item)
            elif window == "days_60":
                days_60.append(item)
            else:
                days_90.append(item)
        else:
            # 未知 theme 預設 60 天
            days_60.append(f"補強 {theme} 相關控制措施")

    # 若所有 bucket 都空，產生通用計畫
    if not days_30 and not days_60 and not days_90:
        normalized = [cid.lower().strip() for cid in clause_ids]
        days_30.append("確認各控制項現況與文件化狀態")
        days_60.append("完成缺口項目的文件補充或程序建立")
        days_90.append("執行內部審查確認改善完成，準備稽核")

    # 補充控制項負責人
    for cid in clause_ids:
        owner = CONTROL_DEFAULT_OWNER.get(cid.lower().strip())
        if owner:
            owners_set.add(owner)

    owners = sorted(owners_set) if owners_set else ["IT", "資安", "合規"]

    return {
        "risk_level": risk_level,
        "days_30": days_30,
        "days_60": days_60,
        "days_90": days_90,
        "owners": owners,
        "summary": (
            f"共發現 {len(missing_signals)} 項可能缺口，"
            f"其中 {len(days_30)} 項建議於 30 天內完成，"
            f"{len(days_60)} 項於 60 天內完成，"
            f"{len(days_90)} 項於 90 天內完成。"
        ),
    }


def _get_action_text(theme: str) -> str:
    actions = {
        "還原測試": "建立定期還原測試程序並執行首次測試，留存紀錄",
        "定期存取權限覆核": "完成全員存取權限覆核並留存紀錄",
        "帳號停用程序": "訂定離職帳號停用 SLA 並納入 HR 離職流程",
        "修補期限": "在脆弱性管理程序中明訂各風險等級的修補時限",
        "事件分類分級": "建立資安事件分類分級定義文件",
        "回應時限": "在事件管理程序中訂定回應與通報時限",
        "風險評鑑準則": "建立風險評鑑方法論，定義評鑑準則與等級",
        "風險擁有者": "指定各風險的擁有者並記錄於風險登錄表",
        "備份保存期限": "在備份政策中明訂保存期限規定",
        "備份保護（加密/異地）": "實作備份加密或異地儲存機制",
        "失敗告警機制": "設定備份失敗自動告警通知",
        "日誌審查週期": "訂定定期日誌審查週期並指派負責人",
        "日誌保存期限": "在日誌管理政策中明訂保存期限",
        "日誌保護完整性": "設定日誌唯讀保護或集中收集機制",
        "修補驗證": "建立修補後複掃驗證流程",
        "例外處理": "建立弱點豁免申請流程",
        "最小權限原則": "在存取控制政策中明訂最小權限要求並納入申請流程",
        "特權帳號管理": "建立特權帳號清冊並限制使用範圍",
        "訓練效果評估": "在訓練計畫中加入測驗或評估機制",
        "訓練頻率": "在訓練計畫中明訂年度訓練頻率",
        "稽核結果追蹤": "建立不符合事項追蹤清單並指派負責人",
        "BCP/DR 演練": "安排 BCP/DR 演練並留存紀錄",
        "RTO/RPO 目標": "在 BCP/DRP 中明訂 RTO/RPO 目標",
        "程序書定期審查": "排定程序書年度審查計畫",
    }
    return actions.get(theme, f"建立 {theme} 相關文件或程序")
