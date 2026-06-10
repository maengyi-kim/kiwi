/**
 * Kiwi LoRa 网关 — ESP32 固件 v2.0
 * 
 * 功能:
 *   1. 监听所有节点 LoRa 上行数据
 *   2. 解析二进制包 → JSON → HTTP POST 上报
 *   3. OLED 显示状态（收包数、WiFi、HTTP）
 *   4. WiFi 断连时 SPIFFS 缓存
 *   5. 节点心跳超时检测
 *
 * v2.0 变更: MQTT → HTTP POST (kiwi.maengyi.top/ingest)
 *
 * 下行控制: TODO — 后续通过 HTTP 轮询 /ctrl/poll 实现
 */

#include <Arduino.h>
#include <WiFi.h>
#include <SPIFFS.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <RadioLib.h>

// ─── 配置 ───
const char* WIFI_SSID     = "302";
const char* WIFI_PASS     = "1380700700";
const char* SERVER_HOST   = "kiwi.maengyi.top";
const int   SERVER_PORT   = 443;
const char* INGEST_PATH   = "/ingest";

// LoRa 引脚 (Heltec WiFi LoRa 32 V3)
#define LORA_NSS    8
#define LORA_DIO0   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

// OLED (Heltec 内置)
#ifdef OLED_ENABLED
#include <U8x8lib.h>
U8X8_SSD1306_128X64_NONAME_HW_I2C u8x8(/*reset=*/21, /*scl=*/18, /*sda=*/17);
#endif

// ─── 全局 ───
SX1262 radio = new Module(LORA_NSS, LORA_DIO0, LORA_RST, LORA_BUSY);
WiFiClientSecure sslClient;

uint32_t pkt_count = 0;
uint32_t last_status = 0;
bool wifi_connected = false;

// 心跳跟踪 (device_id → last_seen millis)
#define MAX_NODES 200
struct NodeHeartbeat {
    uint16_t device_id;
    uint32_t last_seen;
};
NodeHeartbeat node_hb[MAX_NODES];
int node_count = 0;

// ─── CRC16 (与节点协议一致) ───
static uint16_t crc16_ccitt(const uint8_t* data, int len) {
    uint16_t crc = 0xFFFF;
    for (int i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x8000) crc = (crc << 1) ^ 0x1021;
            else crc <<= 1;
        }
    }
    return crc;
}

// ─── OLED ───
void oled_update(void) {
#ifdef OLED_ENABLED
    static char line1[17], line2[17], line3[17];
    snprintf(line1, 17, "Kiwi GW   Pkts:%u", pkt_count);
    snprintf(line2, 17, "WiFi:%s", wifi_connected ? "OK" : "NO");
    snprintf(line3, 17, "HTTP:%s  Nodes:%d",
             "OK", node_count);  // simplified
    u8x8.clear();
    u8x8.drawString(0, 0, line1);
    u8x8.drawString(0, 2, line2);
    u8x8.drawString(0, 4, line3);
#endif
}

// ─── 节点心跳跟踪 ───
void update_node_heartbeat(uint16_t device_id) {
    for (int i = 0; i < node_count; i++) {
        if (node_hb[i].device_id == device_id) {
            node_hb[i].last_seen = millis();
            return;
        }
    }
    if (node_count < MAX_NODES) {
        node_hb[node_count].device_id = device_id;
        node_hb[node_count].last_seen = millis();
        node_count++;
    }
}

// ─── 协议解析: 二进制 → JSON ───
String parse_sensor_payload(const uint8_t* payload, int len, uint16_t src_id) {
    JsonDocument doc;
    doc["device_id"] = src_id;
    JsonArray sensors = doc["sensors"].to<JsonArray>();
    
    int i = 0;
    while (i < len - 1) {
        uint8_t type = payload[i];
        uint8_t vlen = payload[i + 1];
        if (i + 2 + vlen > len) break;
        
        const uint8_t* val = &payload[i + 2];
        JsonObject s = sensors.add<JsonObject>();
        
        switch (type) {
            case 0x01: { // Temperature (int16, 0.1°C)
                int16_t raw = val[0] | (val[1] << 8);
                s["type"] = "temperature";
                s["value"] = raw / 10.0;
                s["unit"] = "°C";
                break;
            }
            case 0x02: { // Humidity (uint8, %)
                s["type"] = "humidity";
                s["value"] = (int)val[0];
                s["unit"] = "%";
                break;
            }
            case 0x03: { // Water level (uint16, mm)
                s["type"] = "water_level";
                s["value"] = val[0] | (val[1] << 8);
                s["unit"] = "mm";
                break;
            }
            default:
                s["type"] = "unknown";
                s["value"] = 0;
                break;
        }
        i += 2 + vlen;
    }
    
    String json;
    serializeJson(doc, json);
    return json;
}

// ─── HTTP POST ───
bool http_post_to_ingest(String json) {
    if (!wifi_connected) {
        // SPIFFS 缓存
        File f = SPIFFS.open("/queue.dat", "a");
        if (f) {
            f.println(json);
            f.close();
        }
        return false;
    }

    HTTPClient http;
    String url = "https://" + String(SERVER_HOST) + String(INGEST_PATH);
    http.begin(sslClient, url);
    http.addHeader("Content-Type", "application/json");

    int code = http.POST(json);
    bool ok = (code == 200);
    
    if (ok) {
        Serial.printf("↑ HTTP OK (%d bytes)\n", json.length());
    } else {
        Serial.printf("↑ HTTP FAIL code=%d\n", code);
    }

    http.end();
    return ok;
}

