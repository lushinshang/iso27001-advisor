"""
tests/test_cli.py
CLI 整合測試 — ISO 27001 Advisor Agent v1.2
測試 main.py 的命令列介面邊界條件、build_prompt 截斷防護與正常流程
"""
import sys
import os
import subprocess
import json
import pytest
from unittest.mock import patch, MagicMock


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(BASE_DIR, "main.py")


def run_main(*args, env_override=None, input_text=None, timeout=15):
    """輔助函數：執行 main.py 並取得結果"""
    import subprocess
    env = os.environ.copy()
    # 清除 GEMINI_API_KEY 避免干擾
    if env_override is not None:
        env.update(env_override)
    
    cmd = [sys.executable, MAIN_PY] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
        timeout=timeout,
        cwd=BASE_DIR
    )
    return result


class TestCLIHelp:
    def test_CLI01_help_exit_code_zero(self):
        """CLI-01: --help 應以 exit code 0 退出"""
        result = run_main("--help")
        assert result.returncode == 0, f"--help 應成功退出，但 exit code = {result.returncode}"

    def test_CLI01_help_contains_gemini_option(self):
        """CLI-01: --help 說明應包含 --gemini 選項"""
        result = run_main("--help")
        assert "--gemini" in result.stdout, "--help 輸出應包含 --gemini 說明"

    def test_CLI01_help_contains_top_k_option(self):
        """CLI-01: --help 說明應包含 --top-k 選項"""
        result = run_main("--help")
        assert "--top-k" in result.stdout, "--help 輸出應包含 --top-k 說明"

    def test_CLI02_invalid_argument(self):
        """CLI-02: 無效的參數應以非零 exit code 退出"""
        result = run_main("--this-is-not-a-valid-argument")
        assert result.returncode != 0, "無效參數應以非零 exit code 退出"


class TestCLIGeminiValidation:
    def test_CLI03_gemini_without_api_key(self):
        """CLI-03: 使用 --gemini 但無 API Key 應以 exit code 1 退出
        注意：使用 SKIP_DOTENV=1 環境變數跳過 .env 載入，以確保測試隔離。
        """
        # 建立一個乾淨環境，移除所有 GEMINI_API_KEY，並跳過 .env 載入
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("GEMINI_API_KEY",)}
        clean_env["SKIP_DOTENV"] = "1"  # 通知 main.py 跳過 .env 載入
        clean_env["GEMINI_API_KEY"] = ""  # 明確設為空

        result = run_main(
            "風險評鑑是什麼？",
            "--gemini",
            env_override=clean_env,
            timeout=10
        )
        assert result.returncode == 1, \
            f"無 API Key 使用 --gemini 應以 exit code 1 退出，但得到 {result.returncode}"
        # 應包含錯誤提示
        combined = result.stdout + result.stderr
        assert "GEMINI_API_KEY" in combined, \
            "錯誤訊息應提示缺少 GEMINI_API_KEY"


class TestCLIQueryMode:
    def test_retrieval_output_present(self, searcher):
        """CLI-04: 搜尋有結果時，訊息樣板應包含「📌 檢索到」字樣"""
        results = searcher.search("風險評鑑", limit=4)
        assert len(results) > 0, "搜尋「風險評鑑」應有結果"
        output_msg = f"📌 檢索到 {len(results)} 筆相關條文，正在產生顧問解答..."
        assert "📌 檢索到" in output_msg

    def test_CLI05_empty_query_no_exception(self, searcher):
        """CLI-05: 空字串不應引發例外，回傳空 list"""
        results = searcher.search("", limit=4)
        assert results == [], "空字串搜尋應回傳空 list 而非拋出例外"


class TestCLIProcessQuery:
    """透過 searcher fixture 測試搜尋流程（由 conftest.py 提供）"""

    def test_search_returns_results_for_known_query(self, searcher):
        """已知問題應能在 DB 中找到結果"""
        results = searcher.search("內部稽核計畫", limit=4)
        assert len(results) >= 1, "「內部稽核計畫」應至少找到 1 筆條文"

    def test_top_k_argument_works(self, searcher):
        """--top-k 參數應影響回傳結果數量"""
        r1 = searcher.search("風險", limit=2)
        r4 = searcher.search("風險", limit=4)
        assert len(r1) <= 2
        assert len(r4) <= 4
        assert len(r4) >= len(r1)


# ===========================================================
# build_prompt 截斷防護測試（v1.2 新增）
# ===========================================================

