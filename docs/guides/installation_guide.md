# 📥 本地部署與安裝說明手冊 (Installation Guide)
## ISO 27001 Advisor Agent — v1.2.0

本手冊指引您如何在本地（甚至是完全物理隔離的離線網段）環境部署與執行 **ISO 27001 Advisor Agent**。

---

## 1. 系統環境需求 (System Requirements)

- **作業系統**：macOS (Apple Silicon 最佳), Linux (Ubuntu 20.04+ 推薦), 或 Windows 10/11。
- **Python 環境**：Python 3.8 或以上版本（系統僅使用純標準庫，**無需安裝額外 pip 套件**）。
- **硬體建議**：
  - 本地運作 4B 模型：8GB RAM。
  - 本地運作 12B 模型（如 `gemma4`）：16GB+ RAM (或 8GB+ VRAM 顯示卡)。

---

## 2. 部署步驟 (Deployment Steps)

### 步驟一：獲取專案程式碼
將整個專案資料夾下載或複製到您本機的目錄中（例如 `/Users/lanss/projects/iso27001-advisor`）。

### 步驟二：安裝並啟動 Ollama (離線推理核心)
1. 前往 [Ollama 官方網站](https://ollama.com) 下載並安裝適合您 OS 的安裝檔。
2. 啟動 Ollama 應用程式。
3. 下載本次專案所使用的語言模型（請在終端機中執行）：
   ```bash
   # 下載預設模型
   ollama pull gemma2
   
   # 或下載您所擁有的高階對話模型
   ollama pull gemma4:12b-it-qat-16k
   ```

### 步驟三：配置 API 金鑰與敏感資訊保護 (Security Protection)
如果您希望在本地 Ollama 未啟動時，能自動備用切換至雲端的 Gemini API：
1. 在專案根目錄下建立一個 `.env` 檔案（此檔案已列於 `.gitignore` 中，以防止金鑰外洩到版本控制庫）：
2. 在終端機執行建立指令：
   ```bash
   echo 'GEMINI_API_KEY="您的_GEMINI_API_KEY_金鑰字串"' > .env
   ```
3. 專案根目錄內建了 `.gitignore` 配置，確保敏感性環境變數 `.env`、自動生成之評估結果 `eval_results.json`，以及 Python 快取目錄（如 `__pycache__`、`.pytest_cache`）不被意外提交，完全符合 ISO 27001 本身對機密性保護之控制要求。

### 步驟四：初始化資料庫 (Data Prep)
執行結構化腳本，將原始中文條文解析並輸出為可檢索 JSON 資料庫：
```bash
python3 parse_iso.py
```
*當您看見畫面顯示 `Structured data saved to .../iso27001_structure.json`，即代表資料庫初始化完成！*

---

## 3. 測試與驗證 (Verification & Testing)

### 3.1 執行評估指標
為了確保您的 RAG 檢索模組完全正常，請執行檢索品質評估腳本：
```bash
python3 evaluation.py
```
*執行後將同時評估 Hit Rate @ 4 與 MRR @ 4 指標。當看到 `檢索成功率 (Hit Rate @ 4): 100.0%`，代表檢索模組配置完美，已準備就緒！*

### 3.2 執行完整的 Pytest 測試套件
本專案內建了 80 項單元與回歸測試，在進行程式碼改動後可執行：
```bash
# 預設執行
python -m pytest tests/ -v --tb=short

# 在測試環境中排除本地環境變數 .env 的干擾 (使用模擬或純檢索測試)
SKIP_DOTENV=1 python -m pytest tests/ -v
```
*(設定環境變數 `SKIP_DOTENV=1` 能確保執行測試時，程式內部 `load_dotenv` 機制被靜態繞過，避免測試載入本機的實體 API Key)*

---

## 4. 疑難排解 (Troubleshooting)

### ❌ 問題一：執行時出現 `❌ 推理失敗: timed out` 或 `Ollama 回應逾時 (120 秒)`
* **原因**：本地硬體在首次載入 12B 大模型（約 7.2 GB）至顯存時速度較慢，超出了連線時間限制。
* **解法**：
  1. 請再次執行命令，因為此時模型很可能已經加載完成。
  2. 如果硬體效能受限，建議改用較輕量快速的模型，例如：
     ```bash
     python3 main.py "如何針對敏感個資實施資料遮罩控制措施 ？" --model TwinkleAI/gemma-3-4B-T1-it:latest --top-k 2
     ```

### ❌ 問題二：無法連線至 Ollama 服務 (`ConnectionRefusedError`)
* **原因**：本地的 Ollama 應用程式尚未開啟，或是運作在非預設連接埠。
* **解法**：
  1. 請確認您的電腦右上角或工作列中是否有 Ollama 的小圖示（已啟動）。
  2. 若啟用了不同的連接埠，請以 `--host` 參數指定正確位址：
     ```bash
     python3 main.py --host http://localhost:11435
     ```
