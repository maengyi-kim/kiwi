/**
 * Kiwi 传感器节点 — 主固件
 * 
 * 状态机: SLEEP → WAKE → SENSOR → SEND → LISTEN → SLEEP
 * 
 * 编译:
 *   温湿度节点: platformio run
 *   水位计节点: platformio run -e bluepill
 *   (在 platformio.ini 中通过 build_flags 区分)
 */

#include <RadioLib.h>
#include "config.h"
#include "sensors.h"
#include "protocol.h"
#include "storage.h"

// ─── 全局状态 ───
SX1278 radio = new Module(LORA_NSS, LORA_DIO0, LORA_RST, LORA_DIO1);
uint8_t tx_buf[MAX_FRAME_LEN];
uint8_t rx_buf[MAX_FRAME_LEN];
uint32_t boot_time;
uint32_t last_report = 0;
uint32_t last_heartbeat = 0;
uint32_t report_count = 0;

#ifdef KIWI_WATER_NODE
#define IS_WATER_NODE true
#else
#define IS_WATER_NODE false
#endif

// ─── 低功耗休眠 ───
void deep_sleep(uint32_t seconds) {
#ifdef KIWI_DEBUG
    Serial.print("Sleep ");
    Serial.print(seconds);
    Serial.println("s...");
    Serial.flush();
#endif
    LED_OFF();
    
    // STM32 STOP 模式 + RTC 闹钟唤醒
    // Arduino STM32duino: 用 LowPower 库或直接操作 RTC
    // 简化版: delay (开发调试用，正式版改 RTC)
    delay(seconds * 1000);
    
    LED_ON(); delay(50); LED_OFF();
#ifdef KIWI_DEBUG
    Serial.println("Wake!");
#endif
}

// ─── LoRa 收发 ───
bool lora_init(void) {
    int state = radio.begin(LORA_FREQ, LORA_BW, LORA_SF, LORA_CR, LORA_SF, LORA_PREAMBLE);
    if (state != RADIOLIB_ERR_NONE) {
#ifdef KIWI_DEBUG
        Serial.print("LoRa init failed: "); Serial.println(state);
#endif
        return false;
    }
    radio.setOutputPower(LORA_POWER);
    return true;
}

int lora_transmit(uint8_t* buf, int len) {
    LED_ON();
    int state = radio.transmit(buf, len);
    LED_OFF();
#ifdef KIWI_DEBUG
    if (state == RADIOLIB_ERR_NONE) {
        Serial.print("TX OK: "); Serial.print(len); Serial.println(" bytes");
    } else {
        Serial.print("TX fail: "); Serial.println(state);
    }
#endif
    return state;
}

int lora_receive(uint32_t timeout_ms) {
    int state = radio.receive(rx_buf, MAX_FRAME_LEN);
    // RadioLib receive 是阻塞的，这里简化处理
    // 实际项目中用 DIO0 中断 + startReceive()
    return state;
}

bool lora_listen(uint32_t timeout_ms) {
    // 切换为接收模式，等下行消息
    uint32_t start = millis();
    radio.startReceive();
    while (millis() - start < timeout_ms) {
        if (radio.available()) {
            int state = radio.readData(rx_buf, MAX_FRAME_LEN);
            if (state == RADIOLIB_ERR_NONE) {
                return true;
            }
        }
        delay(10);
    }
    radio.standby();
    return false;
}

// ─── 下行消息处理 ───
void handle_downlink(int rx_len) {
    if (!verify_crc(rx_buf, rx_len)) {
#ifdef KIWI_DEBUG
        Serial.println("Downlink CRC fail");
#endif
        return;
    }
    
    uint8_t type = parse_frame_type(rx_buf);
    uint16_t target = parse_target_id(rx_buf);
    uint16_t my_addr = get_dev_addr();
    
    // 检查目标地址是否匹配
    if (target != 0x0000 && target != my_addr) return;
    
#ifdef KIWI_DEBUG
    Serial.print("Downlink type=0x"); Serial.println(type, HEX);
#endif
    
    switch (type) {
        case MSG_JOIN_ACCEPT: {
            uint16_t dev_addr;
            uint8_t nwk_skey[16], app_skey[16];
            if (parse_join_accept(rx_buf, rx_len, &dev_addr, nwk_skey, app_skey)) {
                set_joined(dev_addr);
                set_frame_counter(0);
#ifdef KIWI_DEBUG
                Serial.print("Joined! DevAddr=0x");
                Serial.println(dev_addr, HEX);
#endif
                // 快速闪烁3次表示入网成功
                for (int i = 0; i < 3; i++) { LED_ON(); delay(100); LED_OFF(); delay(100); }
            }
            break;
        }
        case MSG_LINK_ADR_REQ: {
            // ADR: 调整速率
            const uint8_t* pl = parse_payload(rx_buf);
            uint8_t dr = pl[0];  // 0=SF12 .. 5=SF7
            uint8_t tx_power = pl[1];
            
            if (dr <= 5) {
                uint8_t new_sf = 12 - dr;
                set_saved_sf(new_sf);
                set_saved_tx_power(tx_power);
                radio.setSpreadingFactor(new_sf);
                radio.setOutputPower(tx_power);
            }
            
            // 应答
            uint8_t status = 0x0F;  // all OK
            int ans_len = encode_link_adr_ans(tx_buf, MAX_FRAME_LEN,
                                               my_addr, get_frame_counter(), status);
            increment_frame_counter();
            lora_transmit(tx_buf, ans_len);
#ifdef KIWI_DEBUG
            Serial.print("ADR: SF="); Serial.print(12-dr);
            Serial.print(", TX="); Serial.print(tx_power); Serial.println("dBm");
#endif
            break;
        }
        case MSG_WRITE_CONFIG: {
            // 配置写入(简化)
#ifdef KIWI_DEBUG
            Serial.println("Config write received");
#endif
            break;
        }
        case MSG_HEARTBEAT_ACK: {
            // 心跳应答（含校时）
#ifdef KIWI_DEBUG
            Serial.println("Heartbeat ACK");
#endif
            break;
        }
    }
}

