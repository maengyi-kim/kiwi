/**
 * Kiwi 传感器驱动 — 头文件
 */
#pragma once
#include <Arduino.h>

float read_temperature(void);
float read_humidity(void);
float read_water_level(void);
float read_battery_voltage(void);
uint16_t read_battery_mv(void);
void watchdog_init(void);
