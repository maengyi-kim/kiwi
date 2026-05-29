/**
 * Kiwi v1.1 协议编解码
 * 
 * 帧格式 (7字节头):
 *   Byte0: [Ver(2b)|Confirmed(1b)|MsgType(5b)]
 *   Byte1-2: Target ID (小端)
 *   Byte3-4: Source ID (小端)
 *   Byte5: Frame Counter
 *   Byte6: Payload Length
 *   Byte7..N: Payload
 *   N+1..N+2: CRC16 (CCITT 0x1021)
 */

#include "protocol.h"
#include "config.h"
#include <string.h>

// CRC16-CCITT 查找表
static const uint16_t CRC16_TABLE[256] = {
    0x0000,0x1021,0x2042,0x3063,0x4084,0x50a5,0x60c6,0x70e7,
    0x8108,0x9129,0xa14a,0xb16b,0xc18c,0xd1ad,0xe1ce,0xf1ef,
    0x1231,0x0210,0x3273,0x2252,0x52b5,0x4294,0x72f7,0x62d6,
    0x9339,0x8318,0xb37b,0xa35a,0xd3bd,0xc39c,0xf3ff,0xe3de,
    0x2462,0x3443,0x0420,0x1401,0x64e6,0x74c7,0x44a4,0x5485,
    0xa56a,0xb54b,0x8528,0x9509,0xe5ee,0xf5cf,0xc5ac,0xd58d,
    0x3653,0x2672,0x1611,0x0630,0x76d7,0x66f6,0x5695,0x46b4,
    0xb75b,0xa77a,0x9719,0x8738,0xf7df,0xe7fe,0xd79d,0xc7bc,
    0x48c4,0x58e5,0x6886,0x78a7,0x0840,0x1861,0x2802,0x3823,
    0xc9cc,0xd9ed,0xe98e,0xf9af,0x8948,0x9969,0xa90a,0xb92b,
    0x5af5,0x4ad4,0x7ab7,0x6a96,0x1a71,0x0a50,0x3a33,0x2a12,
    0xdbfd,0xcbdc,0xfbbf,0xeb9e,0x9b79,0x8b58,0xbb3b,0xab1a,
    0x6ca6,0x7c87,0x4ce4,0x5cc5,0x2c22,0x3c03,0x0c60,0x1c41,
    0xedae,0xfd8f,0xcdec,0xddcd,0xad2a,0xbd0b,0x8d68,0x9d49,
    0x7e97,0x6eb6,0x5ed5,0x4ef4,0x3e13,0x2e32,0x1e51,0x0e70,
    0xff9f,0xefbe,0xdfdd,0xcffc,0xbf1b,0xaf3a,0x9f59,0x8f78,
    0x9188,0x81a9,0xb1ca,0xa1eb,0xd10c,0xc12d,0xf14e,0xe16f,
    0x1080,0x00a1,0x30c2,0x20e3,0x5004,0x4025,0x7046,0x6067,
    0x83b9,0x9398,0xa3fb,0xb3da,0xc33d,0xd31c,0xe37f,0xf35e,
    0x02b1,0x1290,0x22f3,0x32d2,0x4235,0x5214,0x6277,0x7256,
    0xb5ea,0xa5cb,0x95a8,0x8589,0xf56e,0xe54f,0xd52c,0xc50d,
    0x34e2,0x24c3,0x14a0,0x0481,0x7466,0x6447,0x5424,0x4405,
    0xa7db,0xb7fa,0x8799,0x97b8,0xe75f,0xf77e,0xc71d,0xd73c,
    0x26d3,0x36f2,0x0691,0x16b0,0x6657,0x7676,0x4615,0x5634,
    0xd94c,0xc96d,0xf90e,0xe92f,0x99c8,0x89e9,0xb98a,0xa9ab,
    0x5844,0x4865,0x7806,0x6827,0x18c0,0x08e1,0x3882,0x28a3,
    0xcb7d,0xdb5c,0xeb3f,0xfb1e,0x8bf9,0x9bd8,0xabbb,0xbb9a,
    0x4a75,0x5a54,0x6a37,0x7a16,0x0af1,0x1ad0,0x2ab3,0x3a92,
    0xfd2e,0xed0f,0xdd6c,0xcd4d,0xbdaa,0xad8b,0x9de8,0x8dc9,
    0x7c26,0x6c07,0x5c64,0x4c45,0x3ca2,0x2c83,0x1ce0,0x0cc1,
    0xef1f,0xff3e,0xcf5d,0xdf7c,0xaf9b,0xbfba,0x8fd9,0x9ff8,
    0x6e17,0x7e36,0x4e55,0x5e74,0x2e93,0x3eb2,0x0ed1,0x1ef0
};

