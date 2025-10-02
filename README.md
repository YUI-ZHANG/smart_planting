# **智慧種植系統 (Smart Planting System)**
這是一個結合 ESP8266/Arduino 與 Python Flask 的物聯網解決方案。它能自動監測植物的環境數據（如土壤濕度），並透過網頁儀表板實現遠端監控和自動化控制（如自動澆水）。

# **Install (安裝與設定)**
## 1. 硬體設備
主控板：ESP8266、Arduino UNO

感測器：土壤濕度感測器、環境溫濕度感測器、光照度感測器

執行器：水泵、繼電器

## 2. 韌體上傳
使用 Arduino IDE 開啟 8266_V2.ino 以及 UNO_V2.ino 檔案。

在 8266_V2.ino 中，請依據您的設定更改 scriptURL (用於傳輸數據的伺服器或腳本網址) 以及 FLASK_SERVER_URL (您的本地端/伺服器 IP)。

將韌體上傳到對應的主控板。

## 3. 軟體環境設定
Python 版本： 請確保您的環境使用 Python 3.13.7 或更高版本。

安裝依賴： 安裝專案所需的 Python 模組。

```Bash
pip install -r requirements.txt
```
Google Sheets API 設定：

在 Python 程式碼中 (flask_app.py內)，將 gs_keyfile 變數更改為從 Google Sheets API 取得的 JSON 密鑰檔案名稱。

Google Sheets 設定：

在 Python 程式碼中 (flask_app.py內)，將 fixed_sheet_id 變數更改為您的 Google Sheets 網址中段那一長串 ID。

# **Usage (使用方式)**
## 1. 啟動後端伺服器
開啟終端機，並執行 Flask 應用程式。

```Bash
python flask_app.py
```
## 2. 數據傳輸
確認您的 ESP8266 裝置已成功連上 Wi-Fi，並開始將感測器數據傳送到您設定的 Google Sheets 中。

## 3. 存取監控儀表板
本地端存取：在執行程式的電腦上，使用瀏覽器開啟 http://127.0.0.1:5000 即可查看即時數據、歷史記錄並實現自動化控制。

區域網路存取：若要讓其他在相同 Wi-Fi 網路下的裝置也能使用，請將上述網址的 IP 位址替換成您的區域網路 IP 位址（例如：http://192.168.1.XX:5000）。

# **Contributing (貢獻)**
本專案是作者的個人學習與實作，仍有許多可優化及擴展的空間，歡迎提供建議。
