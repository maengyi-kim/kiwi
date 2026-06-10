/**
 * Kiwi EEPROM 存储 — 头文件
 */
#pragma once
#include <Arduino.h>

void     storage_init(void);
void     storage_write_u8(int addr, uint8_t val);
void     storage_write_u16(int addr, uint16_t val);
uint8_t  storage_read_u8(int addr);
uint16_t storage_read_u16(int addr);

bool     is_joined(void);
void     set_joined(uint16_t dev_addr);
void     reset_joined(void);
uint16_t get_dev_addr(void);

uint8_t  get_frame_counter(void);
void     set_frame_counter(uint8_t ctr);
void     increment_frame_counter(void);

uint8_t  get_saved_sf(void);
void     set_saved_sf(uint8_t sf);
uint8_t  get_saved_tx_power(void);
void     set_saved_tx_power(uint8_t p);
uint16_t get_report_interval(void);
void     set_report_interval(uint16_t iv);

// ─── 芯片 UID ───
uint16_t       get_uid_device_id(void);   // UID[10:11] → 0~65535
const uint8_t* get_uid_dev_eui(void);     // 8字节 DevEUI (UID[0:5]+UID[10:11])
