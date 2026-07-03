#!/usr/bin/env python3
"""
recommendation.py - ISO 27001 合規推薦系統

根據當前問答命中的條文 ID，從關聯圖譜查出相關主題，
回傳 2-3 個推薦下一步問題（優先使用 FAQ 快取中的真實問題）。
零 LLM 成本，純 JSON 查表。
"""
import json
import os
from pathlib import Path
from typing import List, Dict, Optional

_BASE = Path(__file__).resolve().parents[3]
GRAPH_PATH   = os.path.join(_BASE, "data", "pdca_graph.json")
FAQ_PATH     = os.path.join(_BASE, "tmp", "faq_cache.json")

# 當 FAQ 快取尚未生成時，使用預設問題範本
_FALLBACK_QUESTIONS: Dict[str, str] = {
    "control_5.1":  "資訊安全政策應包含哪些內容？如何確保管理階層核可？",
    "control_5.2":  "如何定義與配置組織內的資訊安全角色與責任？",
    "control_5.3":  "職務區隔的具體實施方式為何？有哪些常見的衝突職務？",
    "control_5.15": "如何建立有效的存取控制政策？",
    "control_5.16": "身分管理的稽核證據需要準備哪些？",
    "control_5.17": "密碼管理政策應涵蓋哪些要求事項？",
    "control_5.18": "存取權限審查的頻率與流程應如何設計？",
    "control_5.24": "如何建立資訊安全事件管理計畫？",
    "control_5.25": "資訊安全事件的分類分級標準如何訂定？",
    "control_5.26": "發生資訊安全事故時的回應程序為何？",
    "control_5.29": "中斷期間的資訊安全如何維持？",
    "control_5.30": "ICT 備妥性計畫應涵蓋哪些內容？",
    "control_5.34": "個人資料保護（PII）的控制措施有哪些？",
    "control_5.35": "資訊安全獨立審查應如何進行？",
    "control_5.36": "如何確保員工遵循資訊安全政策？",
    "control_6.3":  "資訊安全教育訓練計畫應包含哪些主題？",
    "control_6.8":  "員工發現資訊安全事件時應如何通報？",
    "control_7.1":  "實體安全周界的設計標準為何？",
    "control_7.2":  "如何管控實體進入敏感區域的存取？",
    "control_8.2":  "特殊存取權限（特權帳號）應如何管理？",
    "control_8.7":  "防範惡意軟體的控制措施應包含哪些？",
    "control_8.8":  "如何建立技術脆弱性管理流程？",
    "control_8.13": "備份的稽核證據要準備什麼？備份測試如何執行？",
    "control_8.15": "資訊系統的日誌記錄應保存哪些內容？",
    "control_8.19": "變更管理流程應如何設計以確保資訊安全？",
    "control_8.20": "網路安全管理應涵蓋哪些控制措施？",
    "control_8.24": "密碼技術的使用政策應包含哪些規定？",
    "control_8.25": "安全開發生命週期（SDLC）的要求為何？",
    "clause_6.1":   "如何執行 ISO 27001 的風險評鑑？",
    "clause_8.2":   "資訊安全風險評鑑流程應如何文件化？",
    "clause_8.3":   "風險處理計畫需要涵蓋哪些內容？",
    "clause_9.1":   "ISMS 的監視與量測指標應如何設計？",
    "clause_9.2":   "內部稽核計畫如何制定？需要哪些稽核證據？",
    "clause_9.3":   "管理審查應包含哪些輸入與輸出項目？",
    "clause_10.1":  "不符合事項的矯正措施流程應如何執行？",
}


class RecommendationEngine:
    def __init__(
        self,
        graph_path: str = GRAPH_PATH,
        faq_path: str = FAQ_PATH,
        max_recs: int = 3,
    ):
        self.max_recs = max_recs
        self._graph: Dict = {}
        self._faq_map: Dict[str, List[str]] = {}  # clause_id → [question, ...]

        self._load_graph(graph_path)
        self._load_faq(faq_path)

    def _load_graph(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._graph = {k: v for k, v in data.items() if not k.startswith("_")}

    def _load_faq(self, path: str):
        """建立 clause_id → questions 的反向索引，用於推薦真實 FAQ 問題。"""
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            faq = json.load(f)
        for item in faq.get("items", []):
            for cid in item.get("clause_ids", []):
                self._faq_map.setdefault(cid, []).append(item["question"])

    def _get_question_for(self, clause_id: str) -> Optional[str]:
        """取得 clause_id 對應的問題（優先 FAQ，其次 fallback）。"""
        faq_qs = self._faq_map.get(clause_id, [])
        if faq_qs:
            return faq_qs[0]
        return _FALLBACK_QUESTIONS.get(clause_id)

    def recommend(self, clause_ids: List[str]) -> List[Dict]:
        """
        根據命中的條文 ID 列表，回傳推薦問題清單。
        每筆格式：{question, clause_id, reason, cluster}
        """
        if not self._graph or not clause_ids:
            return []

        candidate_ids: List[str] = []
        seen = set(clause_ids)

        # 收集 next（優先）和 related（次要）
        for cid in clause_ids:
            node = self._graph.get(cid, {})
            for nid in node.get("next", []):
                if nid not in seen:
                    candidate_ids.append(("next", nid, node.get("cluster", "")))
                    seen.add(nid)
            for rid in node.get("related", []):
                if rid not in seen:
                    candidate_ids.append(("type_related", rid, node.get("cluster", "")))
                    seen.add(rid)

        # 取前 max_recs 個有對應問題的候選
        recs = []
        for rel_type, cid, cluster in candidate_ids:
            q = self._get_question_for(cid)
            if not q:
                continue
            node = self._graph.get(cid, {})
            reason = (
                "建議下一步" if rel_type == "next"
                else f"同屬「{node.get('cluster', cluster)}」主題"
            )
            recs.append({
                "question":  q,
                "clause_id": cid,
                "reason":    reason,
                "cluster":   node.get("cluster", cluster),
            })
            if len(recs) >= self.max_recs:
                break

        return recs


if __name__ == "__main__":
    engine = RecommendationEngine()
    # 測試：問了備份相關問題，應推薦業務持續/日誌/容量管理
    test_ids = ["control_8.13"]
    recs = engine.recommend(test_ids)
    print(f"測試：命中 {test_ids}")
    for r in recs:
        print(f"  [{r['clause_id']}] {r['question'][:50]}... ({r['reason']})")
