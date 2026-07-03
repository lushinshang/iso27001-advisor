import argparse
import os
import sys
import urllib.request

from iso27001_advisor.core.search_tool import ISO27001Searcher
from iso27001_advisor.core.semantic_cache import SemanticCache
from iso27001_advisor.llm import (
    build_prompt,
    call_gemini,
    call_ollama,
    get_system_prompt,
    load_dotenv,
    map_reduce_query,
)

def _positive_int(value):
    """argparse type validator：確保為正整數。"""
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"必須為整數，收到: {value}")
    if ivalue < 1:
        raise argparse.ArgumentTypeError(
            f"--top-k 必須為正整數（≥ 1），收到: {value}"
        )
    return ivalue

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="ISO 27001 Advisor Agent - 本地問答 CLI")
    parser.add_argument("query", nargs="?", type=str, help="您的諮詢問題。如果不提供，將進入互動模式。")
    parser.add_argument("--model", type=str, default="gemma3:12b-16k", help="Ollama 模型名稱，預設為 gemma3:12b-16k")
    parser.add_argument("--host", type=str, default="http://localhost:11434", help="Ollama API 位址，預設為 http://localhost:11434")
    parser.add_argument("--gemini", action="store_true", help="使用 Gemini API 作為推理後端（需設定 GEMINI_API_KEY 環境變數）")
    parser.add_argument("--gemini-model", type=str, default="gemini-2.5-pro", help="Gemini 模型名稱，預設為 gemini-2.5-pro")
    parser.add_argument("--top-k", type=_positive_int, default=4, help="檢索條文的數量，預設為 4")
    parser.add_argument("--deep", action="store_true", help="啟用深度分析模式（Map-Reduce），適合複雜跨條文問題")
    parser.add_argument("--no-cache", action="store_true", help="停用語意快取，強制走完整 RAG 流程")
    args = parser.parse_args()

    # 初始化搜尋器
    try:
        searcher = ISO27001Searcher()
    except Exception as e:
        print(f"初始化搜尋器失敗: {e}", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    use_gemini = args.gemini

    # 初始化語意快取（可選，index 不存在時靜默跳過）
    sem_cache = None
    if not args.no_cache and not use_gemini:
        try:
            sem_cache = SemanticCache(host=args.host)
        except Exception:
            pass
    
    # 如果使用者沒有指定 --gemini，但是設定了 GEMINI_API_KEY 且本地 Ollama 沒有運行，可以自動備用 Gemini
    if not use_gemini and api_key:
        # 測試 Ollama 是否可用，不可用則自動切換至 Gemini
        try:
            url = f"{args.host}/api/tags"
            urllib.request.urlopen(url, timeout=2)
        except Exception:
            print("💡 偵測到本地 Ollama 服務未啟動，但已設定 GEMINI_API_KEY，系統自動切換至 Gemini API 進行推理。")
            use_gemini = True

    if use_gemini and not api_key:
        print("❌ 錯誤: 使用 Gemini 推理需要設定 GEMINI_API_KEY 環境變數。", file=sys.stderr)
        sys.exit(1)

    def process_query(q) -> bool:
        if not q.strip():
            return True
            
        # 語意快取查詢（優先於 RAG）
        if sem_cache and sem_cache.is_ready:
            try:
                hit = sem_cache.search(q)
                if hit:
                    print(f"\n⚡ [快取命中] 相似度 {hit['similarity']}  FAQ: {hit['faq_id']}")
                    print("\n==================== 📖 ISO 27001 顧問解答 ====================")
                    print(hit["answer"])
                    print("\n==============================================================\n")
                    print(f"📋 【快取引用條文】{', '.join(hit['clause_ids'])}")
                    return True
            except Exception as e:
                print(f"  ⚠️  語意快取查詢失敗，改走 RAG：{e}", file=sys.stderr)

        print(f"\n🔍 正在檢索與「{q}」最相關的 ISO 27001 條文與控制措施...")
        matched = searcher.search(q, limit=args.top_k)
        
        if not matched:
            print("⚠️ 找不到與該關鍵字相關的條文。")
            return True
            
        mode_label = "深度分析 (Map-Reduce)" if args.deep and not use_gemini else "一般"
        print(f"📌 檢索到 {len(matched)} 筆相關條文，模式：{mode_label}，正在產生顧問解答...")

        # 呼叫推理後端
        try:
            print("\n==================== 📖 ISO 27001 顧問解答 ====================")
            if use_gemini:
                prompt = build_prompt(q, matched)
                ans = call_gemini(prompt, get_system_prompt(), api_key, model=args.gemini_model)
                print(ans)
            elif args.deep:
                ans = map_reduce_query(
                    q, matched,
                    model=args.model,
                    host=args.host,
                    on_progress=lambda msg: print(f"  ⚙️  {msg}", flush=True),
                    on_chunk=lambda c: print(c, end="", flush=True)
                )
            else:
                prompt = build_prompt(q, matched)
                ans = call_ollama(
                    prompt,
                    get_system_prompt(),
                    model=args.model,
                    host=args.host,
                    on_chunk=lambda c: print(c, end="", flush=True)
                )
            print("\n==============================================================\n")
            
            # 列出參考的條文 ID 作為附註
            print("📋 【本次回答所引用之條文依據】")
            for m in matched:
                item = m["item"]
                item_type = "條文" if item["type"] == "clause" else "控制措施"
                print(f"- [{item['id']}] {item['subsection']} ({item_type}, 分數: {m['score']:.2f})")
            print()
            
        except Exception as e:
            print(f"❌ 推理失敗: {e}", file=sys.stderr)
            if not use_gemini:
                print("💡 提示: 如果您要在本地運作 Ollama，請確認服務已啟動且已執行過 `ollama pull gemma2`。", file=sys.stderr)
            return False
        return True

    if args.query:
        # 單次 CLI 查詢模式
        success = process_query(args.query)
        if not success:
            sys.exit(1)
    else:
        # REPL 互動模式
        print("====================================================")
        print("🛡️  歡迎使用 ISO 27001 Advisor Agent - 離線顧問系統")
        print("  - 本地條文庫已載入")
        if use_gemini:
            print(f"  - 推理後端: Gemini API ({args.gemini_model})")
        else:
            print(f"  - 推理後端: Ollama 本地服務 ({args.model})")
        print("  - 輸入 'exit' 或 'quit' 可退出系統。")
        print("====================================================")
        
        while True:
            try:
                user_q = input("\n💬 請輸入您的 ISO 27001 合規諮詢問題: \n> ")
                if user_q.strip().lower() in ["exit", "quit"]:
                    print("👋 感謝使用，再見！")
                    break
                process_query(user_q)
            except KeyboardInterrupt:
                print("\n👋 感謝使用，再見！")
                break
            except Exception as e:
                print(f"發生未預期錯誤: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
