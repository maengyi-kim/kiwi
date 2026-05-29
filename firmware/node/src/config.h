/**
 * Kiwi 传感器节点 — 配置头文件
 * 
 * 按你的节点类型选择版本：
 *   温湿度节点: build_flags = -D KIWI_NODE
 *   水位计节点: build_flags = -D KIWI_WATER_NODE
 */

#pragma once
#include <Arduino.h>

// ─── 设备身份（出厂烧录，每个节点独立）───
#define DEV_EUI     {0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x00, 0x00, 0x01}  // 8字节 IEEE EUI-64
#define APP_KEY     {0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6, 0x07, 0x08, \
                     0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10}  // 16字节 AppKey
#define JOIN_EUI    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}  // 应用标识（与网关一致）

// ─── LoRa 引脚（SX1278 RA-02 → STM32F103 Blue Pill）───
#define LORA_NSS    PB12
#define LORA_DIO0   PB1
#define LORA_DIO1   PB10   // 预留，本期不用
#define LORA_RST    PB0
#define LORA_SCK    PB13
#define LORA_MISO   PB14
#define LORA_MOSI   PB15

// ─── 传感器引脚 ───
#define DHT22_PIN   PA0    // 温湿度传感器数据线
#define ULTR_TRIG   PB6    // 超声波 Trig
#define ULTR_ECHO   PB7    // 超声波 Echo (注意: 5V模块需串1kΩ电阻)
#define BAT_ADC     PA2    // 电池电压分压读取

// ─── 指示灯 ───
#define LED_PIN     PC13   // 板载LED（低电平亮）
#define LED_ON()    digitalWrite(LED_PIN, LOW)
#define LED_OFF()   digitalWrite(LED_PIN, HIGH)

// ─── LoRa 参数 ───
#define LORA_FREQ   433.975   // MHz, 默认CH4入网信道
#define LORA_BW     125.0     // kHz
#define LORA_SF     9         // 默认扩频因子（入网后ADR调整）
#define LORA_CR     5         // 4/5 编码率
#define LORA_POWER  13        // dBm 默认发射功率
#define LORA_PREAMBLE 8       // 前导码长度

// ─── 传感器 ───
#define DHT22_RETRY     3     // DHT22 读取重试次数
#define ULTR_TIMEOUT    30000 // 超声波超时(us)，对应 ~5m

// ─── 电池分压 ───
#define BAT_R1          100.0 // kΩ 上分压电阻
#define BAT_R2          100.0 // kΩ 下分压电阻
#define BAT_RATIO       ((BAT_R1 + BAT_R2) / BAT_R2)  // = 2.0

// ─── 定时 ───
#define REPORT_INTERVAL     300     // 上报间隔(秒)，默认5分钟
#define HEARTBEAT_INTERVAL  600     // 心跳间隔(秒)，默认10分钟
#define JOIN_RETRY_INTERVAL 30      // 入网重试间隔(秒)
#define RX_TIMEOUT_MS       2000    // 下行接收超时(ms)

// ─── 协议常量 ───
#define PROTOCOL_VERSION    0x01    // v1.1
#define MAX_PAYLOAD         255
#define MAX_FRAME_LEN       264     // 7(head) + 255(payload) + 2(CRC)

// ─── 消息类型 (v1.1) ───
#define MSG_SENSOR_DATA     0x00
#define MSG_DEVICE_STATUS   0x01
#define MSG_HEARTBEAT       0x18
#define MSG_HEARTBEAT_ACK   0x19
#define MSG_JOIN_REQ        0x1A
#define MSG_JOIN_ACCEPT     0x1B
#define MSG_LINK_ADR_REQ    0x1C
#define MSG_LINK_ADR_ANS    0x1D
#define MSG_LINK_CHECK_REQ  0x1E
#define MSG_LINK_CHECK_ANS  0x1F
#define MSG_WRITE_CONFIG    0x12
#define MSG_WRITE_CONFIG_ACK 0x13

// ─── 传感器类型编码 (TLV) ───
#define TLV_TEMPERATURE     0x01
#define TLV_HUMIDITY        0x02
#define TLV_WATER_LEVEL     0x03
#define TLV_BATTERY_MV      0x20
#define TLV_RSSI            0x22
#define TLV_SNR             0x23
#define TLV_UPTIME          0x24
#define TLV_FW_VERSION      0x25

// ─── EEPROM 模拟地址（STM32 Flash最后1KB模拟EEPROM）───
#define EE_DEV_ADDR     0x000   // uint16: 分配的短地址
#define EE_FRAME_CTR    0x004   // uint8: 上行帧计数器
#define EE_SF           0x008   // uint8: 当前扩频因子
#define EE_TX_POWER     0x00C   // uint8: 当前发射功率
#define EE_REPORT_INT   0x010   // uint16: 上报间隔
#define EE_JOINED       0x014   // uint8: 0=未入网, 1=已入网
