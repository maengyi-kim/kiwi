# 厂区监控系统 — 设计文档

日期：2026-05-28
状态：设计阶段（不实施）
项目目录：~/monitor/

---

## 一、项目概述

### 目标

构建一套厂区环境监控系统，实时监测水产加工厂关键点位（冷库温湿度、水箱水位等），
数据通过 LoRa 无线传输到云服务器，用 Grafana 仪表盘展示，异常时通过微信告警。

### 成功标准

- 冷库温度数据实时可见（延迟 < 2 分钟）
- 温度超阈值时 30 秒内收到微信告警
- 传感器节点连续运行 7 天以上（电池供电场景）
- 新增监测点位只需：复制硬件 + 改设备ID + 刷新仪表盘

### 非目标（本期不做）

- 双向控制（如远程开关冷库压缩机）
- 视频监控
- 能耗统计
- PLC/工业总线对接

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        厂区                                  │
│                                                              │
│  ┌──────────────┐    LoRa 433MHz    ┌──────────────────┐    │
│  │ 传感器节点 #1 │ ───────────────→ │                  │    │
│  │ STM32+SX1278 │                  │   LoRa 网关       │    │
│  │ +DHT22/超声波 │                  │   ESP32+SX1278   │    │
│  └──────────────┘                  │   +WiFi           │    │
│                                    │                  │    │
│  ┌──────────────┐                  │   (厂区中心位置)   │    │
│  │ 传感器节点 #N │ ───────────────→ │   常电供电         │    │
│  └──────────────┘                  └────────┬─────────┘    │
│                                             │               │
└─────────────────────────────────────────────┼───────────────┘
                                              │ WiFi
                                              │ MQTT (TLS可选)
                                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    云服务器 47.80.20.236                      │
│                                                              │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ Mosquitto│───→│ Python       │───→│ PostgreSQL   │       │
│  │ MQTT     │    │ Ingest 服务   │    │ (+TimescaleDB)│      │
│  │ (Docker) │    │ (订阅+解析)   │    │              │       │
│  └──────────┘    └──────┬───────┘    └──────┬───────┘       │
│                         │                    │               │
│                         │ 告警判断            │ 数据查询       │
│                         ▼                    ▼               │
│                   ┌──────────┐        ┌──────────┐          │
│                   │ 微信通知  │        │ Grafana  │          │
│                   │ (Hermes) │        │ (Docker) │          │
│                   └──────────┘        └──────────┘          │
│                                           │                  │
│                                           │ nginx 反代       │
│                                           ▼                  │
│                                    kiwi.maengyi.top      │
└──────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级 | 组件 | 职责 |
|------|------|------|
| 传感器节点 | STM32 + 传感器 + LoRa | 定时采集、编码、LoRa发送、低功耗休眠 |
| LoRa网关 | ESP32 + LoRa + WiFi | 接收所有节点数据、校验、MQTT上云、心跳检测 |
| 消息层 | Mosquitto (Docker) | MQTT Broker，接收网关数据，分发给订阅者 |
| 数据处理 | Python Ingest 服务 | 订阅MQTT、解析二进制包、写入PostgreSQL、阈值告警 |
| 存储 | PostgreSQL + TimescaleDB | 存储所有传感器时序数据，自动分区和压缩 |
| 展示 | Grafana (Docker) | 仪表盘、历史曲线、页面告警 |
| 告警 | Hermes 微信网关 | 微信消息推送异常告警 |

---

## 三、硬件设计

### 3.1 传感器节点

```
┌────────────────────────────────────┐
│  STM32F103C8T6 (Blue Pill)         │
│                                    │
│  ┌──────────┐    ┌──────────────┐  │
│  │ SX1278   │    │ DHT22/HC-SR04│  │
│  │ LoRa模块  │    │ 传感器        │  │
│  │ SPI接口   │    │ GPIO/ADC     │  │
│  └──────────┘    └──────────────┘  │
│                                    │
│  供电：USB 5V 或 3.7V 18650 锂电池  │
│  功耗：采集~30mA，休眠~20μA         │
└────────────────────────────────────┘
```

