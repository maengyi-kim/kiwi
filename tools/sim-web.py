#!/usr/bin/env python3
"""
传感器模拟器 Web 控制台
在浏览器中控制模拟传感器发送数据，查看实时日志。
"""

import json
import random
import sys
import os
import time
import threading
import queue
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ─── MQTT ───
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# ─── 虚拟设备 ───
DEVICES = [
    # ===== 模拟量 =====
    {"id": 1, "name": "冷库1号温度", "sensors": ["temperature"],
     "temp_range": (-25, -18), "battery": 3.85},
    {"id": 2, "name": "冷库2号温度", "sensors": ["temperature"],
     "temp_range": (-24, -17), "battery": 3.72},
    {"id": 3, "name": "冷库3号温度", "sensors": ["temperature"],
     "temp_range": (-26, -19), "battery": 3.91},
    {"id": 4, "name": "冷库1号湿度", "sensors": ["humidity"],
     "humidity_range": (55, 75), "battery": 3.85},
    {"id": 5, "name": "冷库2号湿度", "sensors": ["humidity"],
     "humidity_range": (50, 70), "battery": 3.72},
    {"id": 6, "name": "冷库3号湿度", "sensors": ["humidity"],
     "humidity_range": (60, 80), "battery": 3.91},
    {"id": 10, "name": "水箱1号水位", "sensors": ["water_level"],
     "water_range": (600, 1500), "battery": 3.78},
    {"id": 11, "name": "水箱2号水位", "sensors": ["water_level"],
     "water_range": (400, 1200), "battery": 3.65},
    {"id": 20, "name": "车间温度", "sensors": ["temperature"],
     "temp_range": (15, 30), "battery": 3.95},
    {"id": 21, "name": "车间湿度", "sensors": ["humidity"],
     "humidity_range": (40, 65), "battery": 3.95},

    # ===== 开关量 / 状态量 =====
    {"id": 30, "name": "冷库1号门", "sensors": ["switch"],
     "switch_on_chance": 0.05, "battery": 3.80},
    {"id": 31, "name": "冷库2号门", "sensors": ["switch"],
     "switch_on_chance": 0.05, "battery": 3.75},
    {"id": 32, "name": "冷库3号门", "sensors": ["switch"],
     "switch_on_chance": 0.05, "battery": 3.82},
    {"id": 40, "name": "冷库1号压缩机", "sensors": ["status"],
     "status_on_chance": 0.90, "battery": 3.85},
    {"id": 41, "name": "冷库2号压缩机", "sensors": ["status"],
     "status_on_chance": 0.90, "battery": 3.78},
    {"id": 42, "name": "冷库3号压缩机", "sensors": ["status"],
     "status_on_chance": 0.90, "battery": 3.88},
    {"id": 50, "name": "水箱1号泵", "sensors": ["status"],
     "status_on_chance": 0.30, "battery": 3.70},
    {"id": 51, "name": "水箱2号泵", "sensors": ["status"],
     "status_on_chance": 0.30, "battery": 3.68},
]

# ─── 全局状态 ───
log_queue = queue.Queue()
sim_state = {"running": False, "interval": 10, "round": 0, "total": 0}
sim_thread = None


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    log_queue.put(line)
    # 只保留最近 200 条
    while log_queue.qsize() > 200:
        try:
            log_queue.get_nowait()
        except queue.Empty:
            break


def gen_sensor_data(device):
    sensors = []
    for stype in device["sensors"]:
        if stype == "temperature":
            tmin, tmax = device["temp_range"]
            sensors.append({"type": "temperature", "value": round(random.uniform(tmin, tmax), 1), "unit": "°C"})
        elif stype == "humidity":
            hmin, hmax = device["humidity_range"]
            sensors.append({"type": "humidity", "value": round(random.uniform(hmin, hmax), 1), "unit": "%"})
        elif stype == "water_level":
            wmin, wmax = device["water_range"]
            sensors.append({"type": "water_level", "value": round(random.uniform(wmin, wmax)), "unit": "mm"})
        elif stype == "door":
            # 门开关: 0=关闭, 1=打开 (偶尔开门)
            val = 1 if random.random() < device.get("door_open_chance", 0.05) else 0
            sensors.append({"type": "door", "value": val, "unit": ""})
        elif stype == "compressor":
            # 压缩机: 0=停机, 1=运行 (大部分时间运行)
            val = 0 if random.random() < device.get("compressor_off_chance", 0.1) else 1
            sensors.append({"type": "compressor", "value": val, "unit": ""})
        elif stype == "pump":
            # 水泵: 0=停机, 1=运行
            val = 1 if random.random() < device.get("pump_on_chance", 0.3) else 0
            sensors.append({"type": "pump", "value": val, "unit": ""})
        elif stype == "switch":
            # 通用开关量: 0=断开, 1=闭合
            val = 1 if random.random() < device.get("switch_on_chance", 0.05) else 0
            sensors.append({"type": "switch", "value": val, "unit": ""})
        elif stype == "status":
            # 通用状态量: 0=停机/关, 1=运行/开
            val = 1 if random.random() < device.get("status_on_chance", 0.5) else 0
            sensors.append({"type": "status", "value": val, "unit": ""})

    return {
        "device_id": device["id"],
        "dev_eui": f"DEADBEEF{device['id']:04X}",
        "sensors": sensors,
        "battery": round(device["battery"] + random.uniform(-0.05, 0.02), 2),
        "rssi": random.randint(-110, -60),
        "snr": round(random.uniform(-5, 12), 1),
        "frame_counter": random.randint(1, 255),
        "data_rate": random.randint(2, 5),
        "timestamp": int(time.time()),
    }