static uint16_t crc16_ccitt(const uint8_t* data, int len) {
    uint16_t crc = 0xFFFF;
    for (int i = 0; i < len; i++) {
        crc = (crc << 8) ^ CRC16_TABLE[((crc >> 8) ^ data[i]) & 0xFF];
    }
    return crc;
}

// ─── 编码 ─────────────────────────────────────────────────

int build_frame_header(uint8_t* buf, uint8_t msg_type, bool confirmed,
                        uint16_t target_id, uint16_t src_id, uint8_t frame_ctr) {
    buf[0] = (PROTOCOL_VERSION << 6) | (confirmed ? (1 << 5) : 0) | (msg_type & 0x1F);
    buf[1] = target_id & 0xFF;
    buf[2] = (target_id >> 8) & 0xFF;
    buf[3] = src_id & 0xFF;
    buf[4] = (src_id >> 8) & 0xFF;
    buf[5] = frame_ctr;
    buf[6] = 0;  // payload length, filled later
    return 7;     // header length
}

int encode_sensor_data(uint8_t* buf, int max_len,
                        uint16_t src_id, uint8_t frame_ctr,
                        float temp, float humidity, float water_level,
                        uint16_t battery_mv, bool is_water_node) {
    int pos = build_frame_header(buf, MSG_SENSOR_DATA, false, 0xFFFF, src_id, frame_ctr);
    
    // TLV: temperature (0x01)
    if (temp > -900.0f) {
        int16_t t = (int16_t)(temp * 10);
        buf[pos++] = TLV_TEMPERATURE;
        buf[pos++] = 2;
        buf[pos++] = t & 0xFF;
        buf[pos++] = (t >> 8) & 0xFF;
    }
    
    // TLV: humidity (0x02) — only for non-water nodes
    if (!is_water_node && humidity >= 0) {
        buf[pos++] = TLV_HUMIDITY;
        buf[pos++] = 1;
        buf[pos++] = (uint8_t)humidity;
    }
    
    // TLV: water level (0x03)
    if (water_level >= 0) {
        uint16_t wl = (uint16_t)water_level;
        buf[pos++] = TLV_WATER_LEVEL;
        buf[pos++] = 2;
        buf[pos++] = wl & 0xFF;
        buf[pos++] = (wl >> 8) & 0xFF;
    }
    
    // Payload length
    buf[6] = pos - 7;
    
    // CRC16
    uint16_t crc = crc16_ccitt(buf, pos);
    buf[pos++] = crc & 0xFF;
    buf[pos++] = (crc >> 8) & 0xFF;
    
    return pos;  // total frame length
}

int encode_device_status(uint8_t* buf, int max_len,
                          uint16_t src_id, uint8_t frame_ctr,
                          uint16_t battery_mv, int8_t rssi, int8_t snr,
                          uint32_t uptime, uint16_t fw_ver) {
    int pos = build_frame_header(buf, MSG_DEVICE_STATUS, false, 0xFFFF, src_id, frame_ctr);
    
    // Battery
    buf[pos++] = TLV_BATTERY_MV; buf[pos++] = 2;
    buf[pos++] = battery_mv & 0xFF; buf[pos++] = (battery_mv >> 8) & 0xFF;
    
    // RSSI
    buf[pos++] = TLV_RSSI; buf[pos++] = 1;
    buf[pos++] = (uint8_t)rssi;
    
    // SNR
    buf[pos++] = TLV_SNR; buf[pos++] = 1;
    buf[pos++] = (uint8_t)snr;
    
    // Uptime
    buf[pos++] = TLV_UPTIME; buf[pos++] = 4;
    buf[pos++] = uptime & 0xFF;
    buf[pos++] = (uptime >> 8) & 0xFF;
    buf[pos++] = (uptime >> 16) & 0xFF;
    buf[pos++] = (uptime >> 24) & 0xFF;
    
    // FW Version
    buf[pos++] = TLV_FW_VERSION; buf[pos++] = 2;
    buf[pos++] = fw_ver & 0xFF; buf[pos++] = (fw_ver >> 8) & 0xFF;
    
    buf[6] = pos - 7;
    uint16_t crc = crc16_ccitt(buf, pos);
    buf[pos++] = crc & 0xFF;
    buf[pos++] = (crc >> 8) & 0xFF;
    
    return pos;
}