**选型明细：**

| 组件 | 型号 | 单价(¥) | 用途 |
|------|------|---------|------|
| MCU | STM32F103C8T6 Blue Pill | ~12 | 主控 |
| LoRa | SX1278 (RA-02) | ~18 | 无线通信 |
| 温湿度 | DHT22 (AM2302) | ~15 | 冷库温湿度 |
| 水位 | HC-SR04 或 JSN-SR04T (防水) | ~10 | 水箱水位 |
| 供电 | USB 5V 或 18650+TP4056 | ~8 | 供电 |
| **单节点合计** | | **~55-63** | |

**冷库传感器注意：**
- DHT22 工作范围 -40~80°C，适合冷库环境
- 传感器探头放冷库内，STM32+LoRa 放冷库外（避免低温影响电子元件和电池）
- 用延长线（3-5米杜邦线即可，DHT22 信号可走几米）

**水箱传感器注意：**
- 用防水超声波 JSN-SR04T（IP67），普通 HC-SR04 怕水汽
- 安装在水箱顶部，向下测距
- 水位 = 水箱总高 - 测得距离

### 3.2 LoRa 网关

```
┌────────────────────────────────────┐
│  ESP32 (或 Heltec WiFi LoRa 32)    │
│                                    │
│  ┌──────────┐    ┌──────────────┐  │
│  │ SX1278   │    │ 内置 WiFi     │  │
│  │ LoRa接收  │    │ 连接路由器    │  │
│  └──────────┘    └──────────────┘  │
│                                    │
│  供电：USB 5V 常电（放办公室）       │
│  缓存：SPIFFS 可存数千条数据（断网时）│
└────────────────────────────────────┘
```

**选型：**

| 组件 | 型号 | 单价(¥) | 用途 |
|------|------|---------|------|
| MCU+WiFi+LoRa | Heltec WiFi LoRa 32 (V3) | ~90 | 一体化网关 |
| 或分开 | ESP32 开发板 + SX1278 | ~50 | 分立方案 |
| **网关合计** | | **~50-90** | |

推荐 Heltec WiFi LoRa 32，集成 OLED 显示屏可以直接看接收状态，省焊接。

---

## 四、通信协议

### 4.1 LoRa 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 频段 | 433 MHz | 中国免许可 ISM 频段 |
| 带宽 | 125 kHz | LoRa 标准带宽 |
| 扩频因子 | SF7-SF12 | SF7=快但近，SF12=慢但远 |
| 编码率 | 4/5 | |
| 发射功率 | 20 dBm (100mW) | SX1278 最大 |
| 速率 | 0.3-5.5 kbps | 取决于SF |

### 4.2 数据包格式

从传感器节点到网关，每包固定 10 字节：

```
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ Byte0│ Byte1│Byte2 │Byte3 │Byte4 │Byte5 │Byte6 │Byte7 │Byte8 │Byte9 │
├──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
│设备ID│设备ID│温度H │温度L │ 湿度 │水位H │水位L │ 电量 │ 状态 │ CRC8 │
│ 高位 │ 低位 │(×10)│(×10) │ (%)  │ (mm) │ (mm) │ (mV/20)│     │      │
└──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘

设备ID：0x0001-0xFFFE（支持65534个节点）
温度：  int16，实际值 = raw / 10（例如 -225 = -22.5°C）
湿度：  uint8，0-100%
水位：  uint16，毫米
电量：  uint8，实际值 = raw * 20 mV（例如 180 = 3600mV = 3.6V）
状态：  bit0=传感器正常, bit1=LoRa信号弱, bit2=低电量
CRC8：  前9字节的CRC-8校验
```

空字段（如纯温度节点没有水位）填 0xFFFF。

### 4.3 MQTT 拓扑

