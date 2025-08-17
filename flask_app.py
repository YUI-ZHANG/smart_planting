from flask import Flask, jsonify
from sqlalchemy import create_engine
import pandas as pd
from flask_cors import CORS

app = Flask(__name__)
CORS(app) 

# 連接到你的資料庫
engine = create_engine('sqlite:///plant_data.db')

@app.route('/api/latest_data', methods=['GET'])
def get_latest_data():
    
    #從資料庫讀取最新的數據並以 JSON 格式回傳。
    
    try:
        query = "SELECT * FROM plant_data ORDER BY id DESC LIMIT 24"
        
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
            
        df = df.iloc[::-1]
        
        return jsonify(df.to_dict(orient='records'))
        
    except Exception as e:
        print(f"從資料庫讀取數據時發生錯誤: {e}")
        return jsonify({"error": "無法取得數據"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

#http://127.0.0.1:5000/api/latest_data