// ─── 二进制帧处理 ───
void handle_lora_packet(const uint8_t* buf, int total_len) {
    if (total_len < 9) return;

    // CRC
    uint16_t frame_crc = buf[total_len-2] | (buf[total_len-1] << 8);
    if (crc16_ccitt(buf, total_len - 2) != frame_crc) {
        Serial.println("CRC fail");
        return;
    }
    
    uint8_t msg_type = buf[0] & 0x1F;
    uint16_t src_id  = buf[3] | (buf[4] << 8);
    uint8_t  plen    = buf[6];
    const uint8_t* payload = &buf[7];
    
    update_node_heartbeat(src_id);
    pkt_count++;
    
    switch (msg_type) {
        case 0x00: { // Sensor Data
            String json = parse_sensor_payload(payload, plen, src_id);
            http_post_to_ingest(json);
            Serial.printf("↑ data dev=%d len=%d\n", src_id, plen);
            break;
        }
        case 0x01:   // Device Status
            http_post_to_ingest("{\"device_id\":" + String(src_id) + ",\"type\":\"status\"}");
            break;
        case 0x18:   // Heartbeat
            http_post_to_ingest("{\"device_id\":" + String(src_id) + ",\"type\":\"heartbeat\"}");
            break;
        case 0x1A: { // Join Request
            // device_id 从 DevEUI 的后2字节提取（与节点 UID 一致）
            uint16_t device_id = payload[6] | ((uint16_t)payload[7] << 8);
            String json = "{\"dev_eui\":\"";
            for (int i = 0; i < 8; i++) {
                char hex[3]; snprintf(hex, 3, "%02X", payload[i]);
                json += hex;
            }
            json += "\",\"device_id\":" + String(device_id) + "}";
            http_post_to_ingest(json);
            Serial.printf("↑ join dev=%d\n", device_id);
            break;
        }
        default:
            Serial.printf("Unknown type 0x%02X from dev %d\n", msg_type, src_id);
            break;
    }
}

// ─── WiFi ───
bool connect_wifi(void) {
    Serial.printf("WiFi: %s", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int retry = 0;
    while (WiFi.status() != WL_CONNECTED && retry < 30) {
        delay(500);
        Serial.print(".");
        retry++;
    }
    wifi_connected = (WiFi.status() == WL_CONNECTED);
    if (wifi_connected) {
        Serial.printf("\nWiFi OK IP=%s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\nWiFi FAIL");
    }
    return wifi_connected;
}

// ─── SPIFFS 缓存回放 ───
void replay_spiffs_queue(void) {
    if (!wifi_connected) return;
    File f = SPIFFS.open("/queue.dat", "r");
    if (!f || f.size() == 0) {
        if (f) f.close();
        return;
    }
    
    Serial.println("Replaying SPIFFS queue...");
    int replayed = 0;
    while (f.available()) {
        String line = f.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            if (http_post_to_ingest(line)) {
                replayed++;
            } else {
                break;  // 网络断了，下次再试
            }
        }
    }
    f.close();
    
    if (replayed > 0) {
        // 清空已发送的
        SPIFFS.remove("/queue.dat");
        Serial.printf("Replayed %d queued packets\n", replayed);
    }
}

// ─── Setup ───
void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n🥝 Kiwi Gateway v2.0 (HTTP) starting...");
    
#ifdef OLED_ENABLED
    u8x8.begin();
    u8x8.setFont(u8x8_font_chroma48medium8_r);
    u8x8.drawString(0, 0, "Kiwi GW v2 boot...");
#endif
    
    // SPIFFS
    if (!SPIFFS.begin(true)) {
        Serial.println("SPIFFS fail");
    }
    
    // LoRa
    int state = radio.begin(433.975, 125.0, 9, 5, 0x12, 8);
    if (state != RADIOLIB_ERR_NONE) {
        Serial.printf("LoRa fail: %d\n", state);
        while (1) delay(1000);
    }
    radio.setOutputPower(10);
    radio.startReceive();
    Serial.println("LoRa RX ready");
    
    // SSL (跳过证书验证用于内网/自签场景)
    sslClient.setInsecure();
    
    // WiFi
    connect_wifi();
    
    // 回放缓存
    replay_spiffs_queue();
    
    oled_update();
    Serial.println("Gateway ready ✓");
}

// ─── Loop ───
void loop() {
    // 1. LoRa 收包
    if (radio.available()) {
        uint8_t buf[264];
        int state = radio.readData(buf, sizeof(buf));
        if (state == RADIOLIB_ERR_NONE) {
            int len = radio.getPacketLength();
            handle_lora_packet(buf, len);
        }
        radio.startReceive();
    }
    
    // 2. WiFi 重连
    if (!wifi_connected) {
        static uint32_t last_wifi_retry = 0;
        if (millis() - last_wifi_retry > 30000) {
            last_wifi_retry = millis();
            wifi_connected = connect_wifi();
            if (wifi_connected) replay_spiffs_queue();
        }
    }
    
    // 3. 心跳检查
    static uint32_t last_hb_check = 0;
    if (millis() - last_hb_check > 60000) {
        last_hb_check = millis();
        for (int i = 0; i < node_count; i++) {
            if (millis() - node_hb[i].last_seen > 600000) {
                http_post_to_ingest(
                    "{\"device_id\":" + String(node_hb[i].device_id) + ",\"type\":\"offline\"}");
            }
        }
    }
    
    // 4. 状态更新 + 网关心跳 (每 60s)
    if (millis() - last_status > 60000) {
        last_status = millis();
        oled_update();
        String gw_json = "{\"gateway_id\":\"kiwi-gateway-01\",\"nodes\":" +
                         String(node_count) + ",\"pkts\":" + String(pkt_count) + "}";
        http_post_to_ingest(gw_json);
    }
    
    delay(1);
}
