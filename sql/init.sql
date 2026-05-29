-- 厂区监控系统 — 数据库初始化脚本
-- TimescaleDB + PostgreSQL 16

-- 启用 TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 设备注册表
CREATE TABLE IF NOT EXISTS devices (
    device_id   INTEGER PRIMARY KEY,
    dev_eui     TEXT UNIQUE NOT NULL,          -- 8字节十六进制 IEEE EUI-64
    device_name TEXT NOT NULL,                 -- "冷库1号"
    location    TEXT,                          -- "厂区东北角"
    sensor_types TEXT NOT NULL DEFAULT '[]',   -- JSON: ["temperature","humidity","water_level"]
    report_interval INTEGER DEFAULT 300,       -- 上报间隔(秒)
    heartbeat_interval INTEGER DEFAULT 600,    -- 心跳间隔(秒)
    alarm_rules  JSONB DEFAULT '{}',           -- 告警规则
    last_seen   TIMESTAMPTZ,                   -- 最后在线时间
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 告警规则示例:
-- {"temperature": {"min": -25, "max": -18, "critical_max": -5},
--  "water_level": {"min": 30, "max": 200},
--  "humidity": {"min": 30, "max": 90}}

-- 传感器数据主表（时序优化）
CREATE TABLE IF NOT EXISTS sensor_data (
    time        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    device_id   INTEGER NOT NULL,
    device_name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,           -- 'temperature', 'humidity', 'water_level'
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT NOT NULL DEFAULT '',-- '°C', '%', 'mm'
    battery     DOUBLE PRECISION,        -- 电池电压(V)
    rssi        INTEGER,                 -- LoRa信号强度(dBm)
    snr         DOUBLE PRECISION,        -- 信噪比(dB)
    frame_counter INTEGER DEFAULT 0,     -- 帧计数器
    data_rate   INTEGER DEFAULT 3        -- 数据率 0=SF12 .. 5=SF7
);

-- 转为 TimescaleDB hypertable（按周自动分区）
SELECT create_hypertable('sensor_data', 'time', if_not_exists => TRUE);

-- 7天后自动压缩旧数据
SELECT add_compression_policy('sensor_data', INTERVAL '7 days', if_not_exists => TRUE);

-- 90天后自动删除
SELECT add_retention_policy('sensor_data', INTERVAL '90 days', if_not_exists => TRUE);

-- 告警事件表
CREATE TABLE IF NOT EXISTS alarms (
    id          SERIAL PRIMARY KEY,
    device_id   INTEGER NOT NULL,
    device_name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    alarm_level TEXT NOT NULL DEFAULT 'warning',  -- 'warning', 'critical'
    message     TEXT NOT NULL,
    value       DOUBLE PRECISION,
    threshold   DOUBLE PRECISION,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    acknowledged BOOLEAN DEFAULT FALSE,
    ack_at      TIMESTAMPTZ
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_sensor_data_device_time 
    ON sensor_data (device_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_data_type_time 
    ON sensor_data (sensor_type, time DESC);
CREATE INDEX IF NOT EXISTS idx_alarms_device 
    ON alarms (device_id, created_at DESC);

-- 插入网关虚拟设备
INSERT INTO devices (device_id, dev_eui, device_name, location, sensor_types) 
VALUES (0, '0000000000000000', 'LoRa网关', '办公室', '[]')
ON CONFLICT (device_id) DO NOTHING;
