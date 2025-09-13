import os
from flask import Flask, jsonify, request, render_template, redirect, url_for
from sqlalchemy import create_engine, text
import pandas as pd
from datetime import datetime, timedelta
from flask_cors import CORS
from werkzeug.utils import secure_filename
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import gspread.exceptions
import uuid

# 設定日誌等級，幫助除錯
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
CORS(app) 

# 連接到你的資料庫
engine = create_engine('sqlite:///plant_data.db')

# 確保 'static/uploads' 資料夾存在，用於存放上傳的圖片
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 設定 Google Sheets API
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS = ServiceAccountCredentials.from_json_keyfile_name('smart-planting-468806-f5b899621000.json', SCOPE)
CLIENT = gspread.authorize(CREDS)
SERVICE_ACCOUNT_EMAIL = "googlesheetsapi@smart-planting-468806.iam.gserviceaccount.com"
YOUR_PERSONAL_EMAIL = "u1473318@gmail.com"


# 固定使用的試算表 ID
FIXED_SHEET_ID = '1NoqaDFRS137ov8gOsbmlixzWhhwGj5EdfANvjotlv28'


def init_db():
    """
    初始化資料庫，創建植物資訊資料表（如果不存在）。
    mac_address 被設為 UNIQUE，確保其唯一性。
    """
    logging.info("正在初始化資料庫...")
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS plants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    photo_path TEXT,
                    sheet_id TEXT,
                    mac_address TEXT UNIQUE,
                    reset_flag INTEGER DEFAULT 0
                );
            """))
            conn.commit()
            logging.info("資料表 'plants' 檢查/創建成功。")
        except Exception as e:
            logging.error(f"初始化資料庫時發生錯誤: {e}")


# 在應用程式啟動前初始化資料庫
with app.app_context():
    init_db()


def handle_plant_sheet_creation(identifier, existing_sheet_id=None):
    """
    在指定的 Google Sheets 試算表中為新植物創建一個工作表。
    """
    try:
        sheet = CLIENT.open_by_key(existing_sheet_id)
        # 使用傳入的 identifier（MAC 位址或 UUID）作為工作表標題
        worksheet = sheet.add_worksheet(title=identifier, rows="100", cols="20")
        headers = ["時間", "環境溫度", "環境濕度", "土壤濕度", "光照度"]
        worksheet.insert_row(headers, index=1)
        logging.info(f"成功為識別碼 {identifier} 創建試算表工作表。")
        return existing_sheet_id
    except gspread.exceptions.APIError as e:
        logging.error(f"處理 Google Sheets 時發生 API 錯誤：{e}")
        return None
    except Exception as e:
        logging.error(f"處理試算表時發生未知錯誤：{e}")
        return None


def get_all_plants():
    """
    從資料庫獲取所有植物資訊。
    """
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT id, name, photo_path, sheet_id, mac_address FROM plants ORDER BY id DESC;"))
            plants = [{"id": row.id, "name": row.name, "photo_path": row.photo_path, "sheet_id":row.sheet_id, "mac_address": row.mac_address} for row in result]
            return plants
        except Exception as e:
            logging.error(f"從資料庫獲取植物列表時發生錯誤: {e}")
            return []


def get_filtered_data(sheet_id, period):
    """
    根據時間週期從資料庫讀取數據。
    period 可以是 'day', 'week', 'month', 'year'。
    """
    try:
        # 使用 open_by_key 和 sheet1 獲取試算表
        sheet = CLIENT.open_by_key(sheet_id).sheet1
        records = sheet.get_all_records()
        df = pd.DataFrame(records)

        df['時間'] = pd.to_datetime(df['時間'], format='%Y-%m-%d %H:%M:%S', errors='coerce')

        now = datetime.now()
        start_date = now - timedelta(days=1)
        
        if period == 'week':
            start_date = now - timedelta(days=7)
        elif period == 'month':
            start_date = now - timedelta(days=30)
        elif period == 'year':
            start_date = now - timedelta(days=365)
        
        filtered_df = df[df['時間'] >= start_date]

        if filtered_df.empty:
            return[]
        
        return filtered_df.to_dict(orient='records')
    except Exception as e:
        logging.error(f"從 Google Sheets 讀取數據時發生錯誤：{e}")
        return None


@app.route('/')
def home():
    plants = get_all_plants()
    return render_template('index.html', plants=plants)

@app.route('/addPlant')
def add_plant():
    return render_template('addPlant.html')

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/api/data/<int:plant_id>', methods=['GET'])
def get_plant_data(plant_id):
    period = request.args.get('period', 'day')
    
    if not plant_id:
        return jsonify({"error": "缺少植物 ID"}), 400
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name, sheet_id, mac_address FROM plants WHERE id = :id"), {"id": plant_id}).first()
        if not result:
            return jsonify({"error": "找不到對應的植物"}), 404
        
        plant_name = result.name
        sheet_id = result.sheet_id
        
        # 根據 mac_address 是否存在來決定工作表名稱
        # 如果 mac_address 存在，就用它。否則，使用 plant_id 作為工作表名稱（從 UUID 生成）
        worksheet_identifier = result.mac_address if result.mac_address else plant_id

    try:
        sheet = CLIENT.open_by_key(sheet_id)
        worksheet = sheet.worksheet(worksheet_identifier)
    except gspread.exceptions.WorksheetNotFound:
        return jsonify({"error": f"在試算表 '{sheet_id}' 中找不到名為 '{worksheet_identifier}' 的工作表。請確認名稱是否正確。"}), 404
    except Exception as e:
        return jsonify({"error": f"無法存取工作表。{e}"}), 500
    
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    
    df['時間'] = pd.to_datetime(df['時間'], format='%Y-%m-%d %H:%M:%S', errors='coerce')

    now = datetime.now()
    start_date = now - timedelta(days=1)
    
    if period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'month':
        start_date = now - timedelta(days=30)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    
    filtered_df = df[df['時間'] >= start_date]

    if filtered_df.empty:
        return jsonify([])
    
    return jsonify(filtered_df.to_dict(orient='records'))


@app.route('/api/delete_plant/<int:plant_id>', methods=['POST'])
def delete_plant(plant_id):
    """
    根據植物 ID 刪除資料庫紀錄和對應的 Google Sheets 工作表。
    """
    try:
        with engine.connect() as conn:
            # 1. 查詢要刪除的植物資訊，以獲取其 MAC 位址和試算表 ID
            result = conn.execute(text("SELECT name, sheet_id, mac_address FROM plants WHERE id = :id;"), {"id": plant_id}).first()
            if not result:
                return jsonify({"error": "找不到對應的植物"}), 404

            plant_name = result.name
            sheet_id = result.sheet_id
            
            # 使用 mac_address 或 id 來決定工作表名稱
            worksheet_identifier = result.mac_address if result.mac_address else str(plant_id)

            # 2. 刪除 Google Sheets 中的工作表
            try:
                sheet = CLIENT.open_by_key(sheet_id)
                # 使用識別碼尋找工作表
                worksheet = sheet.worksheet(worksheet_identifier)
                sheet.del_worksheet(worksheet)
                logging.info(f"成功刪除 Google Sheets 工作表：{worksheet_identifier}")
            except gspread.exceptions.WorksheetNotFound:
                logging.warning(f"Google Sheets 工作表 '{worksheet_identifier}' 不存在，跳過刪除。")
            except Exception as e:
                logging.error(f"刪除 Google Sheets 工作表時發生錯誤：{e}")

            # 3. 刪除資料庫紀錄
            conn.execute(text("DELETE FROM plants WHERE id = :id;"), {"id": plant_id})
            conn.commit()
            logging.info(f"成功從資料庫刪除植物：{plant_name} (ID: {plant_id})")

    except Exception as e:
        logging.error(f"刪除植物時發生錯誤: {e}")
        return jsonify({"error": f"內部伺服器錯誤：{e}"}), 500

    return jsonify({"success": True, "message": f"成功刪除植物：{plant_name}"}), 200


@app.route('/api/remote_reset', methods=['POST'])
def remote_reset():
    """
    接收遠端重設請求，並在資料庫中設定重設旗標。
    """
    try:
        data = request.get_json(silent=True)
        mac_address = data.get('mac_address')
        
        if not mac_address:
            return jsonify({"error": "缺少 MAC 位址"}), 400
        
        with engine.connect() as conn:
            # 根據 MAC 位址查詢植物 ID，確保請求有效
            result = conn.execute(text("SELECT id FROM plants WHERE mac_address = :mac_address;"), {"mac_address": mac_address}).first()
            if not result:
                return jsonify({"error": "找不到對應的裝置"}), 404

            # 設定重設旗標為 1
            conn.execute(text("UPDATE plants SET reset_flag = 1 WHERE mac_address = :mac_address;"), {"mac_address": mac_address})
            conn.commit()
            logging.info(f"已為 MAC {mac_address} 的裝置設定遠端重設旗標。")
            
        return jsonify({"success": True, "message": "遠端重設指令已傳送。"}), 200

    except Exception as e:
        logging.error(f"遠端重設時發生錯誤: {e}")
        return jsonify({"error": f"內部伺服器錯誤：{e}"}), 500

@app.route('/api/check_reset/<string:mac_address>', methods=['GET'])
def check_reset(mac_address):
    """
    供 ESP8266 查詢是否有遠端重設指令。
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT reset_flag FROM plants WHERE mac_address = :mac_address;"), {"mac_address": mac_address}).first()
            if not result:
                return jsonify({"reset_pending": False}), 200

            reset_pending = result.reset_flag == 1

            # 如果有重設指令，則在傳送後清除旗標
            if reset_pending:
                conn.execute(text("UPDATE plants SET reset_flag = 0 WHERE mac_address = :mac_address;"), {"mac_address": mac_address})
                conn.commit()
                logging.info(f"裝置 {mac_address} 已收到並清除遠端重設旗標。")

        return jsonify({"reset_pending": reset_pending}), 200

    except Exception as e:
        logging.error(f"檢查重設指令時發生錯誤: {e}")
        return jsonify({"error": f"內部伺服器錯誤：{e}"}), 500