def publish_round(client):
    """发送一轮所有设备数据，返回发送条数"""
    count = 0
    for device in DEVICES:
        payload = gen_sensor_data(device)
        topic = f"monitor/{device['id']}/data"
        try:
            client.publish(topic, json.dumps(payload), qos=0)
        except Exception as e:
            log(f"❌ MQTT 发送失败: {e}")
            return count

        sensors_str = " | ".join(f"{s['type']}={s['value']}{s['unit']}" for s in payload["sensors"])
        log(f"📤 {device['name']:8s} → {sensors_str}  🔋{payload['battery']}V")
        count += 1

    # 网关心跳
    gw = {"gateway_id": "gw-001", "status": "online", "nodes_heard": len(DEVICES),
          "uptime": random.randint(3600, 86400), "timestamp": int(time.time())}
    try:
        client.publish("monitor/gateway/status", json.dumps(gw), qos=0)
    except Exception:
        pass

    return count


def sim_loop():
    """后台线程：循环发送"""
    import paho.mqtt.client as mqtt_client
    client = mqtt_client.Client(
        client_id="sim-web", protocol=mqtt_client.MQTTv5,
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
    )
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=10)
    except Exception as e:
        log(f"❌ 无法连接 MQTT: {e}")
        sim_state["running"] = False
        return

    log("🟢 模拟器已连接 MQTT，开始循环发送")

    while sim_state["running"]:
        sim_state["round"] += 1
        interval = sim_state["interval"]
        log(f"── 第 {sim_state['round']} 轮 (间隔 {interval}s) ──")
        n = publish_round(client)
        sim_state["total"] += n
        log(f"✅ 本轮发送 {n} 条设备数据 + 1 条网关心跳")

        # 分段等待，方便快速响应停止
        for _ in range(interval):
            if not sim_state["running"]:
                break
            time.sleep(1)

    client.disconnect()
    log("🔴 模拟器已停止")


def start_sim(interval=10):
    global sim_thread
    if sim_state["running"]:
        return False
    sim_state["running"] = True
    sim_state["interval"] = interval
    sim_state["round"] = 0
    sim_state["total"] = 0
    sim_thread = threading.Thread(target=sim_loop, daemon=True)
    sim_thread.start()
    return True


def stop_sim():
    sim_state["running"] = False
    return True


def run_once():
    import paho.mqtt.client as mqtt_client
    client = mqtt_client.Client(
        client_id="sim-once", protocol=mqtt_client.MQTTv5,
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
    )
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=10)
    except Exception as e:
        log(f"❌ 无法连接 MQTT: {e}")
        return 0

    log("📡 手动发送一轮...")
    n = publish_round(client)
    log(f"✅ 发送完成: {n} 条设备数据")
    client.disconnect()
    return n


