# 🥝 Kiwi — 厂区环境监控系统

水产加工厂温湿度、水位实时监控。LoRa 无线传感 + Grafana 仪表盘 + 微信告警。

## 架构

```
传感器节点(STM32+SX1278,~100个) ──LoRa 433MHz──▶ ESP32网关 ──MQTT──▶ 云服务器
                                                                    │
                                                    ┌───────────────┼───────────────┐
                                                    ▼               ▼               ▼
                                               Python Ingest   TimescaleDB     Grafana
                                               (解析→入库→告警)  (时序存储)    (仪表盘)
```

## 目录

```
~/monitor/
├── README.md           ← 你在这里
├── docs/superpowers/specs/
│   ├── factory-monitor-design.md    # 系统设计文档
│   ├── hardware-guide.md            # 硬件实现指南 + 到货接线
│   └── lora-protocol.md             # v1.1 私有 LoRa 协议规范
├── sql/
│   └── init.sql                     # 数据库建表脚本
├── ingest/
│   ├── app.py                       # MQTT→TimescaleDB 接入服务
│   └── requirements.txt
├── tools/
│   ├── sim-sensor.py                # 命令行模拟器
│   └── sim-web.py                   # Web 控制台模拟器
├── firmware/
│   ├── node/                        # STM32 传感器节点固件
│   │   ├── platformio.ini
│   │   └── src/
│   │       ├── config.h             # 引脚/参数/协议常量
│   │       ├── main.cpp             # 主状态机（入网→休眠→采集→发送）
│   │       ├── sensors.cpp/h        # DHT22 + HC-SR04 + 电池ADC
│   │       ├── protocol.cpp/h       # v1.1 协议编解码
│   │       └── storage.cpp/h        # EEPROM 模拟存储
│   └── gateway/                     # ESP32 网关固件
│       ├── platformio.ini
│       └── src/main.cpp             # LoRa→MQTT 双向转发 + OLED + 心跳检测
├── nginx-kiwi.conf                  # nginx 配置
├── grafana-fresh/                   # Grafana 数据（Podman 挂载）
├── mosquitto/                       # MQTT 数据
├── pgdata/                          # TimescaleDB 数据
└── venv/                            # Python 虚拟环境
```

## 服务端口

| 服务 | 端口 | 类型 | 管理 |
|------|------|------|------|
| TimescaleDB | 5433 | Podman | systemd --user |
| Mosquitto MQTT | 1883 | Podman | systemd --user |
| Python Ingest | — | Python | systemd --user (monitor-ingest) |
| Grafana | 3001 | Podman | systemd --user |
| 模拟器 Web | 8081 | Python | 手动启动 |

## 常用命令

```bash
# 查看服务状态
systemctl --user status monitor-ingest container-monitor-db container-monitor-mqtt container-monitor-grafana

# 查看容器
podman ps

# 数据库直连
podman exec monitor-db psql -U postgres -d monitor

# MQTT 测试消息
podman exec monitor-mqtt mosquitto_pub -t "monitor/1/data" -m '{"device_id":1,"sensors":[{"type":"temperature","value":-22.5}]}'

# 模拟器 Web 控制台
cd ~/monitor && source venv/bin/activate && python tools/sim-web.py 8081

# 模拟器命令行
cd ~/monitor && source venv/bin/activate && python tools/sim-sensor.py once

# Grafana 仪表盘
http://localhost:3001/d/factory-monitor  (匿名访问)
域名: kiwi.maengyi.top (DNS 待配)

# 重启所有服务
systemctl --user restart monitor-ingest container-monitor-db container-monitor-mqtt container-monitor-grafana
```

## 协议

私有 LoRa 协议 v1.1，吸收 LoRaWAN 精华（ADR、OTAA 入网、帧计数器防重放、MAC 搭车、跳频）。
详见 [lora-protocol.md](docs/superpowers/specs/2026-05-28-lora-protocol.md)。

## 硬件

已采购 ¥210（ESP32网关 + STM32节点 + DHT22 + SX1278等）。
详见 [hardware-guide.md](docs/superpowers/specs/2026-05-28-hardware-guide.md)。
