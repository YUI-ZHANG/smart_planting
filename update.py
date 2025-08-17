import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from sqlalchemy import create_engine, text
from flask_app import get_latest_data

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
        # 新增 id 欄位，這將作為每一筆數據的唯一識別碼
        # 我們可以使用 DataFrame 的索引作為 id
        df.reset_index(inplace=True)
        df.rename(columns={'index': 'id'}, inplace=True)        
        return df

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
