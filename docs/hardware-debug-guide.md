# Kiwi 硬件调试手册 — 本地操作

> 在本地电脑上操作（需要 USB 口连接开发板）

---

## 0. 准备工作

### 环境安装（Linux/Mac）
```bash
# 安装 PlatformIO
python3 -m pip install platformio

# 安装串口工具
pip install pyserial

# 验证
pio --version
```

### 需要的硬件
- [x] Heltec WiFi LoRa 32 V3 (网关)
- [x] STM32F103C8T6 Blue Pill (节点)
- [x] SX1278 LoRa 模块 RA-02
- [x] DHT22 温湿度传感器模块
- [x] CH340 USB-TTL 模块
- [x] 面包板 + 杜邦线
- [x] 18650 电池 + TP4056 + MT3608
- [x] 433MHz 弹簧天线

---

## 第一步：到货检查（5分钟）

| 项目 | 操作 | 预期 |
|------|------|------|
| STM32 Blue Pill | 接 USB → 看板载 LED | PC13 LED 亮 |
| Heltec V3 | 接 USB → 看 OLED | OLED 亮，显示内容 |
| 18650 电池 | 万用表测电压 | ≥ 3.6V |
| SX1278 模块 | 目视 | 天线座完好 |
| DHT22 模块 | 目视 | 4 针完好 |

---

## 第二步：固件配置修改

在服务器上已经改好了，拉取最新代码到本地：

```bash
# 本地电脑上
cd ~/kiwi   # 或你 clone 的位置
git pull
```

### 需要手动改的配置（只有2处）

**1. 网关 WiFi** — 编辑 `firmware/gateway/src/main.cpp` 第21-22行：
```cpp
const char* WIFI_SSID     = "YOUR_WIFI_SSID";     // ← 改成真实 WiFi
const char* WIFI_PASS     = "YOUR_WIFI_PASSWORD";  // ← 改成真实密码
```

MQTT Broker IP 已确认是 `47.80.20.236`，不用改。

**2. 节点 DEV_EUI** — 编辑 `firmware/node/src/config.h` 第13行：
```cpp
#define DEV_EUI     {0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x00, 0x00, 0x01}
```
每个节点的最后2字节要不同，例如：
- 节点1: `0x00, 0x01`
- 节点2: `0x00, 0x02`
- 节点3: `0x00, 0x03`

---

## 第三步：STM32 接线

### 3.1 烧录线（CH340 → STM32）

```
CH340 USB-TTL         STM32 Blue Pill
─────────────────     ────────────────
TX         ────────── PA10 (RX)
RX         ────────── PA9  (TX)
3.3V       ────────── 3.3V
GND        ────────── GND
```

STM32 跳线帽：**BOOT0=1**（编程模式，烧录时）
烧完后跳回 BOOT0=0（运行模式）

### 3.2 DHT22 温湿度传感器

```
DHT22 模块            STM32
─────────────────     ────────────────
VCC        ────────── 3.3V
DATA       ────────── PA0
GND        ────────── GND
```
注意：DHT22 模块（带小板的那种）已内置 4.7kΩ 上拉电阻，不需要外加。

### 3.3 SX1278 LoRa 模块

```
SX1278 RA-02          STM32
─────────────────     ────────────────
VCC        ────────── 3.3V
GND        ────────── GND
NSS        ────────── PB12
SCK        ────────── PB13
MISO       ────────── PB14
MOSI       ────────── PB15
RST        ────────── PB0
DIO0       ────────── PB1
```

⚠️ **天线必须先接上再通电！不接天线发射可能烧模块。**

### 3.4 电池分压（可选，调试阶段可跳过）

```
电池(+) ─── 100kΩ ───┬── 100kΩ ─── GND
                      │
                     PA2 (ADC)
```

---

## 第四步：编译 & 烧录

### 4.1 编译网关固件

```bash
cd ~/kiwi/firmware/gateway
pio run
```

首次编译会下载依赖（RadioLib、PubSubClient、ArduinoJson），等几分钟。

### 4.2 烧录网关

```bash
# Heltec V3 接 USB，选择对应端口
pio run -t upload

# 或者指定端口
pio run -t upload --upload-port /dev/ttyUSB0
```

烧完后打开串口监视器看输出：
```bash
pio device monitor -b 115200
```

应该看到：
```
🥝 Kiwi Gateway starting...
LoRa RX ready
WiFi: YOUR_SSID
WiFi OK IP=192.168.x.x
MQTT OK
Gateway ready ✓
```

### 4.3 编译节点固件

```bash
cd ~/kiwi/firmware/node
pio run
```

### 4.4 烧录节点

```bash
# STM32 BOOT0=1（编程模式）
pio run -t upload --upload-port /dev/ttyUSB0

# 烧完 → BOOT0=0（运行模式）→ 按 RESET
pio device monitor -b 115200
```

看到输出即表示节点启动正常。

---

## 第五步：端到端验证

### 5.1 服务器端（在云服务器上操作，Max 会配合拉起服务）

先确认服务端跑起来了（TimescaleDB + Mosquitto + Ingest + Grafana）。

### 5.2 节点发数据 → 网关接收

节点上电后自动：
1. 入网（Join Request → Join Accept）
2. 采集 DHT22 数据
3. LoRa 发送到网关

网关串口应看到：
```
↑ data dev=1 len=12
```

### 5.3 网关 → MQTT → 数据库

在服务器上验证：
```bash
# 订阅 MQTT 看有没有数据
podman exec monitor-mqtt mosquitto_sub -t "monitor/+/data" -v

# 查数据库
podman exec monitor-db psql -U postgres -d monitor -c "SELECT * FROM sensor_data ORDER BY time DESC LIMIT 5;"
```

### 5.4 Grafana 仪表盘

打开 `http://kiwi.maengyi.top:3001/d/factory-monitor`（需配 nginx）

---

## 常见问题速查

| 问题 | 排查 |
|------|------|
| STM32 烧录失败 | BOOT0=1？CH340 驱动装了？ |
| DHT22 读不到 | DATA 脚万用表量是否 3.3V |
| LoRa 收不到 | 天线接了没？两端频率一致（433.975MHz）？ |
| 网关 WiFi 连不上 | SSID/密码对不对？2.4G WiFi？ |
| 网关 MQTT 连不上 | 服务器 1883 端口开了没？防火墙？ |

---

## 下一步

完成以上步骤后对 Max 说："硬件调通了，拉服务端"