```
Topic 结构：
  monitor/{device_id}/data      — 传感器数据（网关→服务器）
  monitor/{device_id}/status    — 节点状态（在线/离线）
  monitor/gateway/status        — 网关状态

QoS：0（最多一次，丢了就等下一包）
Retain：否

Payload：JSON 格式（网关将二进制包转为JSON再发）
{
  "device_id": 1,
  "device_name": "冷库1号",
  "sensors": [
    {"type": "temperature", "value": -22.5, "unit": "°C"},
    {"type": "humidity",    "value": 65,   "unit": "%"}
  ],
  "battery": 3.6,
  "rssi": -85,
  "timestamp": 1716892800
}
```

---

## 五、服务端设计

### 5.1 PostgreSQL 数据表

```sql
-- 启用 TimescaleDB 扩展（时序优化）
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 主数据表
CREATE TABLE sensor_data (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INTEGER NOT NULL,
    device_name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,   -- 'temperature', 'humidity', 'water_level'
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT NOT NULL,   -- '°C', '%', 'cm'
    battery     DOUBLE PRECISION,
    rssi        INTEGER
);

-- 转为 TimescaleDB hypertable（自动按时间分区）
SELECT create_hypertable('sensor_data', 'time');

-- 自动压缩策略（7天后压缩旧数据）
SELECT add_compression_policy('sensor_data', INTERVAL '7 days');

-- 数据保留策略（90天后自动删除）
SELECT add_retention_policy('sensor_data', INTERVAL '90 days');
```

### 5.2 设备注册表

```sql
CREATE TABLE devices (
    device_id   INTEGER PRIMARY KEY,
    device_name TEXT NOT NULL,         -- "冷库1号"
    location    TEXT,                  -- "厂区东北角"
    sensor_types TEXT NOT NULL,         -- '["temperature","humidity"]'
    report_interval INTEGER DEFAULT 300, -- 上报间隔(秒)
    alarm_rules  JSONB,                -- 告警规则
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 告警规则示例
-- {"temperature": {"min": -25, "max": -18, "critical_max": -5},
--  "water_level": {"min": 30}}
```

### 5.3 Python Ingest 服务

`~/monitor/ingest/app.py`

```
职责：
1. 连接 Mosquitto，订阅 monitor/+/data
2. 收到消息 → 解析JSON → 写 sensor_data 表
3. 检查告警规则 → 触发告警
4. 检测心跳超时 → 标记离线

核心逻辑（伪代码）：

def on_message(topic, payload):
    data = json.loads(payload)
    device = get_device(data['device_id'])

    # 写入数据库
    for sensor in data['sensors']:
        db.insert(sensor_data, time=now(),
                  device_id=data['device_id'],
                  sensor_type=sensor['type'],
                  value=sensor['value'],
                  unit=sensor['unit'])

    # 检查告警
    for sensor in data['sensors']:
        rule = device.get_alarm_rule(sensor['type'])
        if rule and violates(sensor['value'], rule):
            send_alarm(device, sensor, rule)

    # 更新心跳
    update_heartbeat(data['device_id'])

运行方式：systemd 服务，开机自启。
依赖：paho-mqtt, psycopg2
```

### 5.4 告警通知

**Grafana 页面告警：**
- 在 Grafana 中配置 Alert Rules
- 温度 > -18°C 持续 5 分钟 → Warning
- 温度 > -5°C → Critical
- 水位 < 最低线 → Warning

**微信通知（Hermes 网关）：**
- Python ingest 服务检测到告警 → 调用 Hermes send_message API
- 或直接通过 HTTP POST 到 Hermes 的 webhook
- 告警消息示例："⚠️ 冷库1号温度异常：-12.5°C（阈值 -18°C），持续 5 分钟"

告警降噪：同类告警 30 分钟内不重复发送。

---

## 六、Grafana 仪表盘

### 6.1 部署

```bash
docker run -d --name grafana \
  -p 3001:3000 \
  -v ~/monitor/grafana:/var/lib/grafana \
  grafana/grafana
```

