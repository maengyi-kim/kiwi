# Kiwi 本地调试操作手册

厂区环境监控系统本地开发/调试全流程。适用场景：在自己机器上跑通全链路后调试。

---

## 1. 架构速览

```
传感器模拟器 (sim-web.py:8081)
        │
        ▼ MQTT (monitor/+/data)
Mosquitto (Podman :1883)
        │
        ▼
Python Ingest (ingest/app.py) ──► TimescaleDB (Podman :5433)
                                        │
                                        ▼
                                   Grafana (Podman :3001)
```

物理硬件（LoRa 节点 + 网关）未接入时，用模拟器代替。

---

## 2. 启动（从头拉起）

### 2.1 启动 Podman 容器

三个容器，必须全部启动。顺序无所谓，但 Ingest 服务依赖 DB 和 MQTT。

```bash
# TimescaleDB（已有历史数据，-e 密码会被已有数据覆盖，不能改密码）
podman run -d --name monitor-db \
  -e POSTGRES_PASSWORD=monitor_sensor_2026 \
  -e POSTGRES_DB=monitor \
  -p 5433:5432 \
  -v ~/kiwi/pgdata:/var/lib/postgresql/data:Z \
  docker.io/timescale/timescaledb:latest-pg16

# Mosquitto MQTT
podman run -d --name monitor-mqtt \
  -p 1883:1883 \
  -v ~/kiwi/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:Z \
  -v ~/kiwi/mosquitto/data:/mosquitto/data:Z \
  -v ~/kiwi/mosquitto/log:/mosquitto/log:Z \
  docker.io/library/eclipse-mosquitto:2

# Grafana
podman run -d --name monitor-grafana \
  -p 3001:3000 \
  -v ~/kiwi/grafana-fresh:/var/lib/grafana:Z \
  -v ~/kiwi/grafana-config/custom.ini:/etc/grafana/grafana.ini:Z \
  -e GF_AUTH_ANONYMOUS_ENABLED=true \
  -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
  docker.io/grafana/grafana:latest
```

### 2.2 验证容器

```bash
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 预期输出：
# monitor-db       Up xx seconds   0.0.0.0:5433->5432/tcp
# monitor-mqtt     Up xx seconds   0.0.0.0:1883->1883/tcp
# monitor-grafana  Up xx seconds   0.0.0.0:3001->3000/tcp
```

### 2.3 启动 Ingest 服务

```bash
cd ~/kiwi && source venv/bin/activate && python ingest/app.py
```

启动后会打印 MQTT/DB 连接信息，然后阻塞等待消息。Ctrl+C 停止。

生产环境用 systemd --user 保活（见第 7 节）。

---

## 3. 验证链路

### 3.1 单条 MQTT 测试消息

```bash
podman exec monitor-mqtt mosquitto_pub -t "monitor/1/data" -m \
  '{"device_id":1,"sensors":[{"type":"temperature","value":-22.5,"unit":"°C"}],
    "battery":3.85,"rssi":-75,"snr":8.0,"frame_counter":1,"data_rate":3,
    "timestamp":'"$(date +%s)"'}'
```

### 3.2 查库验证入库

```bash
podman exec monitor-db psql -U postgres -d monitor \
  -c "SELECT time, device_id, sensor_type, value, unit
      FROM sensor_data ORDER BY time DESC LIMIT 5;"
```

能看到刚发的数据就是通的。

### 3.3 模拟器批量测试

```bash
cd ~/kiwi && source venv/bin/activate && python -c "
import json, time, random
import paho.mqtt.client as mqtt

DEVICES = [
    {'id': 1, 'name': '冷库1温度', 'temp_range': (-25, -18)},
    {'id': 4, 'name': '冷库1湿度', 'humidity_range': (55, 75)},
    {'id': 10, 'name': '水箱1水位', 'water_range': (600, 1500)},
]

client = mqtt.Client(client_id='test', protocol=mqtt.MQTTv5,
                      callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.connect('localhost', 1883)

for dev in DEVICES:
    if 'temp_range' in dev:
        s = {'type':'temperature','value':round(random.uniform(*dev['temp_range']),1),'unit':'°C'}
    elif 'humidity_range' in dev:
        s = {'type':'humidity','value':round(random.uniform(*dev['humidity_range']),1),'unit':'%'}
    else:
        s = {'type':'water_level','value':round(random.uniform(*dev['water_range'])),'unit':'mm'}
    payload = {'device_id':dev['id'], 'dev_eui':f'DEAD{dev[\"id\"]:04X}',
               'sensors':[s], 'battery':round(random.uniform(3.6,3.9),2),
               'rssi':-75, 'snr':8.0, 'frame_counter':1, 'data_rate':3,
               'timestamp':int(time.time())}
    client.publish(f'monitor/{dev[\"id\"]}/data', json.dumps(payload))
    print(f'  {dev[\"name\"]} -> {s}')

client.disconnect()
print('Done')
"
```

---

## 4. 模拟器（Web 控制台）

浏览器操作，生成持续模拟数据流。

