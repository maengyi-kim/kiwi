/**
 * Kiwi v1.1 协议编解码 — 头文件
 */
#pragma once
#include <Arduino.h>

// ─── 编码 ───
int  encode_sensor_data(uint8_t* buf, int max_len, uint16_t src_id, uint8_t frame_ctr,
                         float temp, float humidity, float water_level,
                         uint16_t battery_mv, bool is_water_node);
int  encode_device_status(uint8_t* buf, int max_len, uint16_t src_id, uint8_t frame_ctr,
                           uint16_t battery_mv, int8_t rssi, int8_t snr,
                           uint32_t uptime, uint16_t fw_ver);
int  encode_join_request(uint8_t* buf, int max_len, const uint8_t* dev_eui, uint16_t dev_nonce);
int  encode_heartbeat(uint8_t* buf, int max_len, uint16_t src_id, uint8_t frame_ctr);
int  encode_link_adr_ans(uint8_t* buf, int max_len, uint16_t src_id, uint8_t frame_ctr, uint8_t status);

// ─── 解码 ───
uint8_t  parse_frame_type(const uint8_t* buf);
bool     parse_frame_confirmed(const uint8_t* buf);
uint16_t parse_target_id(const uint8_t* buf);
uint16_t parse_source_id(const uint8_t* buf);
uint8_t  parse_frame_counter(const uint8_t* buf);
uint8_t  parse_payload_len(const uint8_t* buf);
const uint8_t* parse_payload(const uint8_t* buf);
bool     verify_crc(const uint8_t* buf, int total_len);
int      parse_join_accept(const uint8_t* buf, int total_len,
                            uint16_t* dev_addr, uint8_t* nwk_skey, uint8_t* app_skey);