nginx 反代：`kiwi.maengyi.top` → `127.0.0.1:3001`

### 6.2 仪表盘布局

```
Dashboard: 厂区监控

Row 1 — 告警状态
  ┌─────────────────────────────────────────────┐
  │ ⚠️ 告警横幅（有异常时红色，无异常绿色"全部正常"）│
  └─────────────────────────────────────────────┘

Row 2 — 实时数据卡片（Stat Panel）
  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
  │ 冷库 #1   │ │ 冷库 #2   │ │ 水箱 #1   │ │ 水箱 #2   │
  │ -22.5°C  │ │ -20.1°C  │ │ 85 cm    │ │ 120 cm   │
  │ 65% RH   │ │ 60% RH   │ │           │ │           │
  │ 🟢正常    │ │ 🟢正常    │ │ 🟢正常    │ │ 🟢正常    │
  └──────────┘ └──────────┘ └──────────┘ └──────────┘

Row 3 — 温度历史曲线（Time Series Panel）
  ┌─────────────────────────────────────────────┐
  │ 冷库温度趋势 (最近 24 小时)                     │
  │ 📈 折线图，每个冷库一条线，-18°C 红色虚线标注    │
  └─────────────────────────────────────────────┘

Row 4 — 水位历史曲线
  ┌─────────────────────────────────────────────┐
  │ 水箱水位趋势                                   │
  │ 📈 折线图，最低水位红色虚线标注                   │
  └─────────────────────────────────────────────┘

Row 5 — 节点状态
  ┌─────────────────────────────────────────────┐
  │ 设备在线状态 + 电池电压 + LoRa 信号强度          │
  │ 📊 表格或状态面板                               │
  └─────────────────────────────────────────────┘
```

### 6.3 PostgreSQL 数据源配置

Grafana 直接连接 PostgreSQL：
- Host: localhost:5432
- Database: monitor (新建)
- 查询示例（温度曲线）：
  ```sql
  SELECT time, value
  FROM sensor_data
  WHERE device_name = '冷库1号'
    AND sensor_type = 'temperature'
    AND time > NOW() - INTERVAL '24 hours'
  ORDER BY time
  ```

---

## 七、固件设计

### 7.1 STM32 传感器节点固件

```
状态机：

  ┌─────────┐    采集完成    ┌─────────┐
  │  SLEEP  │──────────────→│ COLLECT │
  │ 低功耗   │               │ 读取传感器│
  └─────────┘               └────┬────┘
       ↑                         │
       │   定时器唤醒             │
       │   (RTC闹钟)             ▼
       │                   ┌─────────┐
       │                   │  SEND   │
       │                   │ LoRa发送 │
       │                   └────┬────┘
       │                        │
       │   发送完成             │
       └────────────────────────┘

核心逻辑：
1. RTC闹钟唤醒（间隔由设备注册表配置）
2. 读取传感器（DHT22 需等待 2 秒稳定）
3. 按协议打包 10 字节
4. SX1278 发送
5. 回到 SLEEP

工具箱：
- 开发环境：STM32CubeIDE 或 PlatformIO
- LoRa库：RadioLib (支持 SX1278)
- DHT22：自写或 DHTlib
- 低功耗：HAL_PWR_EnterSTOPMode()
```

### 7.2 ESP32 LoRa 网关固件

```
主循环：

  LOOP:
    1. 检查 LoRa 是否有数据包
       ├── 有 → CRC校验 → 解析二进制 → 转JSON → MQTT发布
       └── 无 → 继续

    2. 检查 WiFi 连接状态
       ├── 断连 → 数据缓存到 SPIFFS
       └── 恢复 → 补发缓存数据

    3. 检查节点心跳
       └── 超时节点 → 发送离线状态到MQTT

    4. 每60秒 → 发送网关自身状态

工具箱：
- 开发环境：Arduino IDE 或 PlatformIO
- LoRa：RadioLib
- WiFi：WiFi.h (内置)
- MQTT：PubSubClient
- JSON：ArduinoJson
```

