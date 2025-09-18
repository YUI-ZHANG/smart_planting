#include <ESP8266WiFi.h>
#include <DNSServer.h>
#include <ESP8266WebServer.h>
#include <WiFiManager.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <SoftwareSerial.h>
#include <EEPROM.h>
#include <ArduinoJson.h>

#define RESET_BUTTON_PIN 5
#define RESET_HOLD_TIME 3000

// 與 UNO 的序列通訊
SoftwareSerial espSerial(3, 2); // D3=RX, D2=TX (依接線調整)

// ---------------------- Google Sheets 和 Flask 設定 ----------------------
const String scriptURL = "https://script.google.com/macros/s/AKfycbxKlUToUPLQXHGg5FEeKMyOT-wgKDPIqqz7sxSPP5VCubhWEXAigUZaRq3yq1L-uFrF_Q/exec";
const String FLASK_SERVER_URL = "http://192.168.0.146:5000";

// 遠端檢查間隔（單位：毫秒）
const unsigned long RESET_CHECK_INTERVAL = 60 * 1000;
const unsigned long COMMAND_CHECK_INTERVAL = 5 * 1000;
unsigned long lastResetCheck = 0;
unsigned long lastCommandCheck = 0;

// 函式宣告
void registerDeviceAutomatically();
void checkRemoteReset();
void checkFlaskCommand();
String getMacAddressNoColon();

void setup() {
  Serial.begin(9600);
  espSerial.begin(9600);
  pinMode(RESET_BUTTON_PIN, INPUT_PULLUP);
  EEPROM.begin(256);

  // 使用 WiFiManager 連接 Wi-Fi
  WiFiManager wifiManager;
  if (!wifiManager.autoConnect("Plant-Setup")) {
    Serial.println("Wi-Fi 連線失敗，請手動重啟裝置。");
    delay(3000);
    ESP.restart();
  }

  Serial.println("✅ Wi-Fi 連線成功！");
  Serial.print("IP 位址: ");
  Serial.println(WiFi.localIP());

  // 自動註冊裝置
  registerDeviceAutomatically();
}

void loop() {
  String macAddress = getMacAddressNoColon();

  // ---- 接收 UNO 感測資料並上傳 Google Sheets ----
  if (espSerial.available()) {
    String sensorData = espSerial.readStringUntil('\n');
    sensorData.trim();
    Serial.println("從 UNO 接收到數據: " + sensorData);

    if (WiFi.status() == WL_CONNECTED) {
      WiFiClientSecure client;
      client.setInsecure();

      HTTPClient http;
      http.begin(client, scriptURL);
      http.addHeader("Content-Type", "application/x-www-form-urlencoded");
      http.setTimeout(10000);

      String postData = "data=" + sensorData + "&plantName=" + macAddress;
      int httpCode = http.POST(postData);

      if (httpCode > 0) {
        Serial.println("✅ 成功發送數據到 Google Sheets");
      } else {
        Serial.println("❌ 數據發送失敗: " + http.errorToString(httpCode));
      }
      http.end();
    } else {
      Serial.println("⚠️ Wi-Fi 未連線");
    }
  }

// ---- 定期檢查 Flask 重設指令 ----
if (millis() - lastResetCheck >= RESET_CHECK_INTERVAL) {
  checkRemoteReset();
  lastResetCheck = millis();
}

// ---- 定期檢查 Flask 控制指令 ----
if (millis() - lastCommandCheck >= COMMAND_CHECK_INTERVAL) {
  checkFlaskCommand();
  Serial.println(1);
  lastCommandCheck = millis();
}

  // ---- 長按按鈕清除 WiFi ----
  static unsigned long buttonPressTime = 0;
  static bool buttonPreviouslyPressed = false;
  bool buttonPressed = digitalRead(RESET_BUTTON_PIN) == LOW;

  if (buttonPressed && !buttonPreviouslyPressed) {
    buttonPressTime = millis();
    buttonPreviouslyPressed = true;
  }
  if (!buttonPressed && buttonPreviouslyPressed) {
    buttonPreviouslyPressed = false;
  }
  if (buttonPressed && (millis() - buttonPressTime >= RESET_HOLD_TIME)) {
    Serial.println("🛑 長按重置，清除 Wi-Fi 設定並重啟...");
    WiFiManager wifiManager;
    wifiManager.resetSettings();
    delay(2000);
    ESP.restart();
  }
}

// ---------------------- 函式定義 ----------------------

String getMacAddressNoColon() {
  String macAddress = WiFi.macAddress();
  macAddress.replace(":", "");
  return macAddress;
}

void registerDeviceAutomatically() {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClient client;
    HTTPClient http;

    String url = FLASK_SERVER_URL + "/api/register_device_auto";
    http.begin(client, url);
    http.addHeader("Content-Type", "application/json");

    String macAddress = getMacAddressNoColon();
    StaticJsonDocument<200> doc;
    doc["mac_address"] = macAddress;

    String jsonPostData;
    serializeJson(doc, jsonPostData);

    int httpCode = http.POST(jsonPostData);
    if (httpCode > 0) {
      Serial.printf("✅ 註冊回應: %d\n", httpCode);
      Serial.println("伺服器回應: " + http.getString());
    } else {
      Serial.println("❌ 註冊失敗: " + http.errorToString(httpCode));
    }
    http.end();
  }
}

void checkRemoteReset() {
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(0);
    WiFiClient client;
    HTTPClient http;

    String macAddress = getMacAddressNoColon();
    String url = FLASK_SERVER_URL + "/api/check_reset/" + macAddress;
    http.begin(client, url);

    int httpCode = http.GET();
    if (httpCode == HTTP_CODE_OK) {
      String payload = http.getString();
      StaticJsonDocument<200> doc;
      if (deserializeJson(doc, payload) == DeserializationError::Ok) {
        if (doc["reset_pending"]) {
          Serial.println("🛑 收到遠端重設，清除 Wi-Fi 設定並重啟...");
          WiFiManager wifiManager;
          wifiManager.resetSettings();
          delay(2000);
          ESP.restart();
        }
      }
    } else {
      Serial.println("⚠️ 檢查重設失敗: " + String(httpCode));
    }
    http.end();
  }
}

void checkFlaskCommand() {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClient client;
    HTTPClient http;

    String macAddress = getMacAddressNoColon();
    String url = FLASK_SERVER_URL + "/api/get_command/" + macAddress;
    http.begin(client, url);

    int httpCode = http.GET();
    if (httpCode == HTTP_CODE_OK) {
      String payload = http.getString();
      StaticJsonDocument<256> doc;
      if (deserializeJson(doc, payload) == DeserializationError::Ok) {
        if (doc["has_command"]) {
          int caseValue = doc["command"]["case"];
          int thresholdValue = doc["command"]["value"];
          String command = String(caseValue) + "," + String(thresholdValue);
          espSerial.println(command);  // 發送給 UNO
          Serial.println("➡️ 傳送給 UNO: " + command);
          
          // ⭐ 新增: 向伺服器回報指令已處理
          HTTPClient postHttp;
          WiFiClient postClient;
          String postUrl = FLASK_SERVER_URL + "/api/command_executed/" + getMacAddressNoColon();
          postHttp.begin(postClient, postUrl);
          postHttp.addHeader("Content-Type", "application/json");
          int postHttpCode = postHttp.POST("{}");
          Serial.printf("回報指令已處理，伺服器回應代碼: %d\n", postHttpCode);
          postHttp.end();
        }
      }
    } else {
      Serial.println("⚠️ 指令檢查失敗: " + String(httpCode));
    }
    http.end();
  }
}