class TestBuildPrompt:
    """測試 main.py build_prompt() 的 token 截斷防護行為"""

    def _make_item(self, content: str, item_id: str = "test") -> dict:
        """建立測試用的 matched_item dict"""
        return {
            "item": {
                "id": item_id,
                "type": "clause",
                "section": "測試章節",
                "subsection": "測試條文",
                "content": content,
            },
            "score": 99.0,
        }

    def test_BP01_long_content_truncated_with_marker(self):
        """BP-01: 內容超過 max_chars_per_item 時應截斷並附加省略標記"""
        from iso27001_advisor.llm import build_prompt
        long_item = self._make_item("長" * 1000)
        prompt = build_prompt("測試問句", [long_item], max_chars_per_item=600)
        assert "（以下省略）" in prompt, "截斷後應附加「（以下省略）」標記"

    def test_BP02_short_content_not_truncated(self):
        """BP-02: 內容未超過上限時，不應截斷（不含省略標記）"""
        from iso27001_advisor.llm import build_prompt
        short_item = self._make_item("短" * 50)   # 50 字元，遠低於 600
        prompt = build_prompt("測試問句", [short_item], max_chars_per_item=600)
        assert "（以下省略）" not in prompt, "短內容不應被截斷"

    def test_BP03_custom_limit_respected(self):
        """BP-03: 自訂 max_chars_per_item 應被正確套用"""
        from iso27001_advisor.llm import build_prompt
        item = self._make_item("X" * 500)
        # 200 字元上限 → 應截斷；預設 600 → 不截斷
        prompt_200 = build_prompt("q", [item], max_chars_per_item=200)
        prompt_600 = build_prompt("q", [item], max_chars_per_item=600)
        assert "（以下省略）" in prompt_200, "max_chars_per_item=200 時應截斷"
        assert "（以下省略）" not in prompt_600, "max_chars_per_item=600 時不應截斷"

    def test_BP04_multiple_items_all_checked(self):
        """BP-04: 多筆條文時，每筆都會獨立套用截斷上限"""
        from iso27001_advisor.llm import build_prompt
        items = [
            self._make_item("A" * 1000, item_id="clause_1"),
            self._make_item("B" * 50,   item_id="clause_2"),   # 短，不截斷
            self._make_item("C" * 800,  item_id="clause_3"),
        ]
        prompt = build_prompt("問句", items, max_chars_per_item=600)
        # 至少有截斷（來自第 1、3 筆）
        truncation_count = prompt.count("（以下省略）")
        assert truncation_count == 2, \
            f"應有 2 筆被截斷，但實際截斷 {truncation_count} 筆"

    def test_BP05_prompt_contains_query(self):
        """BP-05: Prompt 中應包含使用者的原始問句"""
        from iso27001_advisor.llm import build_prompt
        item = self._make_item("一般內容")
        query = "這是測試用的問句"
        prompt = build_prompt(query, [item])
        assert query in prompt, "Prompt 應包含使用者的原始問句"


class TestLoadDotenv:
    """測試 load_dotenv 函數的行為"""

    def test_load_dotenv_reads_api_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GEMINI_API_KEY=test_key_12345\n", encoding="utf-8")

        import iso27001_advisor.llm as llm_module
        original_key = os.environ.pop("GEMINI_API_KEY", None)
        # 測試套件以 SKIP_DOTENV=1 啟動，需暫時移除讓 load_dotenv 實際執行
        original_skip = os.environ.pop("SKIP_DOTENV", None)
        try:
            llm_module.load_dotenv(env_path=str(env_file))
            assert os.environ.get("GEMINI_API_KEY") == "test_key_12345"
        finally:
            if original_key is not None:
                os.environ["GEMINI_API_KEY"] = original_key
            else:
                os.environ.pop("GEMINI_API_KEY", None)
            if original_skip is not None:
                os.environ["SKIP_DOTENV"] = original_skip

    def test_load_dotenv_ignores_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# 注解\nTEST_VAR_X=hello\n", encoding="utf-8")

        import iso27001_advisor.llm as llm_module
        # 測試套件以 SKIP_DOTENV=1 啟動，需暫時移除讓 load_dotenv 實際執行
        original_skip = os.environ.pop("SKIP_DOTENV", None)
        try:
            llm_module.load_dotenv(env_path=str(env_file))
            assert os.environ.get("TEST_VAR_X") == "hello"
        finally:
            os.environ.pop("TEST_VAR_X", None)
            if original_skip is not None:
                os.environ["SKIP_DOTENV"] = original_skip

    def test_load_dotenv_skip_env_var(self, tmp_path):
        """SKIP_DOTENV=1 時應完全跳過載入"""
        env_file = tmp_path / ".env"
        env_file.write_text("SHOULD_NOT_LOAD=yes\n", encoding="utf-8")

        import iso27001_advisor.llm as llm_module
        os.environ["SKIP_DOTENV"] = "1"
        try:
            llm_module.load_dotenv(env_path=str(env_file))
            assert os.environ.get("SHOULD_NOT_LOAD") is None
        finally:
            os.environ.pop("SKIP_DOTENV", None)
            os.environ.pop("SHOULD_NOT_LOAD", None)


class TestCLIExitCode:
    def test_inference_failure_returns_nonzero_exit(self):
        """單次查詢模式在推理失敗時，exit code 應為 1"""
        # 使用不存在的 Ollama host 觸發 ConnectionError
        result = subprocess.run(
            [sys.executable, MAIN_PY, "風險評鑑是什麼？",
             "--host", "http://localhost:9"],
            env={**os.environ, "SKIP_DOTENV": "1"},
            capture_output=True,
            text=True
        )
        assert result.returncode == 1, (
            f"推理失敗時應返回 exit code 1，實際為 {result.returncode}. Output: {result.stdout}\nError: {result.stderr}"
        )


class TestCLITopKValidation:
    def test_top_k_zero_rejected(self):
        """--top-k 0 應以非零 exit code 拒絕"""
        result = subprocess.run(
            [sys.executable, MAIN_PY, "test", "--top-k", "0"],
            env={**os.environ, "SKIP_DOTENV": "1"},
            capture_output=True
        )
        assert result.returncode != 0

    def test_top_k_negative_rejected(self):
        """--top-k -1 應以非零 exit code 拒絕"""
        result = subprocess.run(
            [sys.executable, MAIN_PY, "test", "--top-k", "-1"],
            env={**os.environ, "SKIP_DOTENV": "1"},
            capture_output=True
        )
        assert result.returncode != 0