@app.route('/api/add_plant', methods=['POST'])
def api_add_plant():
    try:
        name = request.form.get('name')
        file = request.files.get('photo')

        if not name:
            return jsonify({"error": "植物名稱不能為空"}), 400

        photo_path = 'https://via.placeholder.com/150'
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            photo_path = f"/static/uploads/{filename}"

        # 1. 生成唯一的 UUID 作為臨時識別碼
        temp_id = str(uuid.uuid4())
        
        # 2. 為這個 UUID 創建一個新的 Google Sheets 工作表
        sheet_created_successfully = handle_plant_sheet_creation(identifier=temp_id, existing_sheet_id=FIXED_SHEET_ID)
        
        if not sheet_created_successfully:
            return jsonify({"error": "Failed to create Google Sheet for new plant."}), 500

        # 3. 寫入資料庫，mac_address 欄位使用生成的 UUID
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO plants (name, photo_path, sheet_id, mac_address) VALUES (:name, :photo_path, :sheet_id, :mac_address);"), 
                          {"name": name, "photo_path": photo_path, "sheet_id": FIXED_SHEET_ID, "mac_address": temp_id})
            conn.commit()

        logging.info(f"成功手動新增植物：{name}，臨時 ID：{temp_id}")
        return redirect(url_for('home'))

    except Exception as e:
        logging.error(f"處理新增植物表單時發生錯誤: {e}")
        return jsonify({"error": f"內部伺服器錯誤：{e}"}), 500



