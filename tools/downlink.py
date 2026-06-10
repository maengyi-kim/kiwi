#!/usr/bin/env python3
"""
Kiwi 下行控制面板 v2.0
UI 对齐模拟平台，设备从 DB 动态加载，MQTT 下发真实指令
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

mqtt_client = None


def get_db():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS)


def get_all_devices():
    """从 DB 加载所有设备及其最新状态"""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT d.device_id, d.device_name, d.sensor_types, d.last_seen,
                   COALESCE(EXTRACT(EPOCH FROM NOW()-d.last_seen), 99999) AS ago_s
            FROM devices d ORDER BY d.device_id
        """)
        rows = cur.fetchall()
        db.close()

        devices = []
        for row in rows:
            did, name, stypes_str, last_seen, ago_s = row

            # 查最新传感器值 → 从 sensor_data 推导类型
            states = {}
            try:
                db2 = get_db()
                cur2 = db2.cursor()
                cur2.execute("""
                    SELECT DISTINCT ON (sensor_type) sensor_type, value, time
                    FROM sensor_data WHERE device_id = %s
                    ORDER BY sensor_type, time DESC
                """, (did,))
                for sr in cur2.fetchall():
                    states[sr[0]] = sr[1]
                db2.close()
            except:
                pass

            stypes = sorted(states.keys())  # 从实际数据推导

            online = ago_s < 600  # 10分钟内活跃=在线

            devices.append({
                "id": did, "name": name,
                "sensor_types": stypes,
                "states": states,
                "online": online,
                "last_seen_ago": int(ago_s),
            })
        return devices
    except Exception as e:
        print(f"DB error: {e}")
        return []


def send_cmd(device_id, value):
    """通过 MQTT 下发真实指令"""
    if mqtt_client is None:
        return False
    try:
        payload = json.dumps({"value": value, "action": "on" if value else "off"})
        mqtt_client.publish(f"monitor/cmd/{device_id}", payload, qos=1)
        # 同时发 HTTP /ingest 让模拟节点也能响应
        import urllib.request
        ingest_payload = json.dumps({
            "device_id": device_id,
            "sensors": [{"type": "status", "value": value}],
            "timestamp": int(time.time()),
        }).encode()
        req = urllib.request.Request(
            "https://kiwi.maengyi.top/ingest",
            data=ingest_payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
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

    def _html(self):
        body = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._html()
        elif path == "/api/state":
            devices = get_all_devices()
            total = len(devices)
            online = sum(1 for d in devices if d["online"])
            return self._json({"ok": True, "devices": devices,
                               "total": total, "online": online})
        else:
            self._json({"error": "not found"}, 404)

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
            self._json({"error": "not found"}, 404)


# ═══════════════════════════════════════════════════════════
HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🥝 Kiwi 控制面板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;padding:12px 20px;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:18px;color:#58a6ff}
.stats{display:flex;gap:16px;padding:12px 20px;flex-wrap:wrap}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px}
.stat .label{font-size:11px;color:#8b949e;text-transform:uppercase}
.stat .value{font-size:22px;font-weight:700;color:#58a6ff}
.panel{margin:12px 20px;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
.panel-title{padding:10px 16px;background:#1c2129;font-size:14px;font-weight:600;border-bottom:1px solid #30363d}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #21262d}
th{color:#8b949e;font-weight:600;font-size:11px;text-transform:uppercase}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.on{background:#3fb950;box-shadow:0 0 6px #3fb950}
.status-dot.off{background:#484f58}
.btn{padding:5px 12px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:.15s}
.btn-green{background:#238636;color:#fff}
.btn-red{background:#da3633;color:#fff}
.btn-gray{background:#30363d;color:#8b949e}
.btn:active{transform:scale(.96)}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-temp{background:#b62324;color:#ffa198}
.tag-hum{background:#1f6feb;color:#a5d8ff}
.tag-water{background:#1b7c83;color:#a5f0f5}
.tag-switch{background:#9a6700;color:#f0c97b}
.tag-status{background:#6e40c9;color:#d2a8ff}
.refresh{text-align:center;padding:12px;font-size:11px;color:#484f58}
@media(max-width:768px){.stats{flex-direction:column}.stat{flex:1}}
</style>
</head>
<body>
<div class="header">
  <h1>🥝 Kiwi 控制面板</h1>
</div>
<div class="stats">
  <div class="stat"><div class="label">总设备</div><div class="value" id="total">-</div></div>
  <div class="stat"><div class="label">在线</div><div class="value" id="online">-</div></div>
</div>

<div class="panel">
  <div class="panel-title">📟 设备列表</div>
  <table><thead><tr>
    <th>ID</th><th>名称</th><th>类型</th><th>数值</th><th>在线</th><th>操作</th>
  </tr></thead><tbody id="device-table"></tbody></table>
</div>
<div class="refresh"><span>每 3 秒自动刷新</span></div>

<script>
const TYPE_TAG = {
  temperature:'tag-temp',humidity:'tag-hum',water_level:'tag-water',
  switch:'tag-switch',status:'tag-status'
};
const TYPE_ICON = {
  temperature:'🌡',humidity:'💧',water_level:'📏',switch:'🔘',status:'⚙️'
};
const SWITCHABLE = ['switch','status'];

async function api(path, opts={}) {
  const r = await fetch(path, opts);
  return r.json();
}

function cmdToggle(deviceId, curVal) {
  const next = curVal ? 0 : 1;
  api('api/cmd', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({device_id:deviceId, value:next})
  });
}

async function poll() {
  try {
    const d = await api('api/state');
    document.getElementById('total').textContent = d.total;
    document.getElementById('online').textContent = d.online;

    let html = '';
    for (const dev of d.devices) {
      const dot = dev.online
        ? '<span class="status-dot on"></span>在线'
        : '<span class="status-dot off"></span>' + dev.last_seen_ago + 's前';

      // 传感器值
      const vals = [];
      for (const st of (dev.sensor_types || [])) {
        const v = dev.states[st];
        vals.push(`${TYPE_ICON[st]||''}${st}: ${v!==undefined?v:'-'}`);
      }
      const valStr = vals.length ? vals.join(' ') : '-';

      // 开关按钮: 取第一个 switchable 类型的最新值
      let toggleBtn = '';
      for (const st of SWITCHABLE) {
        if ((dev.sensor_types||[]).includes(st) && dev.states[st]!==undefined) {
          const v = dev.states[st];
          const cls = v ? 'btn-green' : 'btn-red';
          const label = v ? 'ON' : 'OFF';
          toggleBtn = `<button class="btn ${cls}" onclick="cmdToggle(${dev.id},${v})">${label}</button>`;
          break;
        }
      }

      html += `<tr>
        <td>${dev.id}</td>
        <td>📟 ${dev.name}</td>
        <td>${(dev.sensor_types||[]).map(s=>`<span class="tag ${TYPE_TAG[s]||''}">${TYPE_ICON[s]||''}${s}</span>`).join(' ')}</td>
        <td>${valStr}</td>
        <td>${dot}</td>
        <td>${toggleBtn}</td>
      </tr>`;
    }
    document.getElementById('device-table').innerHTML = html || '<tr><td colspan="6" style="color:#484f58;text-align:center;padding:40px">暂无设备</td></tr>';
  } catch(e) {}
}

setInterval(poll, 3000);
poll();
</script>
</body>
</html>"""


def main():
    global mqtt_client

    # MQTT
    mqtt_client = mqtt.Client(client_id="kiwi-downlink", protocol=mqtt.MQTTv5,
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
    print("🥝 Kiwi 控制面板 v2.0")
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