int encode_join_request(uint8_t* buf, int max_len,
                         const uint8_t* dev_eui, uint16_t dev_nonce) {
    int pos = build_frame_header(buf, MSG_JOIN_REQ, false, 0xFFFF, 0x0000, 0);
    
    // DevEUI (8 bytes)
    memcpy(&buf[pos], dev_eui, 8); pos += 8;
    // DevNonce (2 bytes, random)
    buf[pos++] = dev_nonce & 0xFF;
    buf[pos++] = (dev_nonce >> 8) & 0xFF;
    // JoinEUI (8 bytes)
    const uint8_t join_eui[8] = JOIN_EUI;
    memcpy(&buf[pos], join_eui, 8); pos += 8;
    
    buf[6] = pos - 7;
    uint16_t crc = crc16_ccitt(buf, pos);
    buf[pos++] = crc & 0xFF;
    buf[pos++] = (crc >> 8) & 0xFF;
    
    return pos;
}

int encode_heartbeat(uint8_t* buf, int max_len,
                      uint16_t src_id, uint8_t frame_ctr) {
    int pos = build_frame_header(buf, MSG_HEARTBEAT, false, 0xFFFF, src_id, frame_ctr);
    buf[6] = 0;
    uint16_t crc = crc16_ccitt(buf, pos);
    buf[pos++] = crc & 0xFF;
    buf[pos++] = (crc >> 8) & 0xFF;
    return pos;
}

int encode_link_adr_ans(uint8_t* buf, int max_len,
                         uint16_t src_id, uint8_t frame_ctr, uint8_t status) {
    int pos = build_frame_header(buf, MSG_LINK_ADR_ANS, false, 0xFFFF, src_id, frame_ctr);
    buf[pos++] = status;
    buf[6] = 1;
    uint16_t crc = crc16_ccitt(buf, pos);
    buf[pos++] = crc & 0xFF;
    buf[pos++] = (crc >> 8) & 0xFF;
    return pos;
}

// ─── 解码 ─────────────────────────────────────────────────

uint8_t parse_frame_type(const uint8_t* buf) {
    return buf[0] & 0x1F;
}

bool parse_frame_confirmed(const uint8_t* buf) {
    return (buf[0] >> 5) & 0x01;
}

uint16_t parse_target_id(const uint8_t* buf) {
    return buf[1] | (buf[2] << 8);
}

uint16_t parse_source_id(const uint8_t* buf) {
    return buf[3] | (buf[4] << 8);
}

uint8_t parse_frame_counter(const uint8_t* buf) {
    return buf[5];
}

uint8_t parse_payload_len(const uint8_t* buf) {
    return buf[6];
}

const uint8_t* parse_payload(const uint8_t* buf) {
    return &buf[7];
}

bool verify_crc(const uint8_t* buf, int total_len) {
    if (total_len < 9) return false;
    uint16_t expected = crc16_ccitt(buf, total_len - 2);
    uint16_t received = buf[total_len - 2] | (buf[total_len - 1] << 8);
    return expected == received;
}

int parse_join_accept(const uint8_t* buf, int total_len,
                       uint16_t* dev_addr, uint8_t* nwk_skey, uint8_t* app_skey) {
    if (total_len < 7 + 24) return 0;  // header + min join-accept payload
    
    const uint8_t* payload = parse_payload(buf);
    // Join-Accept payload: AppNonce(3) + NetID(3) + DevAddr(4) + DLSettings(1) + RxDelay(1) + CFList(16)
    *dev_addr = payload[6] | (payload[7] << 8) | (payload[8] << 16) | (payload[9] << 24);
    
    // 密钥派生 (简化版 - STM32硬件AES可用时展开)
    // NwkSKey = aes128(AppKey, 0x01|AppNonce|NetID|DevNonce|pad16)
    // AppSKey = aes128(AppKey, 0x02|AppNonce|NetID|DevNonce|pad16)
    // 本期不做完整AES（STM32F103有硬件AES但Arduino框架不便直接调）
    // 先用简单映射，正式部署时替换为硬件AES
    const uint8_t app_key[16] = APP_KEY;
    for (int i = 0; i < 16; i++) {
        nwk_skey[i] = app_key[i] ^ 0x01;
        app_skey[i] = app_key[i] ^ 0x02;
    }
    
    return 1;
}
