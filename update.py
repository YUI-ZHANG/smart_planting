import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime
from flask import Flask, jsonify
import json
from sqlalchemy import create_engine, text
'''
# 設定 Google Sheets API 憑證
# 請將你的 JSON 憑證檔案路徑替換成實際路徑
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('smart-planting-468806-f5b899621000.json', scope)
client = gspread.authorize(creds)

# 打開你的 Google Sheets 試算表和工作表
# 請將 'Your Spreadsheet Name' 和 'Sheet1' 替換成你的試算表名稱和工作表名稱
spreadsheet = client.open('smart')
worksheet = spreadsheet.get_worksheet(0) # 取得第一個工作表

def get_and_clean_data_without_headers():
    """
    從 Google Sheets 讀取沒有標題列的數據並進行清洗。
    """
    try:
        # 讀取所有儲存格的原始數據
        data = worksheet.get_all_values()
        
        if not data:
            print("工作表中沒有數據。")
            return None

        # 手動指定欄位名稱
        # 根據你提供的圖片，A欄是時間，B到E欄分別是溫度、濕度、土壤濕度、光照度
        column_names = ['時間', '環境溫度', '環境濕度', '土壤濕度', '光照度']
        
        # 將數據轉換成 Pandas DataFrame
        df = pd.DataFrame(data, columns=column_names)

        # 資料清洗步驟
        # 1. 轉換資料型別
        numeric_cols = ['環境溫度', '環境濕度', '土壤濕度', '光照度']
        for col in numeric_cols:
            # 嘗試將欄位轉換為數值型，遇到錯誤時填入 NaN
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 2. 處理時間戳記
        df['時間'] = pd.to_datetime(df['時間'], errors='coerce', format='%Y-%m-%d %H:%M')
        
        # 3. 處理空值 (這裡我們用前一個有效值填補，或你可以選擇其他方法)
        df.fillna(method='ffill', inplace=True)
        
        print("資料清洗完成，這是清洗後的 DataFrame：")
        print(df.tail()) # 顯示最後五筆清洗後的數據
        
        return df

    except gspread.exceptions.APIError as e:
        print(f"連線 Google Sheets 時發生錯誤: {e}")
        return None
    except Exception as e:
        print(f"處理數據時發生錯誤: {e}")
        return None

if __name__ == "__main__":
    cleaned_data = get_and_clean_data_without_headers()
    if cleaned_data is not None:
        # 在這裡可以加入將數據呈現到網頁、桌面或儲存成檔案的程式碼
        pass
'''

app = Flask(__name__)
engine = create_engine('sqlite:///plant_data.db')
# 你的 Google Sheets API 憑證設定
# 請將你的 JSON 憑證檔案路徑替換成實際路徑
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('smart-planting-468806-f5b899621000.json', scope)
client = gspread.authorize(creds)
spreadsheet = client.open('smart')
worksheet = spreadsheet.get_worksheet(0)

# 我們把數據清洗的邏輯包裝在一個函式裡
def get_and_clean_data_without_headers():
    """
    從 Google Sheets 讀取數據並進行清洗。
    """
    try:
        data = worksheet.get_all_values()
        if not data:
            return None
        column_names = ['時間', '環境溫度', '環境濕度', '土壤濕度', '光照度']
        df = pd.DataFrame(data, columns=column_names)
        
        numeric_cols = ['環境溫度', '環境濕度', '土壤濕度', '光照度']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df['時間'] = pd.to_datetime(df['時間'], errors='coerce', format='%Y-%m-%d %H:%M')
        df.ffill(inplace=True)
        
        return df
        # 轉換為 JSON 格式
        # return json.loads(df.to_json(orient='records', date_format='iso'))

    except gspread.exceptions.APIError as e:
        print(f"連線 Google Sheets 時發生錯誤: {e}")
        return None
    except Exception as e:
        print(f"處理數據時發生錯誤: {e}")
        return None

def write_to_database():
    """
    將清洗後的數據寫入 SQLite 資料庫。
    """
    cleaned_df = get_and_clean_data_without_headers()
    
    if cleaned_df is None:
        print("無法取得數據，跳過寫入資料庫。")
        return
    
    # 將 Pandas DataFrame 寫入資料庫中的 'plant_data' 資料表
    # if_exists='replace' 會在每次執行時刪除舊資料表並創建新的
    # 更好的方式是使用 'append' 來新增資料，但需要處理重複數據
    try:
        cleaned_df.to_sql('plant_data', engine, if_exists='replace', index=False)
        print("數據已成功寫入資料庫！")
        print(f"資料庫檔案路徑: {engine.url.database}")
        
    except Exception as e:
        print(f"寫入資料庫時發生錯誤: {e}")

if __name__ == '__main__':
    write_to_database()


'''# 建立一個 API 端點
@app.route('/api/data', methods=['GET'])
def get_plant_data():
    """
    提供植物監測數據的 API 端點。
    """
    cleaned_data = get_and_clean_data_without_headers()
    if cleaned_data is None:
        return jsonify({"error": "無法取得數據"}), 500
    
    return jsonify(cleaned_data)

# 運行 Flask 應用程式
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)'''