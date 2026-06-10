#!/usr/bin/env python3
"""
Kiwi 下行控制 + Web 控制面板
MQTT 指令收发 + HTTP 控制页面
"""
import json
import time
import sys
import threading
import psycopg2
import paho.mqtt.client as mqtt
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

MQTT_BROKER = "localhost"
MQTT_PORT = 1884
CMD_TOPIC = "monitor/cmd/+"

DB_HOST = "localhost"
DB_PORT = 5433
DB_NAME = "monitor"
DB_USER = "postgres"
DB_PASS = "monitor_sensor_2026"

# 可控设备列表
DEVICES = [
    {"id": 30, "name": "冷库1号门", "group": "🚪 库门"},
    {"id": 31, "name": "冷库2号门", "group": "🚪 库门"},
    {"id": 32, "name": "冷库3号门", "group": "🚪 库门"},
    {"id": 40, "name": "冷库1号压缩机", "group": "⚙️ 压缩机"},
    {"id": 41, "name": "冷库2号压缩机", "group": "⚙️ 压缩机"},
    {"id": 42, "name": "冷库3号压缩机", "group": "⚙️ 压缩机"},
    {"id": 50, "name": "水箱1号泵", "group": "💧 水泵"},
    {"id": 51, "name": "水箱2号泵", "group": "💧 水泵"},
]

mqtt_client = None


def get_db():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def get_device_state(device_id):
    """从 DB 查询设备最新状态"""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT value FROM sensor_data
            WHERE device_id = %s AND sensor_type IN ('status','switch')
            ORDER BY time DESC LIMIT 1
        """, (device_id,))
        row = cur.fetchone()
        db.close()
        return int(row[0]) if row else 0
    except:
        return 0


def send_cmd(device_id, value):
    """通过 MQTT 下发指令"""
    if mqtt_client is None:
        return False
    try:
        payload = json.dumps({"value": value, "action": "on" if value else "off"})
        topic = f"monitor/cmd/{device_id}"
        mqtt_client.publish(topic, payload, qos=1)
        return True
    except Exception as e:
        print(f"下发失败: {e}")
        return False


# ─── MQTT ───
def on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe(CMD_TOPIC, qos=1)


def on_message(client, userdata, msg):
    try:
        device_id = int(msg.topic.split("/")[-1])
        payload = json.loads(msg.payload.decode())
        value = payload.get("value")
        if value is None:
            return
        print(f"[下行] 设备 {device_id} ← {value}")
        sensor_payload = {
            "device_id": device_id,
            "dev_eui": f"DOWNLINK{device_id:04X}",
            "sensors": [{"type": "status" if device_id >= 40 else "switch", "value": value, "unit": ""}],
            "battery": 3.75, "rssi": -75, "snr": 8.0,
            "frame_counter": int(time.time()) % 256, "data_rate": 3,
            "timestamp": int(time.time()),
        }
        client.publish(f"monitor/{device_id}/data", json.dumps(sensor_payload), qos=1)
        print(f"[下行] 设备 {device_id} → 回传: {value}")
    except Exception as e:
        print(f"[下行] 错误: {e}")


# ─── HTTP API ───
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
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
        path = urlparse(self.path).path
        if path == "/":
            return self._html(HTML)
        elif path == "/api/state":
            states = {}
            for dev in DEVICES:
                val = get_device_state(dev["id"])
                states[str(dev["id"])] = val
            return self._json({"ok": True, "devices": DEVICES, "states": states})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/cmd":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            device_id = body.get("device_id")
            value = body.get("value")
            ok = send_cmd(device_id, value)
            return self._json({"ok": ok})
        else:
            self.send_response(404)
            self.end_headers()


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🥝 Kiwi 控制面板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;padding:20px}
h1{font-size:20px;color:#58a6ff;text-align:center;margin-bottom:4px}
.sub{text-align:center;color:#8b949e;font-size:13px;margin-bottom:20px}
.group{margin-bottom:16px}
.group-title{font-size:15px;font-weight:600;color:#58a6ff;padding:6px 0;border-bottom:1px solid #30363d;margin-bottom:8px}
.device-row{display:flex;align-items:center;justify-content:space-between;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 16px;margin-bottom:6px}
.device-name{font-size:15px;font-weight:500}
.toggle{position:relative;width:56px;height:30px;border-radius:15px;border:none;cursor:pointer;transition:.3s;outline:none}
.toggle.off{background:#30363d}
.toggle.on{background:#238636}
.toggle::after{content:'';position:absolute;top:3px;left:3px;width:24px;height:24px;border-radius:50%;background:#fff;transition:.3s}
.toggle.on::after{left:29px}
.status-text{font-size:12px;min-width:40px;text-align:right}
.status-text.on{color:#3fb950}
.status-text.off{color:#8b949e}
.refresh{text-align:center;margin-top:16px}
.refresh span{font-size:12px;color:#484f58}
</style>
</head>
<body>
<h1>🥝 Kiwi 控制面板</h1>
<div class="sub">设备开关控制</div>
<div id="groups"></div>
<div class="refresh"><span>状态自动刷新</span></div>

<script>
const GROUPS = {};

async function load() {
  const r = await fetch('api/state');
  const d = await r.json();
  const groups = {};
  for (const dev of d.devices) {
    if (!groups[dev.group]) groups[dev.group] = [];
    groups[dev.group].push(dev);
  }
  const html = Object.entries(groups).map(([g, devs]) => `
    <div class="group">
      <div class="group-title">${g}</div>
      ${devs.map(dev => {
        const state = d.states[dev.id] || 0;
        const cls = state ? 'on' : 'off';
        const label = g.includes('门') ? (state ? '⚠开' : '关') : (state ? '运行' : '停机');
        return `<div class="device-row">
          <span class="device-name">${dev.name}</span>
          <span class="status-text ${cls}">${label}</span>
          <button class="toggle ${cls}" data-id="${dev.id}" data-state="${state}" onclick="toggle(this)"></button>
        </div>`;
      }).join('')}
    </div>
  `).join('');
  document.getElementById('groups').innerHTML = html;
}

async function toggle(btn) {
  const id = parseInt(btn.dataset.id);
  const cur = parseInt(btn.dataset.state);
  const next = cur ? 0 : 1;
  btn.disabled = true;
  await fetch('api/cmd', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({device_id: id, value: next})
  });
  setTimeout(load, 800);
}

load();
setInterval(load, 5000);
</script>
</body>
</html>"""


def main():
    global mqtt_client

    # MQTT
    mqtt_client = mqtt.Client(client_id="downlink-sim", protocol=mqtt.MQTTv5,
                              callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    mqtt_thread = threading.Thread(target=mqtt_client.loop_forever, daemon=True)
    mqtt_thread.start()

    # HTTP
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8082
    server = HTTPServer(("0.0.0.0", port), Handler)
    print("=" * 50)
    print("🥝 Kiwi 控制面板")
    print(f"   http://localhost:{port}")
    print(f"   MQTT: {MQTT_BROKER}:{MQTT_PORT}")
    print("=" * 50)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