// ─── OTAA 入网 ───
bool do_join(void) {
    const uint8_t dev_eui[8] = DEV_EUI;
    uint16_t dev_nonce = (uint16_t)(micros() & 0xFFFF);  // 伪随机
    
    int len = encode_join_request(tx_buf, MAX_FRAME_LEN, dev_eui, dev_nonce);
    
#ifdef KIWI_DEBUG
    Serial.println("Sending Join-Request...");
#endif
    
    int state = lora_transmit(tx_buf, len);
    if (state != RADIOLIB_ERR_NONE) return false;
    
    // 等 Join-Accept (2秒)
    delay(100);
    if (lora_listen(RX_TIMEOUT_MS)) {
        int rx_len = radio.getPacketLength();
        handle_downlink(rx_len);
        return is_joined();
    }
    
    return false;
}

// ─── 发送传感器数据 ───
void send_sensor_data(void) {
    float temp = -999, hum = -1, water = -1;
    
    // 读取传感器
    temp = read_temperature();
    
#ifndef KIWI_WATER_NODE
    hum = read_humidity();
#endif
    
#ifdef KIWI_WATER_NODE
    water = read_water_level();
#endif
    
    uint16_t bat_mv = read_battery_mv();
    
    int len = encode_sensor_data(tx_buf, MAX_FRAME_LEN,
                                  get_dev_addr(), get_frame_counter(),
                                  temp, hum, water, bat_mv, IS_WATER_NODE);
    increment_frame_counter();
    
    int state = lora_transmit(tx_buf, len);
    
#ifdef KIWI_DEBUG
    Serial.print("Sensors: T="); Serial.print(temp);
    if (!IS_WATER_NODE) { Serial.print(" H="); Serial.print(hum); }
    if (IS_WATER_NODE)  { Serial.print(" W="); Serial.print(water); }
    Serial.print(" Bat="); Serial.print(bat_mv); Serial.println("mV");
#endif
    
    report_count++;
    
    // 每20次上报检查是否需要 LinkCheck
    // 每30次上报附带 LinkCheckReq (通过MAC搭车, 本期简化: 直接发LinkCheckReq)
}

// ─── 发送心跳 ───
void send_heartbeat(void) {
    int len = encode_heartbeat(tx_buf, MAX_FRAME_LEN, get_dev_addr(), get_frame_counter());
    increment_frame_counter();
    lora_transmit(tx_buf, len);
#ifdef KIWI_DEBUG
    Serial.println("Heartbeat sent");
#endif
}

// ─── 主流程 ───
void setup() {
    pinMode(LED_PIN, OUTPUT);
    LED_ON();
    
#ifdef KIWI_DEBUG
    Serial.begin(115200);
    delay(2000);
    Serial.println("\n🥝 Kiwi Node starting...");
#ifdef KIWI_WATER_NODE
    Serial.println("Type: Water Level");
#else
    Serial.println("Type: Temperature/Humidity");
#endif
#endif
    
    boot_time = millis();
    storage_init();
    
    // 初始化 LoRa
    if (!lora_init()) {
        // LoRa 失败: 慢闪
        while (1) {
            LED_ON(); delay(500);
            LED_OFF(); delay(500);
        }
    }
    radio.setOutputPower(get_saved_tx_power());
    
#ifdef KIWI_DEBUG
    Serial.println("LoRa OK");
#endif
    
    // OTAA 入网
    if (!is_joined()) {
        while (!do_join()) {
#ifdef KIWI_DEBUG
            Serial.print("Join failed, retry in ");
            Serial.print(JOIN_RETRY_INTERVAL); Serial.println("s");
#endif
            LED_ON(); delay(200); LED_OFF();
            deep_sleep(JOIN_RETRY_INTERVAL);
        }
    }
    
    LED_OFF();
    last_report = millis();
    last_heartbeat = millis();
    
#ifdef KIWI_DEBUG
    Serial.print("DevAddr: 0x"); Serial.println(get_dev_addr(), HEX);
    Serial.println("Node ready ✓");
#endif
    
    // 立即发一次数据
    send_sensor_data();
    
    // 监听下行(2秒)
    if (lora_listen(2000)) {
        handle_downlink(radio.getPacketLength());
    }
}

void loop() {
    uint32_t now = millis();
    
    // 定时上报
    if (now - last_report >= get_report_interval() * 1000UL) {
        send_sensor_data();
        last_report = now;
        
        // 发送后监听1秒
        if (lora_listen(1000)) {
            handle_downlink(radio.getPacketLength());
        }
    }
    
    // 定时心跳
    if (now - last_heartbeat >= HEARTBEAT_INTERVAL * 1000UL) {
        send_heartbeat();
        last_heartbeat = now;
    }
    
    // 空闲时轻度休眠（100ms一次循环，省电）
    delay(100);
}
