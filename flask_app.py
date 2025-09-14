import os
import uuid
import logging
from datetime import datetime, timedelta

import pandas as pd
from flask import Flask, jsonify, request, render_template, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, text
import pytz

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import gspread.exceptions

# -----------------------------
# Model 層
# -----------------------------
class PlantModel:
    def __init__(self, db_url='sqlite:///plant_data.db', gs_keyfile='smart-planting-468806-f5b899621000.json', fixed_sheet_id='1NoqaDFRS137ov8gOsbmlixzWhhwGj5EdfANvjotlv28'):
        logging.basicConfig(level=logging.DEBUG)
        self.engine = create_engine(db_url)
        self.fixed_sheet_id = fixed_sheet_id.strip() 

        # Google Sheets 設定
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(gs_keyfile, scope)
        self.client = gspread.authorize(creds)

        # 初始化資料表
        self.init_db()

    def init_db(self):
        logging.info("初始化資料庫...")
        with self.engine.connect() as conn:
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

    # 新增植物
    def add_plant(self, name, photo_path, mac_address):
        with self.engine.connect() as conn:
            conn.execute(text("INSERT INTO plants (name, photo_path, sheet_id, mac_address) VALUES (:name, :photo_path, :sheet_id, :mac_address)"),
                         {"name": name, "photo_path": photo_path, "sheet_id": self.fixed_sheet_id, "mac_address": mac_address})
            conn.commit()

    # 取得所有植物
    def get_all_plants(self):
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT id, name, photo_path, sheet_id, mac_address FROM plants ORDER BY id DESC;"))
            return [{"id": r.id, "name": r.name, "photo_path": r.photo_path, "sheet_id": r.sheet_id, "mac_address": r.mac_address} for r in result]

    # 取得特定植物
    def get_plant_by_id(self, plant_id):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT * FROM plants WHERE id=:id"), {"id": plant_id}).first()

    # 刪除植物
    def delete_plant(self, plant_id):
        plant = self.get_plant_by_id(plant_id)
        if not plant:
            return False, "找不到植物"
        with self.engine.connect() as conn:
            conn.execute(text("DELETE FROM plants WHERE id=:id"), {"id": plant_id})
            conn.commit()
        return True, plant

    # Google Sheets 創建工作表
    def create_worksheet(self, identifier):
        try:
            sheet = self.client.open_by_key(self.fixed_sheet_id)
            ws = sheet.add_worksheet(title=identifier, rows="100", cols="20")
            ws.insert_row(["時間", "環境溫度", "環境濕度", "土壤濕度", "光照度"], index=1)
            return True
        except gspread.exceptions.APIError as e:
            logging.error(f"Google Sheets API Error: {e}")
            return False

        # 從 Google Sheets 取得數據
        # PlantModel 內修改 get_plant_data
    def get_plant_data(self, sheet_id, worksheet_name, start_date=None, end_date=None):
        try:
            # 讀取 Google Sheets 資料
            sheet = self.client.open_by_key(sheet_id)
            all_values = sheet.values_get(f"{worksheet_name}!A:Z")
            values = all_values.get('values', [])
            if not values or len(values) < 2:
                return []

            # 清理標題
            headers = [h.strip() for h in values[0]]
            rows = values[1:]
            df = pd.DataFrame(rows, columns=headers)

            numeric_cols = ["環境溫度", "環境濕度", "土壤濕度", "光照度"]
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 將時間欄位轉換為 datetime 物件，並處理錯誤
            taipei_tz = pytz.timezone('Asia/Taipei')
            df["時間"] = pd.to_datetime(df["時間"], format="%Y/%m/%d-%H:%M:%S", errors="coerce")
            df = df.dropna(subset=["時間"]) # 移除時間轉換失敗的列
            df["時間"] = df["時間"].dt.tz_localize(taipei_tz, ambiguous='infer')
            df["時間"] = df["時間"].dt.tz_convert('UTC')

            if start_date and end_date:
                # 確保傳入的時間是時區感知的，並轉換為 UTC
                start_date_utc = pd.to_datetime(start_date, utc=True)
                end_date_utc = pd.to_datetime(end_date, utc=True)
                
                # 將 DataFrame 的時間欄位轉換為時區感知的，如果它不是的話
                # 如果已經是時區感知的，就直接轉換到 UTC
                if df['時間'].dt.tz is None:
                    df_time_utc = df['時間'].dt.tz_localize('UTC')
                else:
                    df_time_utc = df['時間'].dt.tz_convert('UTC')

                # 根據時間範圍過濾數據
                filtered_df = df[(df_time_utc >= start_date_utc) & (df_time_utc <= end_date_utc)].copy()
                logging.info(f"過濾後的資料筆數: {len(filtered_df)}")
                return filtered_df.to_dict(orient="records")
            
            else:
                # 如果沒有指定時間範圍，回傳所有資料 (或最近一筆)
                # 為了最新的數據顯示，我們只回傳最新的前 100 筆
                latest_data = df.sort_values(by='時間', ascending=False).head(100).to_dict(orient="records")
                logging.info(f"回傳最新 {len(latest_data)} 筆資料。")
                return latest_data

        except Exception as e:
            logging.error(f"取得植物資料錯誤: {e}")
            return []

