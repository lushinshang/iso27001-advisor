"""
tests/conftest.py
共用 pytest fixtures — ISO 27001 Advisor Agent v1.2

將三個測試檔中重複定義的 `searcher` fixture 集中於此，
pytest 會自動發現並提供給同目錄下所有測試使用。
"""
import os
import pytest

from iso27001_advisor.core.search_tool import ISO27001Searcher


@pytest.fixture(scope="session")
def searcher():
    """全 session 共用的 ISO27001Searcher 實例。

    scope="session" 表示整個測試 session 只建立一次，
    節省重複讀取 iso27001_structure.json 的 I/O 與初始化時間。
    """
    return ISO27001Searcher()


@pytest.fixture(scope="session")
def eval_dataset():
    """全 session 共用的評估資料集。

    從 eval_dataset.json 讀取，提供給 test_recall_regression.py 使用。
    """
    import json
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dataset_path = os.path.join(base_dir, "data", "eval_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)
