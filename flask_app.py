import os
import logging
from datetime import datetime

import pandas as pd
from flask import Flask, jsonify, request, render_template, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, text
import pytz

import gspread
import gspread.exceptions
from google.oauth2 import service_account


# -----------------------------
# Model 層
# -----------------------------
class PlantModel:
    def __init__(self, app, db_url='sqlite:///plant_data.db', gs_keyfile='smart-planting-468806-f5b899621000.json', fixed_sheet_id='1NoqaDFRS137ov8gOsbmlixzWhhwGj5EdfANvjotlv28'):
        logging.basicConfig(level=logging.DEBUG)
        self.app = app
        self.engine = create_engine(db_url)
        self.fixed_sheet_id = fixed_sheet_id.strip()
        
        # 修正：將 UPLOAD_FOLDER 設定為屬性
        self.upload_folder = os.path.join(self.app.root_path, 'static', 'uploads')
        os.makedirs(self.upload_folder, exist_ok=True)

        # Google Sheets 設定
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_file(gs_keyfile, scopes=scope)
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
    def delete_plant(self, plant_id):
        """
        刪除指定 plant_id 的所有數據，包括 Google Sheets 和資料庫紀錄。
        """
        conn = None
        try:
            # 1. 取得植物的完整資訊
            plant = self.get_plant_by_id(plant_id)
            if not plant:
                return False, "找不到植物"

            # 2. 刪除 Google Sheets 工作表
            try:
                sheet = self.client.open_by_key(self.fixed_sheet_id)
                worksheet = sheet.worksheet(plant.mac_address)
                sheet.del_worksheet(worksheet)
                logging.info(f"已成功刪除 Google Sheets 工作表: {plant.mac_address}")
            except gspread.exceptions.WorksheetNotFound:
                logging.warning(f"Google Sheets 工作表 '{plant.mac_address}' 不存在，略過刪除。")
            except Exception as e:
                logging.error(f"刪除 Google Sheets 工作表時發生錯誤: {e}")
                # 這裡選擇不中斷，讓資料庫刪除繼續進行

            # 3. 檢查照片檔案是否存在並刪除
            if plant.photo_path and plant.photo_path.startswith('/static/uploads/'):
                filename = os.path.basename(plant.photo_path)
                file_path = os.path.join(self.upload_folder, filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logging.info(f"已成功刪除植物 ID {plant_id} 的照片檔案: {file_path}")
                else:
                    logging.warning(f"找不到植物 ID {plant_id} 的照片檔案: {file_path}")

            # 4. 刪除資料庫中的紀錄
            with self.engine.connect() as conn:
                # 刪除 plants 表中的植物紀錄
                result = conn.execute(text("DELETE FROM plants WHERE id=:id"), {"id": plant_id})
                conn.commit()
                logging.info(f"已成功刪除植物 ID {plant_id} 的資料庫紀錄。")

            return True, plant
        
        except Exception as e:
            logging.error(f"刪除植物時發生錯誤: {e}")
            return False, str(e)

    def add_plant(self, name, photo_path, mac_address):
        with self.engine.connect() as conn:
            conn.execute(text("INSERT INTO plants (name, photo_path, sheet_id, mac_address) VALUES (:name, :photo_path, :sheet_id, :mac_address)"),
                         {"name": name, "photo_path": photo_path, "sheet_id": self.fixed_sheet_id, "mac_address": mac_address})
            conn.commit()
    
    def get_plant_by_mac(self, mac_address):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT * FROM plants WHERE mac_address=:mac_address"), {"mac_address": mac_address}).first()

    def get_all_plants(self):
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT id, name, photo_path, sheet_id, mac_address FROM plants ORDER BY id DESC;"))
            return [{"id": r.id, "name": r.name, "photo_path": r.photo_path, "sheet_id": r.sheet_id, "mac_address": r.mac_address} for r in result]

    def get_plant_by_id(self, plant_id):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT * FROM plants WHERE id=:id"), {"id": plant_id}).first()

    def update_plant(self, plant_id, name, photo_file):
        with self.engine.connect() as conn:
            plant = self.get_plant_by_id(plant_id)
            if not plant:
                raise ValueError("找不到植物")

            photo_path = plant.photo_path
            if photo_file and photo_file.filename:
                # 如果有舊照片且位於上傳資料夾，則刪除
                if photo_path and photo_path.startswith('/static/uploads/'):
                    old_photo_filename = os.path.basename(photo_path)
                    old_photo_path = os.path.join(self.upload_folder, old_photo_filename)
                    if os.path.exists(old_photo_path):
                        os.remove(old_photo_path)
                        logging.info(f"已刪除舊照片: {old_photo_path}")

                # 儲存新照片
                filename = secure_filename(photo_file.filename)
                file_path = os.path.join(self.upload_folder, filename)
                photo_file.save(file_path)
                photo_path = f"/static/uploads/{filename}"

            # 更新資料庫
            conn.execute(text("UPDATE plants SET name = :name, photo_path = :photo_path WHERE id = :id"),
                         {"name": name, "photo_path": photo_path, "id": plant_id})
            conn.commit()
            logging.info(f"植物 ID {plant_id} 的資料已更新。")

    def delete_plant(self, plant_id):
        plant = self.get_plant_by_id(plant_id)
        if not plant:
            return False, "找不到植物"
        with self.engine.connect() as conn:
            conn.execute(text("DELETE FROM plants WHERE id=:id"), {"id": plant_id})
            conn.commit()
        return True, plant

    def create_worksheet(self, identifier):
        try:
            sheet = self.client.open_by_key(self.fixed_sheet_id)
            try:
                sheet.worksheet(identifier)
                logging.warning(f"工作表 '{identifier}' 已存在，不重複創建。")
                return True
            except gspread.exceptions.WorksheetNotFound:
                ws = sheet.add_worksheet(title=identifier, rows="100", cols="20")
                ws.insert_row(["時間", "環境溫度", "環境濕度", "土壤濕度", "光照度"], index=1)
                return True
        except gspread.exceptions.APIError as e:
            logging.error(f"Google Sheets API Error: {e}")
            return False
    
    def get_plant_data(self, sheet_id, worksheet_name, start_date=None, end_date=None):
        try:
            sheet = self.client.open_by_key(sheet_id)
            all_values = sheet.values_get(f"{worksheet_name}!A:Z")
            values = all_values.get('values', [])
            if not values or len(values) < 2:
                return []
            
            headers = [h.strip() for h in values[0]]
            rows = values[1:]
            df = pd.DataFrame(rows, columns=headers)
            
            numeric_cols = ["環境溫度", "環境濕度", "土壤濕度", "光照度"]
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            taipei_tz = pytz.timezone('Asia/Taipei')
            df["時間"] = pd.to_datetime(df["時間"], format="%Y/%m/%d-%H:%M:%S", errors="coerce")
            df = df.dropna(subset=["時間"])
            df["時間"] = df["時間"].dt.tz_localize(taipei_tz, ambiguous='infer')
            df["時間"] = df["時間"].dt.tz_convert('UTC')

            if start_date and end_date:
                start_date_utc = pd.to_datetime(start_date, utc=True)
                end_date_utc = pd.to_datetime(end_date, utc=True)
                
                df_time_utc = df['時間'].dt.tz_convert('UTC')
                filtered_df = df[(df_time_utc >= start_date_utc) & (df_time_utc <= end_date_utc)].copy()
                logging.info(f"過濾後的資料筆數: {len(filtered_df)}")
                return filtered_df.to_dict(orient="records")
            
            else:
                latest_data = df.sort_values(by='時間', ascending=False).head(1).to_dict(orient="records")
                logging.info(f"回傳最新 {len(latest_data)} 筆資料。")
                return latest_data

        except Exception as e:
            logging.error(f"取得植物資料錯誤: {e}")
            return []
# -----------------------------
# Controller 層
# -----------------------------
class PlantController:
    def __init__(self, app, model: PlantModel):
        self.app = app
        self.model = model
        CORS(self.app)
        # 新增：儲存 ESP 指令的暫存區
        self.device_commands = {}
        self.register_routes()

    def register_routes(self):
        # 網頁路由
        @self.app.route('/')
        def home():
            plants = self.model.get_all_plants()
            return render_template('index.html', plants=plants)

        @self.app.route('/editPlant')
        def edit_plant_page():
            plant_id = request.args.get('id')
            if not plant_id:
                return redirect(url_for('home'))
            return render_template('editPlant.html')
        
        @self.app.route('/history')
        def history():
            return render_template('history.html')

        # API 路由
        @self.app.route('/api/plant/<int:plant_id>', methods=['GET'])
        def api_get_plant(plant_id):
            plant = self.model.get_plant_by_id(plant_id)
            if not plant:
                return jsonify({"error": "找不到植物"}), 404
            return jsonify({
                "id": plant.id,
                "name": plant.name,
                "photo_path": plant.photo_path,
                "sheet_id": plant.sheet_id,
                "mac_address": plant.mac_address
            })
        
        @self.app.route('/api/delete_plant/<int:plant_id>', methods=['POST'])
        def delete_plant(plant_id):
            """
            透過 POST 請求刪除一筆植物紀錄及其所有關聯數據。
            """
            try:
                success, message = self.model.delete_plant(plant_id)
                if success:
                    logging.info(f"已成功刪除植物 ID {plant_id}。")
                    return jsonify({
                        "success": True, 
                        "message": "植物紀錄已成功刪除。"
                    }), 200
                else:
                    logging.warning(f"刪除失敗：{message}")
                    return jsonify({
                        "success": False, 
                        "error": message
                    }), 404
            except Exception as e:
                logging.error(f"刪除植物紀錄時發生錯誤: {e}")
                return jsonify({
                    "success": False, 
                    "error": f"伺服器錯誤：無法刪除植物紀錄。"
                }), 500
            
        @self.app.route('/api/update_plant/<int:plant_id>', methods=['POST'])
        def api_update_plant(plant_id):
            try:
                name = request.form.get('plant_name')
                file = request.files.get('plant_photo')
                
                if not name:
                    return jsonify({"error": "植物名稱不能為空"}), 400
                
                self.model.update_plant(plant_id, name, file)
                
                return jsonify({"success": True, "message": "植物資料已成功更新！"})
            except Exception as e:
                logging.error(f"更新植物錯誤: {e}")
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

            
        @self.app.route('/api/remote_reset', methods=['POST'])
        def api_remote_reset():
            try:
                data = request.get_json()
                mac_address = data.get("mac_address")
                if not mac_address:
                    return jsonify({"error": "MAC 地址不能為空"}), 400

                # 在資料庫中設定 reset_flag
                with self.model.engine.connect() as conn:
                    result = conn.execute(text("UPDATE plants SET reset_flag = 1 WHERE mac_address = :mac_address"), {"mac_address": mac_address})
                    conn.commit()
                
                if result.rowcount == 0:
                    return jsonify({"error": "找不到此 MAC 位址的裝置"}), 404

                return jsonify({"success": True, "message": f"已設定遠端重設指令給 {mac_address}"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        # ---------------------------
        # ⚡ ESP8266 裝置相關 API
        # ---------------------------
        @self.app.route('/api/register_device_auto', methods=['POST'])
        def api_register_device():
            try:
                data = request.json
                mac_address = data.get('mac_address')
                plant_name = data.get('name', '未命名植物')
                if not mac_address:
                    return jsonify({"error": "MAC 地址不能為空"}), 400
                if self.model.get_plant_by_mac(mac_address):
                    return jsonify({"success": True, "message": "裝置已配對。"})
                if not self.model.create_worksheet(mac_address):
                    return jsonify({"error": "無法建立 Google Sheets 工作表"}), 500
                photo_path = 'https://via.placeholder.com/150'
                self.model.add_plant(plant_name, photo_path, mac_address)
                return jsonify({"success": True, "message": "裝置配對成功！"})
            except Exception as e:
                logging.error(f"裝置配對錯誤: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/check_reset/<mac_address>', methods=['GET'])
        @self.app.route('/api/check_reset/<mac_address>/', methods=['GET'])
        def check_reset(mac_address):
            try:
                plant = self.model.get_plant_by_mac(mac_address)
                if not plant:
                    return jsonify({"error": "找不到此 MAC 位址的裝置"}), 404
                reset_pending = plant.reset_flag == 1
                if reset_pending:
                    with self.model.engine.connect() as conn:
                        conn.execute(text("UPDATE plants SET reset_flag = 0 WHERE mac_address = :mac_address"), {"mac_address": mac_address})
                        conn.commit()
                return jsonify({"reset_pending": reset_pending})
            except Exception as e:
                logging.error(f"檢查遠端重設錯誤: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/set_threshold', methods=['POST'])
        def set_threshold():
            try:
                data = request.get_json()
                mac_address = data.get("mac_address")
                caseswitch = data.get("case")
                value = data.get("value")
                if not mac_address or caseswitch is None or value is None:
                    return jsonify({"error": "缺少參數"}), 400
                self.device_commands[mac_address] = {
                    "case": int(caseswitch),
                    "value": int(value)
                }
                return jsonify({
                    "message": f"已設定指令給 {mac_address}",
                    "command": self.device_commands[mac_address]
                }), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/api/get_command/<mac_address>', methods=['GET'])
        def get_command(mac_address):
            command = self.device_commands.get(mac_address)
            if command:
                return jsonify({"has_command": True, "command": command})
            else:
                return jsonify({"has_command": False})

        # 新增一個 API，讓裝置在執行指令後可以回報
        @self.app.route('/api/command_executed/<mac_address>', methods=['POST'])
        def command_executed(mac_address):
            if mac_address in self.device_commands:
                del self.device_commands[mac_address]
                return jsonify({"success": True, "message": "指令已從佇列移除"})
            return jsonify({"success": False, "message": "指令不存在"})

        @self.app.route('/api/update_water_settings', methods=['POST'])
        def update_water_setting():
            try:
                data = request.get_json()
                plant_id = data.get("plant_id")
                enabled = data.get("enabled")
                threshold = data.get("threshold")
                print(threshold)
                if not plant_id or enabled is None or threshold is None:
                    return jsonify({"error": "缺少參數"}), 400

                # 取得植物的 MAC 位址
                plant = self.model.get_plant_by_id(plant_id)
                if not plant:
                    return jsonify({"error": "找不到此植物"}), 404
                
                mac_address = plant.mac_address

                self.device_commands[mac_address] = {
                    "case": 1, 
                    "value": int(threshold)
                }

                self.device_commands[mac_address] = {
                    "case": 4, 
                    "value": 1 if enabled else 0
                }
                return jsonify({
                    "message": "已設定澆水指令",
                    "mac_address": mac_address
                }), 200

            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/water_now', methods=['POST'])
        def water_now():
            try:
                data = request.get_json()
                plant_id = data.get("plant_id") # 接收 plant_id

                if not plant_id:
                    return jsonify({"error": "植物 ID 不能為空"}), 400

                # 透過 plant_id 查詢植物資料，包含 mac_address
                plant = self.model.get_plant_by_id(plant_id)
                if not plant:
                    return jsonify({"error": "找不到對應的植物。"}), 404
                
                mac_address = plant.mac_address
                
                # 設定立即澆水的指令
                command = {
                    "case": 3,
                    "value": 1
                }
                
                # 將指令儲存到暫存區
                self.device_commands[mac_address] = command
                
                logging.info(f"已設定立即澆水指令給 {mac_address} (植物 ID: {plant_id})")
                return jsonify({
                    "success": True, 
                    "message": f"已發送立即澆水指令給裝置 {mac_address}。",
                    "command": command
                }), 200
            except Exception as e:
                logging.error(f"發送立即澆水指令錯誤: {e}")
                return jsonify({"error": "無法發送立即澆水指令。"}), 500



# -----------------------------
# 啟動應用程式
# -----------------------------
if __name__ == '__main__':
    app = Flask(__name__)
    model = PlantModel(app)
    controller = PlantController(app, model)
    controller.app.run(debug=True, host='0.0.0.0', port=5000)