# -----------------------------
# Controller 層
# -----------------------------
class PlantController:
    def __init__(self, model: PlantModel):
        self.model = model
        self.app = Flask(__name__)
        CORS(self.app)
        UPLOAD_FOLDER = os.path.join(self.app.root_path, 'static', 'uploads')
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        self.app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
        self.register_routes()

    def register_routes(self):
        @self.app.route('/')
        def home():
            plants = self.model.get_all_plants()
            return render_template('index.html', plants=plants)

        @self.app.route('/editPlant')
        def edit_plant():
            return render_template('editPlant.html')
        
        @self.app.route('/history')
        def history():
            return render_template('history.html')

        @self.app.route('/api/add_plant', methods=['POST'])
        def api_add_plant():
            try:
                name = request.form.get('name')
                file = request.files.get('photo')
                if not name:
                    return jsonify({"error": "植物名稱不能為空"}), 400

                photo_path = 'https://via.placeholder.com/150'
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    photo_path = f"/static/uploads/{filename}"

                temp_id = str(uuid.uuid4())
                if not self.model.create_worksheet(temp_id):
                    return jsonify({"error": "無法建立 Google Sheets 工作表"}), 500
                self.model.add_plant(name, photo_path, temp_id)
                return redirect(url_for('home'))
            except Exception as e:
                logging.error(f"新增植物錯誤: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/data/<plant_id>', methods=['GET'])
        def get_plant_data(plant_id):
            plant = self.model.get_plant_by_id(plant_id)
            if not plant:
                return jsonify({"error": "找不到植物"}), 404
            
            start_iso = request.args.get('start')
            end_iso = request.args.get('end')
            
            start_date = datetime.fromisoformat(start_iso.replace('Z', '+00:00')) if start_iso else None
            end_date = datetime.fromisoformat(end_iso.replace('Z', '+00:00')) if end_iso else None
            
            logging.info(f"API 請求的 plant_id: {plant_id}, start_date: {start_date}, end_date: {end_date}")
            
            data = self.model.get_plant_data(plant.sheet_id, plant.mac_address, start_date=start_date, end_date=end_date)
            return jsonify({"data": data})

        @self.app.route('/api/delete_plant/<int:plant_id>', methods=['POST'])
        def delete_plant(plant_id):
            success, plant = self.model.delete_plant(plant_id)
            if not success:
                return jsonify({"error": plant}), 404
            return jsonify({"success": True, "message": f"已刪除植物 {plant.name}"})

# -----------------------------
# 啟動應用程式
# -----------------------------
if __name__ == '__main__':
    model = PlantModel()
    controller = PlantController(model)
    controller.app.run(debug=True, host='0.0.0.0', port=5000)
