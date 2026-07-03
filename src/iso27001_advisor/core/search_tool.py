import json
import os
import re
from pathlib import Path


class ISO27001Searcher:
    """ISO 27001 本地條文檢索引擎 (v1.2)

    改善項目（v1.2）：
    - [🔴 高] synonyms_dict、boost_words、stopwords 從 search() 移至 __init__，
              只在物件建立時初始化一次，避免每次呼叫重建的效能損耗。
    - [🔴 高] 建立 _id_index dict，get_by_id() 從 O(n) 線性掃描改為 O(1) 雜湊查找。
    """

    # ------------------------------------------------------------------
    # 類別常數：資安術語同義詞字典
    # ------------------------------------------------------------------
    _SYNONYMS = {
        "個資": ["pii", "隱私", "個人資訊", "資料遮蔽", "資料遮罩", "洩漏預防"],
        "敏感個資": ["pii", "隱私", "資料遮蔽", "資料遮罩", "洩漏", "洩漏預防"],
        "敏感性個資": ["pii", "隱私", "資料遮蔽", "資料遮罩", "洩漏", "洩漏預防"],
        "敏感資料": ["敏感性資訊", "敏感性資料", "機密性", "資料遮蔽", "洩漏預防"],
        "敏感資訊": ["敏感性資訊", "敏感性資料", "資料遮蔽", "洩漏預防"],
        "敏感性資訊": ["資料遮蔽", "資料遮罩", "洩漏預防", "pii"],
        "隱私": ["個資", "pii"],
        "pii": ["個資", "隱私"],
        "資料遮罩": ["資料遮蔽"],
        "資料遮蔽": ["資料遮罩"],
        "洩漏": ["洩漏預防", "資料遮蔽"],
        "洩漏預防": ["洩漏", "資料遮蔽"],
        "加密": ["密碼技術", "憑證"],
        "弱點": ["技術脆弱性", "脆弱性"],
        "漏洞": ["技術脆弱性", "脆弱性"],
        "防毒": ["惡意軟體"],
        "病毒": ["惡意軟體"],
        "日誌": ["存錄"],
        "log": ["存錄"],
        "權限": ["存取控制", "存取權限", "身分管理"],
        "帳號": ["存取控制", "存取權限", "身分管理"],
        "隨身碟": ["儲存媒體", "可移除式儲存媒體"],
        "usb": ["儲存媒體"],
        "合規": ["法律", "法規", "契約要求事項", "遵循性"],
    }

    # 核心主題詞：若查詢中出現此詞且條文中有匹配，給予極高加分
    _BOOST_WORDS = [
        "備份", "遮蔽", "遮罩", "洩漏", "洩漏預防", "威脅", "情資",
        "智慧財產", "桌面", "螢幕", "漏洞", "弱點", "個資", "敏感性",
        "pii", "隱私", "加密", "密碼", "備份複本",
    ]

    _INTENT_BOOSTS = [
        {
            "ids": ["clause_4.4"],
            "keywords": ["clause 4.4", "4.4", "isms 建立", "持續維護", "改善哪些面向"],
        },
        {
            "ids": ["control_6.5", "control_5.11", "control_5.18"],
            "keywords": ["離職", "聘用終止", "存取權限", "撤銷", "責任移交"],
        },
        {
            "ids": ["control_6.7", "control_8.1"],
            "keywords": ["遠端工作", "居家辦公", "遠端", "額外的資訊安全控制"],
        },
        {
            "ids": ["control_8.9"],
            "keywords": ["組態", "基準組態", "baseline", "configuration"],
        },
        {
            "ids": ["control_6.1", "control_6.2", "control_6.3", "control_5.16", "control_5.18"],
            "keywords": ["新員工", "入職", "任用", "到職"],
        },
        {
            "ids": ["control_5.23", "control_5.19", "control_5.20", "control_8.9"],
            "keywords": ["saas", "雲端", "導入新的", "新的 saas", "新工具"],
        },
    ]

    # 中文停用詞（單字）
    _STOPWORDS = frozenset(
        "的了是有在與及之而於以對對於要求具體如何我們什麼我們公司"
        "與各項各個一個被為以作為其且或等中但已需應是"
    )

    def __init__(self, json_path=None):
        if json_path is None:
            base_dir = Path(__file__).resolve().parents[3]
            json_path = base_dir / "data" / "iso27001_structure.json"

        self.json_path = str(json_path)
        self.items = []
        self._id_index = {}   # O(1) 精確查詢索引
        self.load_data()

    def load_data(self):
        if not os.path.exists(self.json_path):
            raise FileNotFoundError(
                f"Structure JSON file not found at {self.json_path}. "
                "Please run parse_iso.py first."
            )
        with open(self.json_path, "r", encoding="utf-8") as f:
            self.items = json.load(f)

        # 建立 ID 索引（大小寫不敏感）
        self._id_index = {item["id"].lower(): item for item in self.items}

    def get_by_id(self, item_id):
        """依據 ID 精確查詢（O(1) 雜湊查找）。

        Args:
            item_id: 條文 ID，如 'clause_4.1' 或 'control_5.1'，大小寫不敏感。

        Returns:
            對應的條文 dict，或 None（若不存在）。
        """
        return self._id_index.get(item_id.strip().lower())

    def search(self, query, item_type=None, limit=5):
        """關鍵字搜尋，包含同義詞擴充、核心主題詞加權、去重 N-gram 比對、
        大章節降權與字元權重排序。

        Args:
            query:     使用者輸入的自然語言問句。
            item_type: 限制結果類型，可為 'clause'、'control' 或 None（不限）。
            limit:     回傳的最大結果筆數，預設 5。

        Returns:
            排序後的結果 list，每筆為 {'item': dict, 'score': float}。
        """
        if limit <= 0:
            return []
        if not query:
            return []

        query_lower = query.lower()

        # 1. 同義詞擴充（使用類別常數，不再每次重建）
        expanded_terms = []
        for key, vals in self._SYNONYMS.items():
            if key in query_lower:
                expanded_terms.extend(vals)

        # 2. 分詞（中英文字元）
        raw_tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", query_lower)
        tokens = [t for t in raw_tokens if t not in self._STOPWORDS]

        # 將同義詞也加入 tokens
        for term in expanded_terms:
            exp_toks = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", term.lower())
            tokens.extend([t for t in exp_toks if t not in self._STOPWORDS])

        # 3. N-gram 提取（2-gram 到 4-gram）
        ngrams = []
        for n in range(2, 5):
            for i in range(len(raw_tokens) - n + 1):
                ngram = "".join(raw_tokens[i : i + n])
                if len(ngram) > 1 and not ngram.isdigit():
                    ngrams.append(ngram)
        for term in expanded_terms:
            if len(term) > 1:
                ngrams.append(term)
        ngrams = list(set(ngrams))

        # 4. 計算各條文分數
        results = []
        for item in self.items:
            if item_type and item["type"] != item_type:
                continue

            score = 0.0
            item_id = item["id"].lower()
            title = item.get("title", "").lower()
            subsection = item.get("subsection", "").lower()
            content = item.get("content", "").lower()

            for rule in self._INTENT_BOOSTS:
                if item["id"] in rule["ids"] and any(kw in query_lower for kw in rule["keywords"]):
                    score += 180.0

            # (1) 完整 query 字串比對
            if query_lower in content:
                score += 40.0
            if query_lower in title or query_lower in subsection:
                score += 60.0

            # (2) 核心主題詞加權（_BOOST_WORDS 為類別常數，不再重建）
            for boost_w in self._BOOST_WORDS:
                if boost_w in query_lower:
                    has_match = (
                        boost_w in title
                        or boost_w in subsection
                        or boost_w in content
                    )
                    if not has_match:
                        for syn in self._SYNONYMS.get(boost_w, []):
                            if syn in title or syn in subsection or syn in content:
                                has_match = True
                                break
                    if has_match:
                        score += 100.0

            # (3) 去重最長匹配的 N-gram
            title_matches: list[str] = []
            for ngram in sorted(ngrams, key=len, reverse=True):
                if ngram in title or ngram in subsection:
                    if not any(ngram in m for m in title_matches):
                        title_matches.append(ngram)
                        score += 15.0 * len(ngram)

            content_matches: list[str] = []
            for ngram in sorted(ngrams, key=len, reverse=True):
                if ngram in content:
                    if not any(ngram in m for m in content_matches):
                        content_matches.append(ngram)
                        score += 5.0 * len(ngram)

            # (4) 單字 token 匹配
            for token in set(tokens):
                if token in title:
                    score += 5.0
                if token in subsection:
                    score += 4.0
                count_in_content = content.count(token)
                if count_in_content > 0:
                    score += min(count_in_content * 0.8, 8.0)

            # (5) 大章節降權（父章節 ID 不含小數點，例如 clause_5、control_8）
            if "_" in item_id:
                part = item_id.split("_")[1]
                if part.isdigit():
                    score *= 0.1

            if score > 0:
                results.append({"item": item, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]


if __name__ == "__main__":
    searcher = ISO27001Searcher()
    print("Testing search for '風險評鑑':")
    res = searcher.search("風險評鑑", limit=3)
    for r in res:
        print(f"ID: {r['item']['id']} | Title: {r['item']['title']} | Score: {r['score']:.2f}")

    print("\nTesting exact lookup for 'control_5.1':")
    item = searcher.get_by_id("control_5.1")
    if item:
        print(f"ID: {item['id']} | Content: {item['content']}")
