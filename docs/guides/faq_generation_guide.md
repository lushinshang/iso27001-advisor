# ISO 27001 Advisor — FAQ 問答集資料工程與自動化生成指南

> [!TIP]
> 整理 FAQ 問答集最有效率、且品質最高的方法是：**「利用現有的結構化條文庫，透過 LLM (Gemini) 自動化批次生成 FAQ 問題與標準答案」**。

---

## 1. FAQ 資料庫格式設計 (Schema)

一個標準的 FAQ 快取資料庫 `faq_database.json` 應包含以下格式，以便於前端直接渲染與後端向量檢索：

```json
[
  {
    "id": "faq_001",
    "associated_clause": "control_8.13",
    "category": "資訊備份",
    "question": "ISO 27001 對於備份有哪些具體要求？稽核時需要提供什麼證據？",
    "answer": "### 🎯 諮詢問題分析\n組織必須確保資訊、軟體及系統映像檔在發生意外時能安全復原...\n\n### 🛠️ 文件缺口與稽核證據建議\n- **文件缺口**：需備妥「備份管理程序書」...\n- **稽核證據**：最近三個月的備份成功日誌、年度備份還原測試報告..."
  }
]
```

---

## 2. 自動化生成腳本：利用 Gemini 批次產出 FAQ

我們可以寫一個簡單的 Python 腳本 `generate_faq.py`。它會讀取您現有的 [iso27001_structure.json](file:///Users/lanss/projects/2_Practice/5-Day%20AI%20Agents%20Intensive%20Course%20with%20Google%282026%29/iso27001-advisor/iso27001_structure.json)，並將每條規範送給 Gemini，自動產生 2~3 個熱門 FAQ 與完美標準答案。

### 🐍 `generate_faq.py` 腳本原型：

```python
import json
import os
import urllib.request
import time

def call_gemini_api(prompt, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json"  # 強制 Gemini 回傳 JSON 格式
        }
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        res = json.loads(response.read().decode('utf-8'))
        text = res['candidates'][0]['content']['parts'][0]['text']
        return json.loads(text)

def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ 請先設定 GEMINI_API_KEY 環境變數")
        return

    # 讀取條文庫
    with open("iso27001_structure.json", "r", encoding="utf-8") as f:
        structure = json.load(f)

    faq_database = []
    
    # 範例：先針對前 5 個控制項進行測試生成，成功再擴大到全部
    test_items = [i for i in structure if i["type"] == "control"][:5]

    for idx, item in enumerate(test_items, 1):
        print(f"正在為 {item['id']} ({item['subsection']}) 生成 FAQ...")
        
        prompt = f"""
        你是一位 ISO 27001 資深主導稽核員。請根據以下條款，生成 2 個企業在合規過程中，最常詢問的 FAQ 問答。
        
        【條款內容】
        ID: {item['id']}
        名稱: {item['subsection']}
        內容: {item['content']}
        
        【輸出 JSON 格式】
        請嚴格回傳一個 JSON Array，格式如下：
        [
          {{
            "question": "企業最常詢問的口語化諮詢問題？",
            "answer": "一份排版精美、使用 Markdown 語法的完美顧問標準解答（包含諮詢問題分析、文件缺口與稽核證據建議、合規免責警示）"
          }}
        ]
        """
        
        try:
            faqs = call_gemini_api(prompt, api_key)
            for faq in faqs:
                faq_database.append({
                    "id": f"faq_{len(faq_database) + 1:03d}",
                    "associated_clause": item["id"],
                    "category": item["title"],
                    "question": faq["question"],
                    "answer": faq["answer"]
                })
            time.sleep(1) # 避免觸發 API 頻率限制
        except Exception as e:
            print(f"生成 {item['id']} 失敗: {e}")

    # 儲存 FAQ 資料庫
    with open("faq_database.json", "w", encoding="utf-8") as f:
        json.dump(faq_database, f, ensure_ascii=False, indent=2)
    print(f"🎉 成功！已生成 {len(faq_database)} 筆 FAQ，儲存至 faq_database.json")

if __name__ == "__main__":
    main()
```

---

## 3. 在 Web UI 後端中如何實作這道 FAQ 快取？

當您生成好 `faq_database.json` 後，您只需在後端 `app.py` 的 `/api/chat` 開頭加入簡單的比對：

```python
# 1. 載入 FAQ 資料庫
with open("faq_database.json", "r", encoding="utf-8") as f:
    faq_db = json.load(f)

# 2. 在對話端點進行語意比對
@app.post("/api/chat")
async def chat_endpoint(request: Request):
    ...
    # (可選) 使用與您的搜尋器相似的 TF-IDF/BM25 算法比對 query 與 faq_db 中的 question。
    # 如果相似度分數極高（例如命中同義詞與關鍵字）：
    # 直接回傳：
    # yield f"data: {json.dumps({'type': 'references', 'data': [關聯的條文資訊]})}\n\n"
    # yield f"data: {json.dumps({'type': 'chunk', 'data': 該預設的完美 answer})}\n\n"
    # yield f"data: {json.dumps({'type': 'done'})}\n\n"
```
這在效能上將會是非常大的跨越！