```bash
cd ~/kiwi && source venv/bin/activate && python tools/sim-web.py 8081
```

打开 http://localhost:8081

功能：
- **循环发送** — 每隔 N 秒发送一轮 18 个设备的模拟数据
- **发送一轮** — 手动触发一轮
- 实时日志 + 统计

---

## 5. 控制面板（下行指令测试）

```bash
cd ~/kiwi && source venv/bin/activate && python tools/downlink.py 8082
```

打开 http://localhost:8082

功能：
- 开关控制 8 个设备（库门、压缩机、水泵）
- 点击按钮 → MQTT 下发 monitor/cmd/{id} → 模拟设备回传状态

---

## 6. Grafana 仪表盘

```
http://localhost:3001/d/factory-monitor
```

匿名访问，无需登录。

如果仪表盘不存在：手动导入或从 grafana-fresh/ 恢复。

---

## 7. 停止 & 重启

### 7.1 停止全部

```bash
# 停 Ingest（Ctrl+C 或 kill）
pkill -f "ingest/app.py"

# 停容器
podman stop monitor-db monitor-mqtt monitor-grafana
```

### 7.2 重启全部

```bash
# 重启容器
podman start monitor-db monitor-mqtt monitor-grafana

# 等 DB 就绪（约 5 秒）
sleep 5

# 重新启动 Ingest
cd ~/kiwi && source venv/bin/activate && python ingest/app.py &
```

---

## 8. 调试技巧

### 8.1 查看 Ingest 实时日志

Ingest 的 Python logging 有缓冲。如果急着看：

```bash
# 方法1：开新终端看 journal
journalctl --user -f -n 50

# 方法2：PYTHONUNBUFFERED 运行
cd ~/kiwi && source venv/bin/activate && PYTHONUNBUFFERED=1 python ingest/app.py
```

### 8.2 MQTT 消息监听

```bash
# 监听所有 monitor 主题
podman exec monitor-mqtt mosquitto_sub -t "monitor/#" -v
```

### 8.3 数据库直连

```bash
podman exec -it monitor-db psql -U postgres -d monitor
```

常用 SQL：

```sql
-- 最近数据
SELECT time, device_name, sensor_type, value, unit
FROM sensor_data ORDER BY time DESC LIMIT 20;

-- 按设备统计
SELECT device_id, device_name, sensor_type, COUNT(*), MAX(time)
FROM sensor_data GROUP BY device_id, device_name, sensor_type
ORDER BY device_id;

-- 告警记录
SELECT * FROM alarms ORDER BY created_at DESC LIMIT 10;

-- 设备在线状态
SELECT device_id, device_name, last_seen, is_active
FROM devices WHERE is_active = true;
```

### 8.4 检查容器日志

```bash
podman logs monitor-db     --tail 20
podman logs monitor-mqtt   --tail 20
podman logs monitor-grafana --tail 20
```

### 8.5 容器挂了怎么办

```bash
# 诊断
podman ps -a                         # 看退出状态
podman logs monitor-db --tail 50     # 看日志

# 如果数据目录权限坏了
sudo chown -R 165605:165605 ~/kiwi/pgdata   # TimescaleDB UID

# 强制重建（⚠ 会丢数据）
podman rm -f monitor-db
# 然后重新 2.1 中的 run 命令
```

---

## 9. 密码 & 端口速查

| 项目 | 值 |
|------|-----|
| DB 密码 | `***` |
| DB 端口 | 5433 |
| MQTT 端口 | 1883 |
| Grafana 端口 | 3001 |
| 模拟器端口 | 8081 |
| 控制面板端口 | 8082 |
| MQTT 主题 | `monitor/{device_id}/data` |
| 下行主题 | `monitor/cmd/{device_id}` |
| 网关心跳 | `monitor/gateway/status` |

---

## 10. systemd 保活（生产用）

创建 `~/.config/systemd/user/monitor-ingest.service`：

```ini
[Unit]
Description=Kiwi Monitor Ingest Service
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/kiwi
ExecStart=%h/kiwi/venv/bin/python ingest/app.py
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

然后：

```bash
systemctl --user daemon-reload
systemctl --user enable --now monitor-ingest
systemctl --user status monitor-ingest
```

容器也可以用 systemd 管理，但直接 `podman start` 也能持久。

---

## 11. 故障排查 Checklist

- [ ] `podman ps` — 三个容器都在 Up？
- [ ] `ps aux | grep ingest` — Ingest 进程在？
- [ ] `podman exec monitor-mqtt mosquitto_pub ...` — MQTT 能发？
- [ ] `podman exec monitor-db psql ... -c "SELECT 1"` — DB 能连？
- [ ] 发测试消息后 `SELECT * FROM sensor_data ORDER BY time DESC LIMIT 1` — 入库了？
- [ ] `curl -s http://localhost:3001/api/health` — Grafana 返回 200？
- [ ] 检查 Grafana 数据源配置是否正确连到 TimescaleDB

---

更新日期：2026-06-07