# ─── HTTP Server ───
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>📡 传感器模拟器</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;padding:16px 20px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:12px}
.header h1{font-size:18px;color:#58a6ff}
.status{display:inline-block;padding:4px 12px;border-radius:12px;font-size:13px;font-weight:600}
.status.running{background:#1a7f4b;color:#fff}
.status.stopped{background:#30363d;color:#8b949e}
.controls{display:flex;gap:10px;padding:16px 20px;flex-wrap:wrap;align-items:center}
.btn{padding:10px 20px;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;transition:.2s}
.btn:active{transform:scale(.97)}
.btn-start{background:#238636;color:#fff}
.btn-start:hover{background:#2ea043}
.btn-once{background:#1f6feb;color:#fff}
.btn-once:hover{background:#388bfd}
.btn-stop{background:#da3633;color:#fff}
.btn-stop:hover{background:#f85149}
.btn-clear{background:#30363d;color:#8b949e}
.btn-clear:hover{background:#484f58}
.interval-wrap{display:flex;align-items:center;gap:8px;margin-left:auto}
.interval-wrap label{font-size:13px;color:#8b949e}
.interval-wrap input{width:60px;padding:8px;border:1px solid #30363d;border-radius:6px;background:#0d1117;color:#c9d1d9;font-size:14px;text-align:center}
.interval-wrap span{font-size:13px;color:#8b949e}
.stats{display:flex;gap:16px;padding:0 20px 12px;flex-wrap:wrap}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px}
.stat .label{font-size:11px;color:#8b949e;text-transform:uppercase}
.stat .value{font-size:22px;font-weight:700;color:#58a6ff}
.log-container{margin:0 20px 20px;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
.log-header{padding:10px 16px;background:#1c2129;border-bottom:1px solid #30363d;font-size:13px;font-weight:600}
.log-body{height:400px;overflow-y:auto;padding:8px 16px;font-family:'SF Mono',Monaco,Menlo,monospace;font-size:12px;line-height:1.7}
.log-body div{border-bottom:1px solid #1c2129;padding:2px 0}
.log-body div:last-child{border:none}
.empty{color:#484f58;text-align:center;padding:60px 0}
@media(max-width:600px){
  .controls{flex-direction:column;align-items:stretch}
  .interval-wrap{margin-left:0}
  .btn{padding:12px;font-size:16px}
  .log-body{height:300px}
}
</style>
</head>
<body>
<div class="header">
  <h1>📡 传感器模拟器</h1>
  <span id="status" class="status stopped">● 已停止</span>
</div>

<div class="controls">
  <button class="btn btn-start" onclick="start()">▶ 循环发送</button>
  <button class="btn btn-once" onclick="once()">⚡ 发送一轮</button>
  <button class="btn btn-stop" onclick="stop()">⏹ 停止</button>
  <button class="btn btn-clear" onclick="clearLog()">🗑 清屏</button>
  <div class="interval-wrap">
    <label>间隔</label>
    <input id="interval" type="number" value="10" min="1" max="3600">
    <span>秒</span>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="label">当前轮次</div><div class="value" id="round">0</div></div>
  <div class="stat"><div class="label">累计发送</div><div class="value" id="total">0</div></div>
  <div class="stat"><div class="label">模拟设备</div><div class="value">18</div></div>
</div>

<div class="log-container">
  <div class="log-header">📋 实时日志</div>
  <div class="log-body" id="log">
    <div class="empty">等待操作...</div>
  </div>
</div>

<script>
const logEl = document.getElementById('log');
let lastLogLen = 0;

async function api(path) {
  const r = await fetch(path);
  return r.json();
}

async function start() {
  const intv = document.getElementById('interval').value;
  const d = await api('/start?interval=' + intv);
  if(d.ok) document.getElementById('status').className = 'status running';
  document.getElementById('status').textContent = '● 运行中';
}

async function stop() {
  const d = await api('/stop');
  if(d.ok) document.getElementById('status').className = 'status stopped';
  document.getElementById('status').textContent = '● 已停止';
}

async function once() {
  await api('/once');
}

async function clearLog() {
  await api('/clear');
  logEl.innerHTML = '<div class="empty">已清屏</div>';
  lastLogLen = 0;
}

async function poll() {
  try {
    const d = await api('/state');
    document.getElementById('status').textContent = d.running ? '● 运行中' : '● 已停止';
    document.getElementById('status').className = 'status ' + (d.running ? 'running' : 'stopped');
    document.getElementById('round').textContent = d.round;
    document.getElementById('total').textContent = d.total;
  } catch(e) {}

  try {
    const r = await fetch('/logs?since=' + lastLogLen);
    const lines = await r.json();
    if(lines.length > 0) {
      if(logEl.querySelector('.empty')) logEl.innerHTML = '';
      for(const l of lines) {
        const div = document.createElement('div');
        div.textContent = l;
        logEl.appendChild(div);
      }
      logEl.scrollTop = logEl.scrollHeight;
      lastLogLen += lines.length;
    }
  } catch(e) {}
}

setInterval(poll, 1500);
poll();
</script>
</body>
</html>"""

# ─── 日志存储（内存） ───
log_store = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默 HTTP 日志

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content, code=200):
        body = content.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global log_store
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)

        if path == "/" or path == "/index.html":
            return self._html(HTML)

        elif path == "/start":
            interval = int(params.get("interval", [10])[0])
            ok = start_sim(interval)
            return self._json({"ok": ok, "running": sim_state["running"]})

        elif path == "/stop":
            ok = stop_sim()
            return self._json({"ok": ok, "running": sim_state["running"]})

        elif path == "/once":
            n = run_once()
            sim_state["total"] += n
            return self._json({"ok": True, "count": n})

        elif path == "/clear":
            log_store.clear()
            while not log_queue.empty():
                try: log_queue.get_nowait()
                except queue.Empty: break
            return self._json({"ok": True})

        elif path == "/state":
            return self._json({
                "running": sim_state["running"],
                "round": sim_state["round"],
                "total": sim_state["total"],
                "interval": sim_state["interval"],
            })

        elif path == "/logs":
            # 消费队列追加到 store
            while not log_queue.empty():
                try:
                    log_store.append(log_queue.get_nowait())
                except queue.Empty:
                    break
            since = int(params.get("since", [0])[0])
            return self._json(log_store[since:])

        else:
            self.send_response(404)
            self.end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    server = HTTPServer(("0.0.0.0", port), Handler)
    log("=" * 40)
    log(f"📡 传感器模拟器 Web 控制台")
    log(f"   本地访问: http://localhost:{port}")
    log(f"   外部访问: http://47.80.20.236:{port}")
    log("=" * 40)
    print(f"\n📡 传感器模拟器已启动 → http://localhost:{port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("⏹ 服务器关闭")
        stop_sim()
        server.shutdown()


if __name__ == "__main__":
    main()
