import os
import json
import glob
import numpy as np
import requests
import time
from pathlib import Path

# 若沒有安裝 docling，請先執行: pip install docling
try:
    from docling.document_converter import DocumentConverter
except ImportError:
    print("❌ 錯誤：尚未安裝 docling。請先在終端機執行：pip install docling")
    exit(1)

# ==========================================
# 🛠️ 第一步：配置設定 (您可以在此修改模型名稱)
# ==========================================
PDF_DIR = "../new_pdfs"                 # 您放置 PDF 的資料夾
OUTPUT_DIR = "../custom_data"           # 產出檔案會放在這裡

# 根據您的 Ollama 清單推薦的模型
EMBEDDING_MODEL = "jeffh/intfloat-multilingual-e5-large-instruct:f16"
GRAPH_MODEL = "gemma4:12b-it-qat-16k"
OLLAMA_API_BASE = "http://localhost:11434/api"

# ==========================================
# 🚀 執行工具開始
# ==========================================
def ensure_directories():
    os.makedirs(PDF_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def step1_convert_pdfs():
    print("\n⏳ [階段 1/3] 正在使用 IBM Docling 將 PDF 轉換成文字 (Markdown)...")
    pdf_files = glob.glob(os.path.join(PDF_DIR, "*.pdf"))
    if not pdf_files:
        print(f"⚠️ 在 {PDF_DIR} 找不到任何 PDF 檔案！請把 PDF 放進去後再執行一次。")
        exit(1)

    converter = DocumentConverter()
    all_chunks = []
    chunk_id = 0

    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        print(f"  📄 正在轉換: {filename}")
        try:
            # 使用 Docling 轉換 PDF
            result = converter.convert(pdf_path)
            md_text = result.document.export_to_markdown()
            
            # 簡單的切片邏輯：依照 Markdown 標題 (##) 切割，或是以空行段落切割
            paragraphs = md_text.split('\n\n')
            current_chunk = ""
            for p in paragraphs:
                if len(current_chunk) + len(p) < 1000:
                    current_chunk += p + "\n\n"
                else:
                    if current_chunk.strip():
                        all_chunks.append({"id": f"doc_{chunk_id}", "source": filename, "content": current_chunk.strip()})
                        chunk_id += 1
                    current_chunk = p + "\n\n"
            if current_chunk.strip():
                all_chunks.append({"id": f"doc_{chunk_id}", "source": filename, "content": current_chunk.strip()})
                chunk_id += 1
        except Exception as e:
            print(f"  ❌ 轉換 {filename} 時發生錯誤: {e}")

    # 儲存 knowledge_base.json
    kb_path = os.path.join(OUTPUT_DIR, "knowledge_base.json")
    with open(kb_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"✅ 轉換完成！共切出 {len(all_chunks)} 個段落，存檔於 {kb_path}")
    return all_chunks

def step2_generate_embeddings(chunks):
    print(f"\n⏳ [階段 2/3] 正在呼叫 Ollama ({EMBEDDING_MODEL}) 進行語意向量轉換...")
    embeddings = []
    
    for i, chunk in enumerate(chunks):
        print(f"  🧠 正在轉換進度: {i+1}/{len(chunks)}", end="\r")
        text = chunk["content"]
        try:
            response = requests.post(f"{OLLAMA_API_BASE}/embeddings", json={
                "model": EMBEDDING_MODEL,
                "prompt": text
            })
            if response.status_code == 200:
                vector = response.json().get("embedding")
                embeddings.append(vector)
            else:
                print(f"\n  ❌ Ollama 錯誤 (這可能是模型尚未拉取，請確定模型存在)")
                # 給一個預設的全 0 向量以防崩潰
                embeddings.append([0.0] * 1024) 
        except Exception as e:
            print(f"\n  ❌ 呼叫 Ollama API 失敗: {e}。請確認 Ollama 有在背景執行！")
            exit(1)
            
    print("\n✅ 向量轉換完成！")
    # 儲存 embeddings.npy
    npy_path = os.path.join(OUTPUT_DIR, "embeddings.npy")
    np.save(npy_path, np.array(embeddings, dtype=np.float32))
    print(f"✅ 向量陣列已存檔於 {npy_path}")

def step3_extract_graph(chunks):
    print(f"\n⏳ [階段 3/3] 正在呼叫 Ollama ({GRAPH_MODEL}) 自動萃取知識圖譜...")
    print("  這需要一點時間，您可以去泡杯咖啡 ☕")
    
    graph_nodes = []
    graph_edges = []
    
    # 為了節省時間，這裡示範將相鄰的 chunk 進行簡單關聯萃取
    # 實務上會透過 prompt 請 AI 給出 JSON，此處提供 AI 呼叫範本
    for i in range(min(5, len(chunks))): # 這裡只示範前 5 個以防等待過久，您可自行拿掉限制
        prompt = f"""
請分析以下法規條文，並以簡短的一句話總結其核心控制目標：
條文內容：
{chunks[i]['content'][:500]}
"""
        try:
            response = requests.post(f"{OLLAMA_API_BASE}/generate", json={
                "model": GRAPH_MODEL,
                "prompt": prompt,
                "stream": False
            })
            summary = response.json().get("response", "").strip()
            
            graph_nodes.append({
                "id": chunks[i]["id"],
                "label": summary[:20] + "...",
                "source": chunks[i]["source"]
            })
            
            # 將相鄰節點連線建立基礎圖譜
            if i > 0:
                graph_edges.append({
                    "source": chunks[i-1]["id"],
                    "target": chunks[i]["id"],
                    "relation": "next_section"
                })
        except Exception as e:
            pass

    graph_data = {
        "nodes": graph_nodes,
        "edges": graph_edges
    }
    
    graph_path = os.path.join(OUTPUT_DIR, "custom_graph.json")
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 圖譜萃取完成！存檔於 {graph_path}")

# ==========================================
# 🏁 主程式進入點
# ==========================================
if __name__ == "__main__":
    print("======================================================")
    print(" 🤖 專屬 AI 顧問全自動建置工具 (No-Code 版本) ")
    print("======================================================")
    ensure_directories()
    
    print(f"👉 第一步：請確認您已將 PDF 檔案放進了 {os.path.abspath(PDF_DIR)} 資料夾中。")
    input("按下 Enter 鍵開始全自動轉換流程...")
    
    chunks = step1_convert_pdfs()
    step2_generate_embeddings(chunks)
    step3_extract_graph(chunks)
    
    print("\n🎉 恭喜！所有客製化資料已全部準備完畢！")
    print(f"請前往 {os.path.abspath(OUTPUT_DIR)} 查看您的三大核心檔案。")
    print("接下來，只要將原本系統設定檔的路徑指向這個資料夾，您的新顧問就能正式上線囉！")