---

## 八、项目目录结构

```
~/monitor/
├── README.md
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-28-factory-monitor-design.md  ← 本文档
├── firmware/
│   ├── node/            # STM32 传感器节点固件
│   │   ├── main.c
│   │   ├── sensors.c    # DHT22, HC-SR04 驱动
│   │   ├── lora.c       # SX1278 驱动
│   │   └── protocol.c   # 数据打包/解包
│   └── gateway/         # ESP32 网关固件
│       ├── main.cpp
│       ├── lora_rx.cpp
│       ├── mqtt.cpp
│       └── cache.cpp    # SPIFFS 缓存
├── ingest/              # Python 数据接入服务
│   ├── app.py           # 主程序（MQTT订阅→入库→告警）
│   ├── db.py            # 数据库操作
│   ├── alarm.py         # 告警逻辑
│   └── requirements.txt
├── grafana/             # Grafana 持久化数据（Docker volume）
├── sql/
│   └── init.sql         # 数据库初始化脚本
└── docker-compose.yml   # Mosquitto + Grafana
```

---

## 九、实施计划（概要，不执行）

| 阶段 | 内容 | 预估工时 |
|------|------|----------|
| Phase 1 | 云服务：Mosquitto + PostgreSQL + Python Ingest + Grafana | 1-2天 |
| Phase 2 | 硬件调试：STM32 + 传感器 + LoRa 收发 | 2-3天 |
| Phase 3 | 网关固件：ESP32 LoRa→MQTT 转发 | 1天 |
| Phase 4 | 联调：端到端数据跑通 | 1天 |
| Phase 5 | 告警：Grafana规则 + 微信通知 | 0.5天 |
| Phase 6 | 部署：systemd 服务 + nginx 反代 + 域名 | 0.5天 |

---

## 十、风险与注意事项

1. **LoRa 频段合规**：433MHz 在中国需满足发射功率 ≤ 10mW（某些解读为 100mW EIRP），使用 SX1278 设置为 20dBm 时在法律灰色地带，建议调至 10-13dBm（工厂内部几百米足够）。

2. **冷库金属屏蔽**：冷库墙壁含金属隔热层，LoRa 信号可能被大幅衰减。传感器节点尽量放冷库门口或信号可穿透的位置，传感器探头用延长线引入库内。

3. **PostgreSQL 已有实例**：当前服务器 PostgreSQL 端口 5432 已被其他应用占用。建议复用同一个实例，新建 `monitor` 数据库，避免额外开销。

4. **TimescaleDB 安装**：阿里云 Linux 3 的 PostgreSQL 版本需确认是否支持 TimescaleDB 扩展。如不支持，可降级为纯 PostgreSQL（不用自动分区），或使用 Docker 独立 PostgreSQL+TimescaleDB 实例。

5. **Grafana 认证**：默认 admin/admin，首次登录后必须改密码，否则公网暴露不安全。

6. **MQTT 安全**：Mosquitto 默认无认证。建议至少配置用户名密码认证，如走公网建议 TLS。

---

## 十一、附录：采购清单

| 物品 | 型号 | 数量 | 单价(¥) | 小计(¥) |
|------|------|------|---------|---------|
| STM32 Blue Pill | STM32F103C8T6 | N | ~12 | — |
| LoRa 模块 | SX1278 RA-02 | N+1 | ~18 | — |
| 温湿度传感器 | DHT22 | 按冷库数 | ~15 | — |
| 防水超声波 | JSN-SR04T | 按水箱数 | ~10 | — |
| LoRa 网关 | Heltec WiFi LoRa 32 V3 | 1 | ~90 | 90 |
| 杜邦线/面包板 | — | 若干 | ~20 | 20 |
| 18650 电池+座 | — | 按需 | ~10 | — |

(节点数量 N 由老板后续确定)
