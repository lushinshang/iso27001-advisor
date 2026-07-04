import pytest
import re

def has_overlap(original: str, paraphrased: str, min_len: int = 6) -> bool:
    """檢查 paraphrased 是否包含 original 中連續 >= min_len 的字元片段（忽略空白、標點與專有名詞/行業詞）。"""
    ignored_patterns = [r"iso\s*27001", r"isms", r"資訊安全", r"資安", r"控制措施"]
    
    clean_orig = original.lower()
    clean_para = paraphrased.lower()
    
    for pat in ignored_patterns:
        clean_orig = re.sub(pat, "", clean_orig)
        clean_para = re.sub(pat, "", clean_para)
        
    clean_orig = "".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]+", clean_orig))
    clean_para = "".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]+", clean_para))
    
    if len(clean_orig) < min_len or len(clean_para) < min_len:
        return False
        
    for i in range(len(clean_orig) - min_len + 1):
        chunk = clean_orig[i : i + min_len]
        if chunk in clean_para:
            return True
    return False

def test_has_overlap():
    orig = "如何決定 ISMS 的適用範圍？我們需要考量哪些因素？"
    
    # 1. 包含大段抄襲
    para_bad = "我們會決定ISMS的範圍，並看看有哪些因素。"
    
    # 2. 完全沒有抄襲
    para_good = "怎樣界定資訊安全管理系統的範疇？在規劃時該評估哪些面向？"
    assert has_overlap(orig, para_good) is False
    
    # 3. 專有名詞與行業詞測試：原題包含 ISO 27001 與資訊安全，改寫也包含，但不算抄襲
    orig_iso = "ISO 27001 要求我們如何進行資訊安全風險評鑑？"
    para_iso = "根據 ISO 27001 標準，企業應採取何種方式來執行資訊安全風險評估？"
    assert has_overlap(orig_iso, para_iso) is False
    
    # 4. 如果包含除了專名與行業詞外的實質抄襲，仍要被抓出來
    para_iso_bad = "ISO 27001 要求我們如何進行資安維護？" # "要求我們如何進行" 排除專名後為 "要求我們如何進行" 8字
    assert has_overlap(orig_iso, para_iso_bad) is True
