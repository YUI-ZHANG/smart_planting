#include <SoftwareSerial.h>
#include <DHT.h>

#define DHTPIN 4
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

int soilMoisturePin = A1;
int waterLevelPin = A2;
int ldrPin = A3;
int pumpPin = 5;
int lightPin = 6;

SoftwareSerial espSerial(2, 3); // RX, TX to ESP8266

unsigned long previousMillis = 0;
const long interval = 5000; // 60秒傳一次資料

// 閾值（可由 ESP8266 下發更新）
int soilHumidity = 40; // 土壤濕度閾值 (%)
int lightLimit = 65;   // 光照強度閾值 (%)
int waterTask = 0;
void setup() {
  Serial.begin(9600);
  espSerial.begin(9600);
  dht.begin();

  pinMode(pumpPin, OUTPUT);
  pinMode(lightPin, OUTPUT);

  Serial.println("✅ UNO 開始工作");
}

void loop() {
  // ---------------- 接收 ESP8266 指令 ----------------
  if (espSerial.available()) {
    String response = espSerial.readStringUntil('\n');
    response.trim();
    int commaIndex = response.indexOf(',');

    if (commaIndex > 0) {
      int caseswitch = response.substring(0, commaIndex).toInt();
      int condition = response.substring(commaIndex + 1).toInt();

      switch (caseswitch) {
        case 1:
          soilHumidity = condition;
          Serial.print("✅ 更新土壤濕度目標值: ");
          Serial.println(soilHumidity);
          break;
        case 2:
          lightLimit = condition;
          Serial.print("✅ 更新光照限制目標值: ");
          Serial.println(lightLimit);
          break;
        case 3:           
          watering();
          break;
        case 4:
          waterTask = condition;
          break;
        default:
          Serial.println("⚠️ 收到未知指令，忽略");
          break;
      }
    }
  }

  // ---------------- 感測器讀值 ----------------
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  int soilRaw = analogRead(soilMoisturePin);
  int waterRaw = analogRead(waterLevelPin);
  int lightRaw = analogRead(ldrPin);
  
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("❌ DHT 感測器讀取失敗");
    return;
  }
  
  // 轉換為百分比
  float soilPercent = map(soilRaw, 0, 1023, 0, 100); 
  float waterPercent = map(waterRaw, 0, 1023, 0, 100); 
  float lightPercent = 100 - map(lightRaw, 0, 1023, 0, 100);

  // ---------------- 控制設備 ----------------
  // 自動澆水
  if (soilPercent < soilHumidity && waterPercent > 10 && waterTask == 1) { 
    watering();
  }

  // 自動補光
  if (lightPercent < lightLimit) { 
    digitalWrite(lightPin, HIGH);
  } else {
    digitalWrite(lightPin, LOW);
  }
  
  // ---------------- 定時傳資料 ----------------
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    String data = String(temperature, 1) + "," +
                  String(humidity, 1) + "," +
                  String(soilPercent, 1) + "," +
                  String(lightPercent, 1);

    espSerial.println(data);
    Serial.println("📤 傳送資料給 ESP8266: " + data);
  }
}

void watering(){
  digitalWrite(pumpPin, HIGH);
  delay(1000);
  digitalWrite(pumpPin, LOW);
  delay(3000);
  
}
