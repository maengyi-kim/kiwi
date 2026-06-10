/**
 * Kiwi EEPROM 模拟 — STM32 Flash 最后1页模拟EEPROM
 * STM32F103C8T6: 64KB Flash, 最后一页 0x0800FC00
 * 
 * 简化版: 使用 Arduino 内置 EEPROM 库（STM32duino 支持）
 */

#include "storage.h"
#include "config.h"
#include <EEPROM.h>
#include <string.h>

// ─── 芯片 UID 缓存 ───
static uint8_t  uid_cache[12];
static bool     uid_loaded = false;

static void uid_load(void) {
    if (uid_loaded) return;
    for (int i = 0; i < 12; i++) {
        uid_cache[i] = *(volatile uint8_t*)(UID_BASE + i);
    }
    uid_loaded = true;
}

uint16_t get_uid_device_id(void) {
    uid_load();
    // device_id = UID 最后2字节
    return uid_cache[10] | ((uint16_t)uid_cache[11] << 8);
}

const uint8_t* get_uid_dev_eui(void) {
    uid_load();
    // DevEUI = UID[0:5] + UID[10:11]
    // 后2字节与 device_id 一致，网关可直接从 DevEUI 提取 device_id
    static uint8_t dev_eui[8];
    memcpy(dev_eui, uid_cache, 6);        // UID[0..5]
    dev_eui[6] = uid_cache[10];            // device_id low
    dev_eui[7] = uid_cache[11];            // device_id high
    return dev_eui;
}

// ─── EEPROM 底层 ───

void storage_init(void) {
    // STM32duino 的 EEPROM 库自动模拟
    EEPROM.init();
}

void storage_write_u8(int addr, uint8_t val) {
    EEPROM.write(addr, val);
}

void storage_write_u16(int addr, uint16_t val) {
    EEPROM.write(addr, val & 0xFF);
    EEPROM.write(addr + 1, (val >> 8) & 0xFF);
}

uint8_t storage_read_u8(int addr) {
    return EEPROM.read(addr);
}

uint16_t storage_read_u16(int addr) {
    return EEPROM.read(addr) | (EEPROM.read(addr + 1) << 8);
}

// ─── 高级存取 ───

bool is_joined(void) {
    return storage_read_u8(EE_JOINED) == 1;
}

void set_joined(uint16_t dev_addr) {
    storage_write_u16(EE_DEV_ADDR, dev_addr);
    storage_write_u8(EE_JOINED, 1);
}

void reset_joined(void) {
    storage_write_u8(EE_JOINED, 0);
}

uint16_t get_dev_addr(void) {
    return storage_read_u16(EE_DEV_ADDR);
}

uint8_t get_frame_counter(void) {
    return storage_read_u8(EE_FRAME_CTR);
}

void set_frame_counter(uint8_t ctr) {
    storage_write_u8(EE_FRAME_CTR, ctr);
}

void increment_frame_counter(void) {
    uint8_t ctr = get_frame_counter() + 1;
    if (ctr == 0) {
        // 回绕 → 需要重入网
        reset_joined();
    }
    set_frame_counter(ctr);
}

uint8_t get_saved_sf(void) {
    uint8_t sf = storage_read_u8(EE_SF);
    return (sf >= 7 && sf <= 12) ? sf : LORA_SF;
}

void set_saved_sf(uint8_t sf) {
    storage_write_u8(EE_SF, sf);
}

uint8_t get_saved_tx_power(void) {
    uint8_t p = storage_read_u8(EE_TX_POWER);
    return (p >= 2 && p <= 20) ? p : LORA_POWER;
}

void set_saved_tx_power(uint8_t p) {
    storage_write_u8(EE_TX_POWER, p);
}

uint16_t get_report_interval(void) {
    uint16_t iv = storage_read_u16(EE_REPORT_INT);
    return (iv > 0) ? iv : REPORT_INTERVAL;
}

void set_report_interval(uint16_t iv) {
    storage_write_u16(EE_REPORT_INT, iv);
}
