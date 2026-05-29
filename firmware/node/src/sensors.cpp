/**
 * Kiwi 传感器驱动 — DHT22 温湿度 + HC-SR04 超声波 + 电池ADC
 */

#include "sensors.h"
#include "config.h"

// ─── DHT22 ───────────────────────────────────────────────

static uint8_t dht22_read_raw(uint8_t* data) {
    // DHT22 时序:
    // 1. MCU拉低18ms → 拉高40us
    // 2. DHT22拉低80us → 拉高80us（响应）
    // 3. DHT22发40bit数据（每bit: 50us低 + 26~70us高）
    
    pinMode(DHT22_PIN, OUTPUT);
    digitalWrite(DHT22_PIN, LOW);
    delay(18);                          // 拉低至少18ms
    noInterrupts();
    digitalWrite(DHT22_PIN, HIGH);
    delayMicroseconds(40);              // 拉高40us
    pinMode(DHT22_PIN, INPUT_PULLUP);
    
    // 等 DHT22 响应
    uint32_t timeout = micros();
    while (digitalRead(DHT22_PIN) == HIGH) {
        if (micros() - timeout > 100) { interrupts(); return 0; }
    }
    timeout = micros();
    while (digitalRead(DHT22_PIN) == LOW) {
        if (micros() - timeout > 100) { interrupts(); return 0; }
    }
    timeout = micros();
    while (digitalRead(DHT22_PIN) == HIGH) {
        if (micros() - timeout > 100) { interrupts(); return 0; }
    }
    
    // 读 40 bits
    for (int i = 0; i < 5; i++) {
        data[i] = 0;
        for (int b = 7; b >= 0; b--) {
            // 等低电平
            timeout = micros();
            while (digitalRead(DHT22_PIN) == LOW) {
                if (micros() - timeout > 100) { interrupts(); return 0; }
            }
            // 测高电平持续时间
            timeout = micros();
            while (digitalRead(DHT22_PIN) == HIGH) {
                if (micros() - timeout > 100) { interrupts(); return 0; }
            }
            if (micros() - timeout > 40) {
                data[i] |= (1 << b);  // >40us = bit 1
            }
        }
    }
    interrupts();
    
    // 校验
    uint8_t sum = data[0] + data[1] + data[2] + data[3];
    return (sum == data[4]) ? 1 : 0;
}

float read_temperature(void) {
    uint8_t data[5];
    for (int retry = 0; retry < DHT22_RETRY; retry++) {
        if (dht22_read_raw(data)) {
            int16_t raw = (data[0] << 8) | data[1];
            if (raw & 0x8000) {  // 负数
                raw = -(raw & 0x7FFF);
            }
            return raw / 10.0f;
        }
        delay(100);
    }
    return -999.0f;  // 读取失败
}

float read_humidity(void) {
    uint8_t data[5];
    for (int retry = 0; retry < DHT22_RETRY; retry++) {
        if (dht22_read_raw(data)) {
            uint16_t raw = (data[2] << 8) | data[3];
            return raw / 10.0f;
        }
        delay(100);
    }
    return -1.0f;
}

// ─── HC-SR04 超声波 ──────────────────────────────────────

float read_water_level(void) {
    // 发送 10us 脉冲
    pinMode(ULTR_TRIG, OUTPUT);
    digitalWrite(ULTR_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(ULTR_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(ULTR_TRIG, LOW);
    
    // 读回波
    pinMode(ULTR_ECHO, INPUT);
    uint32_t duration = pulseIn(ULTR_ECHO, HIGH, ULTR_TIMEOUT);
    
    if (duration == 0) {
        return -1.0f;  // 超时/无回波
    }
    
    // 距离 = 声速(343m/s) * 时间 / 2
    // distance(mm) = duration(us) * 0.343 / 2 = duration * 0.1715
    return duration * 0.1715f;
}

// ─── 电池 ────────────────────────────────────────────────

float read_battery_voltage(void) {
    // ADC 12bit, 3.3V 参考电压
    analogRead(BAT_ADC);  // 丢弃第一次（ADC稳定）
    delay(10);
    uint16_t adc = analogRead(BAT_ADC);
    float voltage = (adc / 4095.0f) * 3.3f * BAT_RATIO;
    return voltage;
}

uint16_t read_battery_mv(void) {
    return (uint16_t)(read_battery_voltage() * 1000);
}

// ─── 看门狗 ──────────────────────────────────────────────

void watchdog_init(void) {
    // IWDG: 独立看门狗，8秒超时
    // STM32F103 的 IWDG 用 LSI(40kHz)
    // IWDG 寄存器在 Arduino 环境下不能直接操作
    // 改用 HAL 函数或使用 RTC 闹钟做软看门狗
    #ifdef KIWI_DEBUG
    Serial.println("Watchdog: using software watchdog");
    #endif
}