@app.route('/api/register_device_auto', methods=['POST'])
def register_device_auto():
    """
    接收來自裝置的自動註冊請求，並根據 MAC 位址建立或更新植物紀錄。
    這段程式碼已被修正，以支援配對手動創建的植物。
    """
    try:
        data = request.get_json(silent=True)
        mac_address = data.get('mac_address')
        
        if not mac_address:
            logging.error("Missing MAC address.")
            return jsonify({"error": "Missing MAC address"}), 400
        
        with engine.connect() as conn:
            # 1. 檢查 MAC 位址是否已存在
            result = conn.execute(text("SELECT id FROM plants WHERE mac_address = :mac_address;"), {"mac_address": mac_address}).first()
            
            if not result:
                # 2. 如果 MAC 位址不存在，檢查是否有尚未配對的植物（mac_address IS NULL）
                unpaired_plant = conn.execute(text("SELECT id FROM plants WHERE mac_address IS NULL LIMIT 1;")).first()
                
                if unpaired_plant:
                    # 3. 如果找到未配對的植物，將 MAC 位址更新到這筆紀錄上
                    plant_id = unpaired_plant.id
                    conn.execute(text("UPDATE plants SET mac_address = :mac_address WHERE id = :id;"), {"mac_address": mac_address, "id": plant_id})
                    conn.commit()
                    logging.info(f"成功將 MAC 位址 {mac_address} 配對到手動創建的植物 (ID: {plant_id})。")
                else:
                    # 4. 如果沒有未配對的植物，則自動創建一個新的紀錄
                    logging.info(f"偵測到新的 MAC 位址：{mac_address}，正在自動建立植物紀錄。")
                    plant_name = f"Plant-{mac_address[-4:]}"
                    new_sheet_id = handle_plant_sheet_creation(mac_address, existing_sheet_id=FIXED_SHEET_ID)
                    if not new_sheet_id:
                        return jsonify({"error": "Failed to create Google Sheet."}), 500
                    
                    conn.execute(text("INSERT INTO plants (name, photo_path, sheet_id, mac_address) VALUES (:name, :photo_path, :sheet_id, :mac_address);"), 
                                  {"name": plant_name, "photo_path": 'https://via.placeholder.com/150', "sheet_id": new_sheet_id, "mac_address": mac_address})
                    conn.commit()
                    logging.info(f"成功自動註冊新植物：{plant_name}，MAC：{mac_address}")
            else:
                # 5. 如果 MAC 位址已存在，無需重新註冊，直接回傳成功
                logging.info(f"MAC 位址 {mac_address} 已存在，無需重新註冊。")
            
            return jsonify({"success": True, "mac_address": mac_address}), 200

    except Exception as e:
        logging.error(f"自動註冊裝置時發生錯誤: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/latest_data/<int:plant_id>', methods=['GET'])
def get_latest_data(plant_id):
    """
    獲取指定植物 ID 的最新數據。
    這個 API 會從 Google Sheets 讀取最新的單一數據點，並回傳所有數據類型。
    """
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name, sheet_id, mac_address FROM plants WHERE id = :id"), {"id": plant_id}).first()
        if not result:
            return jsonify({"error": "找不到對應的植物"}), 404
        
        sheet_id = result.sheet_id
        worksheet_identifier = result.mac_address if result.mac_address else str(plant_id)

    try:
        # 從 Google Sheets 獲取所有數據
        sheet = CLIENT.open_by_key(sheet_id)
        worksheet = sheet.worksheet(worksheet_identifier)
        records = worksheet.get_all_records()
        
        if not records:
            return jsonify({"data": {}}), 200

        # 獲取最新的數據點 (最後一條記錄)
        latest_record = records[-1]
        
        # 移除 '時間' 欄位，因為它通常不會顯示在單一數值方塊中
        if '時間' in latest_record:
            del latest_record['時間']

        return jsonify({"data": latest_record}), 200
    
    except gspread.exceptions.WorksheetNotFound:
        logging.error(f"在試算表 '{sheet_id}' 中找不到名為 '{worksheet_identifier}' 的工作表。")
        return jsonify({"error": f"找不到對應的工作表。"}), 404
    except Exception as e:
        logging.error(f"從 Google Sheets 獲取數據時發生錯誤：{e}")
        return jsonify({"error": f"無法獲取數據：{e}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
