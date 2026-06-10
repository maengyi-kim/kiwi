#!/usr/bin/env python3
"""
Kiwi 模拟平台 — 管理虚拟 Gateway 和 Node
真实链路: 虚拟Node → 虚拟Gateway → HTTP POST /ingest → 真实服务器
"""
import json, random, sys, time, threading, queue, uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ─── 配置 ───
INGEST_URL = "https://kiwi.maengyi.top/ingest"

# ─── 传感器工厂 ───
SENSOR_PROFILES = {
    "temperature":  {"sensors": [{"type": "temperature", "unit": "°C"}],
                     "range": (-25, -18), "battery": 3.85},
    "humidity":     {"sensors": [{"type": "humidity", "unit": "%"}],
                     "range": (50, 80), "battery": 3.75},
    "water_level":  {"sensors": [{"type": "water_level", "unit": "mm"}],
                     "range": (400, 1500), "battery": 3.70},
    "switch":       {"sensors": [{"type": "switch", "unit": ""}],
                     "range": (0, 1), "battery": 3.80, "int_output": True},
    "status":       {"sensors": [{"type": "status", "unit": ""}],
                     "range": (0, 1), "battery": 3.85, "int_output": True},
    "temp_humidity": {"sensors": [
                         {"type": "temperature", "unit": "°C"},
                         {"type": "humidity", "unit": "%"}],
                      "temp_range": (-25, -18), "hum_range": (50, 80), "battery": 3.82},
}

# ─── 全局状态 ───
gateways = {}   # {gid: Gateway}
nodes = {}      # {nid: Node}
log_queue = queue.Queue()
next_gw_id = 1
next_node_id = 1

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    log_queue.put(f"[{ts}] {msg}")
    while log_queue.qsize() > 500:
        try: log_queue.get_nowait()
        except queue.Empty: break

# ═══════════════════════════════════════════════════════════
# Gateway
# ═══════════════════════════════════════════════════════════
class Gateway:
    def __init__(self, gid, name):
        self.gid = gid
        self.name = name
        self.running = False
        self.thread = None
        self.inbox = queue.Queue()
        self.pkt_count = 0
        self.nodes_heard = set()

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        log(f"🟢 Gateway [{self.gid}] {self.name} started")

    def stop(self):
        self.running = False
        log(f"🔴 Gateway [{self.gid}] {self.name} stopped")

    def feed(self, payload):
        """接收 Node 数据"""
        if self.running:
            self.inbox.put(payload)

    def _loop(self):
        heartbeat_at = time.time() + 60
        while self.running:
            # 处理队列
            drained = 0
            while not self.inbox.empty():
                try:
                    payload = self.inbox.get_nowait()
                    self._post(payload)
                    self.pkt_count += 1
                    self.nodes_heard.add(payload.get("device_id"))
                    drained += 1
                except queue.Empty:
                    break
            if drained:
                log(f"📡 Gateway [{self.gid}] sent {drained} packets")

            # 网关心跳 (60s)
            if time.time() >= heartbeat_at:
                heartbeat_at = time.time() + 60
                gw_payload = {
                    "gateway_id": f"sim-gw-{self.gid:03d}",
                    "nodes": len(self.nodes_heard),
                    "pkts": self.pkt_count,
                }
                self._post(gw_payload)

            time.sleep(0.5)

    def _post(self, payload):
        try:
            import urllib.request
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                INGEST_URL, data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            log(f"❌ Gateway [{self.gid}] POST failed: {e}")

    def to_dict(self):
        return {
            "id": self.gid, "name": self.name,
            "running": self.running,
            "pkts": self.pkt_count,
            "nodes": len(self.nodes_heard),
        }

# ═══════════════════════════════════════════════════════════
# Node
# ═══════════════════════════════════════════════════════════
class Node:
    def __init__(self, nid, name, sensor_type, gateway_id, interval=10):
        self.nid = nid
        self.name = name
        self.sensor_type = sensor_type
        self.gateway_id = gateway_id
        self.interval = interval
        self.running = False
        self.thread = None
        self.count = 0
        self.battery = SENSOR_PROFILES[sensor_type].get("battery", 3.75)

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        log(f"🟢 Node [{self.nid}] {self.name} → GW [{self.gateway_id}]")

    def stop(self):
        self.running = False
        log(f"🔴 Node [{self.nid}] {self.name} stopped")

    def _loop(self):
        while self.running:
            payload = self._gen_payload()
            gw = gateways.get(self.gateway_id)
            if gw and gw.running:
                gw.feed(payload)
            time.sleep(self.interval)

    def _gen_payload(self):
        profile = SENSOR_PROFILES[self.sensor_type]
        sensors = []
        self.count += 1
        self.battery = round(self.battery + random.uniform(-0.02, 0.01), 2)
        self.battery = max(2.5, min(4.2, self.battery))

        if self.sensor_type == "temp_humidity":
            t = round(random.uniform(*profile["temp_range"]), 1)
            h = round(random.uniform(*profile["hum_range"]), 1)
            sensors = [
                {"type": "temperature", "value": t, "unit": "°C"},
                {"type": "humidity", "value": h, "unit": "%"},
            ]
        elif profile.get("int_output"):
            val = random.randint(*profile["range"])
            sensors = [{"type": self.sensor_type, "value": val}]
        else:
            val = round(random.uniform(*profile["range"]), 1)
            sensors = [{"type": self.sensor_type, "value": val,
                        "unit": profile["sensors"][0].get("unit", "")}]

        return {
            "device_id": self.nid,
            "dev_eui": f"SIMDEAD{self.nid:04X}",
            "sensors": sensors,
            "battery": self.battery,
            "rssi": random.randint(-90, -50),
            "snr": round(random.uniform(2, 15), 1),
            "frame_counter": self.count % 256,
            "data_rate": random.randint(2, 5),
            "timestamp": int(time.time()),
        }

    def to_dict(self):
        return {
            "id": self.nid, "name": self.name,
            "sensor_type": self.sensor_type,
            "gateway_id": self.gateway_id,
            "interval": self.interval,
            "running": self.running,
            "count": self.count,
            "battery": self.battery,
        }

# ═══════════════════════════════════════════════════════════
# HTTP API
# ═══════════════════════════════════════════════════════════
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        global log_queue
        path = urlparse(self.path).path

        if path == "/":
            return self._html()

        elif path == "/api/state":
            return self._json({
                "gateways": [g.to_dict() for g in gateways.values()],
                "nodes": [n.to_dict() for n in nodes.values()],
                "sensor_types": list(SENSOR_PROFILES.keys()),
            })

        elif path == "/api/logs":
            since = 0
            try:
                qs = urlparse(self.path).query
                if qs:
                    since = int(qs.split("=")[1])
            except: pass
            lines = []
            # drain queue
            while not log_queue.empty():
                try: lines.append(log_queue.get_nowait())
                except queue.Empty: break
            return self._json(lines[since:])

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        global next_gw_id, next_node_id
        path = urlparse(self.path).path
        body = self._read_body()

        # ─── Gateway ───
        if path == "/api/gateway/create":
            gid = next_gw_id; next_gw_id += 1
            name = body.get("name", f"Gateway-{gid}")
            gateways[gid] = Gateway(gid, name)
            log(f"➕ Gateway [{gid}] {name} created")
            return self._json(gateways[gid].to_dict())

        elif path.startswith("/api/gateway/") and path.endswith("/start"):
            gid = int(path.split("/")[3])
            if gid in gateways:
                gateways[gid].start()
                return self._json(gateways[gid].to_dict())

        elif path.startswith("/api/gateway/") and path.endswith("/stop"):
            gid = int(path.split("/")[3])
            if gid in gateways:
                gateways[gid].stop()
                return self._json(gateways[gid].to_dict())

        elif path.startswith("/api/gateway/") and "/delete" in path:
            gid = int(path.split("/")[3])
            if gid in gateways:
                gateways[gid].stop()
                del gateways[gid]
                log(f"🗑 Gateway [{gid}] deleted")
                return self._json({"ok": True})

        elif path.startswith("/api/gateway/") and path.endswith("/update"):
            gid = int(path.split("/")[3])
            if gid in gateways:
                gw = gateways[gid]
                if "name" in body:
                    gw.name = body["name"]
                log(f"✏ Gateway [{gid}] updated")
                return self._json(gw.to_dict())

        # ─── Node ───
        elif path == "/api/node/create":
            nid = next_node_id; next_node_id += 1
            name = body.get("name", f"Node-{nid}")
            stype = body.get("sensor_type", "temperature")
            gid = body.get("gateway_id", 1)
            interval = body.get("interval", 10)
            if stype not in SENSOR_PROFILES:
                return self._json({"error": f"unknown type: {stype}"}, 400)
            if gid not in gateways:
                return self._json({"error": f"gateway {gid} not found"}, 400)
            nodes[nid] = Node(nid, name, stype, gid, interval)
            log(f"➕ Node [{nid}] {name} ({stype}) → GW [{gid}]")
            return self._json(nodes[nid].to_dict())

        elif path.startswith("/api/node/") and path.endswith("/start"):
            nid = int(path.split("/")[3])
            if nid in nodes:
                nodes[nid].start()
                return self._json(nodes[nid].to_dict())

        elif path.startswith("/api/node/") and path.endswith("/stop"):
            nid = int(path.split("/")[3])
            if nid in nodes:
                nodes[nid].stop()
                return self._json(nodes[nid].to_dict())

        elif path.startswith("/api/node/") and "/delete" in path:
            nid = int(path.split("/")[3])
            if nid in nodes:
                nodes[nid].stop()
                del nodes[nid]
                log(f"🗑 Node [{nid}] deleted")
                return self._json({"ok": True})

        elif path.startswith("/api/node/") and path.endswith("/update"):
            nid = int(path.split("/")[3])
            if nid in nodes:
                node = nodes[nid]
                was_running = node.running
                if was_running: node.stop()
                if "name" in body:
                    node.name = body["name"]
                if "interval" in body:
                    node.interval = max(1, int(body["interval"]))
                if "gateway_id" in body:
                    new_gid = int(body["gateway_id"])
                    if new_gid in gateways:
                        node.gateway_id = new_gid
                if "sensor_type" in body:
                    st = body["sensor_type"]
                    if st in SENSOR_PROFILES:
                        node.sensor_type = st
                        node.battery = SENSOR_PROFILES[st].get("battery", 3.75)
                if was_running: node.start()
                log(f"✏ Node [{nid}] updated")
                return self._json(node.to_dict())

        # ─── 一键预设 ───
        elif path == "/api/preset":
            preset = body.get("preset", "small")
            created = _create_preset(preset)
            return self._json({"ok": True, "created": created})

        else:
            self._json({"error": "not found"}, 404)


def _create_preset(preset):
    global next_gw_id, next_node_id
    created = {"gateways": 0, "nodes": 0}

    if preset == "small":
        # 1 gateway + 5 nodes
        gid = next_gw_id; next_gw_id += 1
        gateways[gid] = Gateway(gid, "厂区网关")
        gateways[gid].start()
        created["gateways"] += 1

        specs = [
            ("冷库温度", "temperature", 15),
            ("冷库湿度", "humidity", 15),
            ("水箱水位", "water_level", 20),
            ("车间温度", "temperature", 20),
            ("车间湿度", "humidity", 20),
        ]
        for name, stype, iv in specs:
            nid = next_node_id; next_node_id += 1
            nodes[nid] = Node(nid, name, stype, gid, iv)
            nodes[nid].start()
            created["nodes"] += 1

    elif preset == "full":
        # 2 gateways + 18 nodes (原 sim-web 的规模)
        gid1 = next_gw_id; next_gw_id += 1
        gateways[gid1] = Gateway(gid1, "冷库区网关")
        gateways[gid1].start()
        created["gateways"] += 1

        gid2 = next_gw_id; next_gw_id += 1
        gateways[gid2] = Gateway(gid2, "车间区网关")
        gateways[gid2].start()
        created["gateways"] += 1

        # 冷库区
        for name, stype in [
            ("冷库1号温度", "temperature"), ("冷库2号温度", "temperature"),
            ("冷库3号温度", "temperature"),
            ("冷库1号湿度", "humidity"), ("冷库2号湿度", "humidity"),
            ("冷库3号湿度", "humidity"),
            ("水箱1号水位", "water_level"), ("水箱2号水位", "water_level"),
            ("冷库1号门", "switch"), ("冷库2号门", "switch"),
            ("冷库3号门", "switch"),
            ("冷库1号压缩机", "status"), ("冷库2号压缩机", "status"),
            ("冷库3号压缩机", "status"),
        ]:
            nid = next_node_id; next_node_id += 1
            nodes[nid] = Node(nid, name, stype, gid1, random.randint(10, 20))
            nodes[nid].start()
            created["nodes"] += 1

        # 车间区
        for name, stype in [
            ("车间温度", "temperature"), ("车间湿度", "humidity"),
            ("水箱1号泵", "status"), ("水箱2号泵", "status"),
        ]:
            nid = next_node_id; next_node_id += 1
            nodes[nid] = Node(nid, name, stype, gid2, random.randint(15, 25))
            nodes[nid].start()
            created["nodes"] += 1

    log(f"🎬 Preset '{preset}': {created['gateways']}GW + {created['nodes']}Nodes")
    return created


# ═══════════════════════════════════════════════════════════
# Web UI
# ═══════════════════════════════════════════════════════════
HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🥝 Kiwi 模拟平台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;padding:12px 20px;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:18px;color:#58a6ff}
.header .presets{display:flex;gap:6px}
.panel{margin:12px 20px;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
.panel-title{padding:10px 16px;background:#1c2129;font-size:14px;font-weight:600;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between}
.btn{padding:6px 14px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:.15s}
.btn:active{transform:scale(.96)}
.btn-green{background:#238636;color:#fff}
.btn-green:hover{background:#2ea043}
.btn-blue{background:#1f6feb;color:#fff}
.btn-red{background:#da3633;color:#fff}
.btn-gray{background:#30363d;color:#8b949e}
.btn-gray:hover{background:#484f58}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #21262d}
th{color:#8b949e;font-weight:600;font-size:11px;text-transform:uppercase}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.on{background:#3fb950;box-shadow:0 0 6px #3fb950}
.status-dot.off{background:#484f58}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.tag-temp{background:#b62324;color:#ffa198}
.tag-hum{background:#1f6feb;color:#a5d8ff}
.tag-water{background:#1b7c83;color:#a5f0f5}
.tag-switch{background:#9a6700;color:#f0c97b}
.tag-status{background:#6e40c9;color:#d2a8ff}
.tag-th{background:#8250df;color:#d2a8ff}
.form-row{display:flex;gap:10px;padding:10px 16px;align-items:flex-end;flex-wrap:wrap}
.form-row label{font-size:11px;color:#8b949e;display:block;margin-bottom:3px}
.form-row select,.form-row input{padding:6px 10px;border:1px solid #30363d;border-radius:6px;background:#0d1117;color:#c9d1d9;font-size:13px}
.form-row select{min-width:120px}
.form-row input{width:100px}
.log-panel{height:300px;overflow-y:auto;padding:8px 16px;font-family:'SF Mono',Monaco,monospace;font-size:12px;line-height:1.5}
.log-panel div{border-bottom:1px solid #1c2129;padding:1px 0}
.empty{color:#484f58;text-align:center;padding:40px 0}
@media(max-width:768px){.form-row{flex-direction:column}.form-row select,.form-row input{width:100%}}
</style>
</head>
<body>
<div class="header">
  <h1>🥝 Kiwi 模拟平台</h1>
  <div class="presets">
    <button class="btn btn-green" onclick="preset('small')">⚡ 小规模(1GW+5Node)</button>
    <button class="btn btn-blue" onclick="preset('full')">🏭 完整厂区(2GW+18Node)</button>
  </div>
</div>

<!-- Gateway -->
<div class="panel">
  <div class="panel-title">
    📡 网关 Gateways
    <button class="btn btn-green" onclick="createGW()">+ 新建网关</button>
  </div>
  <table id="gw-table"><tbody></tbody></table>
</div>

<!-- Node -->
<div class="panel">
  <div class="panel-title">
    📟 节点 Nodes
    <div style="display:flex;gap:8px;align-items:center">
      <button class="btn btn-blue" onclick="createNode()">+ 新建节点</button>
    </div>
  </div>
  <table id="node-table"><tbody></tbody></table>
</div>

<!-- 新建节点表单 (隐藏) -->
<div class="panel" id="node-form" style="display:none">
  <div class="panel-title">➕ 新建节点</div>
  <div class="form-row">
    <div><label>名称</label><input id="nf-name" value="Node" placeholder="节点名称"></div>
    <div><label>传感器类型</label><select id="nf-type">
      <option value="temperature">温度</option><option value="humidity">湿度</option>
      <option value="water_level">水位</option><option value="switch">开关</option>
      <option value="status">状态</option><option value="temp_humidity">温湿度一体</option>
    </select></div>
    <div><label>绑定网关</label><select id="nf-gw"></select></div>
    <div><label>上报间隔(s)</label><input id="nf-int" value="10" type="number" min="1"></div>
    <button class="btn btn-green" onclick="doCreateNode()">创建</button>
    <button class="btn btn-gray" onclick="document.getElementById('node-form').style.display='none'">取消</button>
  </div>
</div>

<!-- 编辑面板 (隐藏) -->
<div class="panel" id="edit-panel" style="display:none">
  <div class="panel-title"><span id="edit-title">✏ 编辑</span></div>
  <div class="form-row">
    <div><label>名称</label><input id="ef-name"></div>
    <div id="ef-type-group"><label>传感器类型</label><select id="ef-type">
      <option value="temperature">温度</option><option value="humidity">湿度</option>
      <option value="water_level">水位</option><option value="switch">开关</option>
      <option value="status">状态</option><option value="temp_humidity">温湿度一体</option>
    </select></div>
    <div id="ef-gw-group"><label>绑定网关</label><select id="ef-gw"></select></div>
    <div id="ef-int-group"><label>上报间隔(s)</label><input id="ef-int" type="number" min="1"></div>
    <button class="btn btn-green" onclick="doUpdate()">💾 保存</button>
    <button class="btn btn-gray" onclick="document.getElementById('edit-panel').style.display='none'">取消</button>
  </div>
</div>

<!-- 日志 -->
<div class="panel">
  <div class="panel-title">
    📋 日志
    <button class="btn btn-gray" onclick="clearLog()">清屏</button>
  </div>
  <div class="log-panel" id="log"><div class="empty">等待操作...</div></div>
</div>

<script>
let lastLog = 0;

async function api(path, opts={}) {
  const r = await fetch(path, opts);
  return r.json();
}

function preset(name) {
  api('api/preset', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({preset:name})});
}

function createGW() {
  const name = prompt('网关名称:', 'Gateway');
  if (name) api('api/gateway/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
}

function gwAction(id, action) {
  api(`api/gateway/${id}/${action}`, {method:'POST'});
}

function gwDelete(id) {
  if (confirm('删除网关?')) api(`api/gateway/${id}/delete`, {method:'POST'});
}

let editTarget = null; // {type:'gw'|'node', id:N}

function editGW(id) {
  const g = window._gwData[id];
  editTarget = {type:'gw', id};
  document.getElementById('edit-title').textContent = '✏ 编辑网关 #'+id;
  document.getElementById('ef-name').value = g.name;
  document.getElementById('ef-gw-group').style.display = 'none';
  document.getElementById('ef-int-group').style.display = 'none';
  document.getElementById('ef-type-group').style.display = 'none';
  document.getElementById('edit-panel').style.display = 'block';
}

function editNode(id) {
  const n = window._nodeData[id];
  editTarget = {type:'node', id};
  document.getElementById('edit-title').textContent = '✏ 编辑节点 #'+id;
  document.getElementById('ef-name').value = n.name;
  document.getElementById('ef-int').value = n.interval;
  document.getElementById('ef-type').value = n.sensor_type;
  document.getElementById('ef-type-group').style.display = 'block';
  document.getElementById('ef-gw-group').style.display = 'block';
  document.getElementById('ef-int-group').style.display = 'block';
  // Populate gateway dropdown
  const gwSel = document.getElementById('ef-gw');
  const gws = Object.values(window._gwData || {});
  gwSel.innerHTML = gws.map(g => `<option value="${g.id}" ${g.id===n.gateway_id?'selected':''}>[${g.id}] ${g.name}</option>`).join('');
  document.getElementById('edit-panel').style.display = 'block';
}

function doUpdate() {
  if (!editTarget) return;
  const {type, id} = editTarget;
  const name = document.getElementById('ef-name').value;
  const body = {name};
  if (type === 'node') {
    body.interval = parseInt(document.getElementById('ef-int').value) || 10;
    body.gateway_id = parseInt(document.getElementById('ef-gw').value);
    body.sensor_type = document.getElementById('ef-type').value;
  }
  api(`api/${type}/${id}/update`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  document.getElementById('edit-panel').style.display = 'none';
  editTarget = null;
}

function createNode() {
  document.getElementById('node-form').style.display = 'block';
}

function doCreateNode() {
  const name = document.getElementById('nf-name').value || 'Node';
  const stype = document.getElementById('nf-type').value;
  const gid = parseInt(document.getElementById('nf-gw').value);
  const iv = parseInt(document.getElementById('nf-int').value) || 10;
  api('api/node/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name, sensor_type:stype, gateway_id:gid, interval:iv})});
  document.getElementById('node-form').style.display = 'none';
}

function nodeAction(id, action) {
  api(`api/node/${id}/${action}`, {method:'POST'});
}

function nodeDelete(id) {
  if(confirm('删除节点?')) api(`api/node/${id}/delete`, {method:'POST'});
}

function clearLog() {
  lastLog = 99999;
  document.getElementById('log').innerHTML = '';
}

const TYPE_TAG = {
  temperature: 'tag-temp', humidity: 'tag-hum', water_level: 'tag-water',
  switch: 'tag-switch', status: 'tag-status', temp_humidity: 'tag-th',
};
const TYPE_LABEL = {
  temperature: '🌡温', humidity: '💧湿', water_level: '📏水位',
  switch: '🔘开关', status: '⚙️状态', temp_humidity: '🌡💧温湿',
};

async function poll() {
  try {
    const d = await api('api/state');

    // Gateway table
    let gwHtml = '<tr><th>ID</th><th>名称</th><th>状态</th><th>收包</th><th>节点数</th><th>操作</th></tr>';
    for (const g of d.gateways) {
      const dot = g.running ? '<span class="status-dot on"></span>运行中' : '<span class="status-dot off"></span>已停止';
      window._gwData = window._gwData || {};
      window._gwData[g.id] = g;
      const startBtn = g.running ? '' : `<button class="btn btn-green" onclick="gwAction(${g.id},'start')">▶</button>`;
      const stopBtn = g.running ? `<button class="btn btn-red" onclick="gwAction(${g.id},'stop')">⏹</button>` : '';
      gwHtml += `<tr>
        <td>${g.id}</td><td>📡 ${g.name}</td><td>${dot}</td>
        <td>${g.pkts}</td><td>${g.nodes}</td>
        <td>${startBtn} ${stopBtn} <button class="btn btn-gray" onclick="editGW(${g.id})">⚙</button> <button class="btn btn-gray" onclick="gwDelete(${g.id})">🗑</button></td>
      </tr>`;
    }
    document.getElementById('gw-table').innerHTML = gwHtml;

    // Gateway name lookup for node table
    const gwMap = {};
    for (const g of d.gateways) gwMap[g.id] = g.name;

    // Node table
    let nodeHtml = '<tr><th>ID</th><th>名称</th><th>类型</th><th>网关</th><th>间隔</th><th>上报</th><th>电池</th><th>状态</th><th>操作</th></tr>';
    for (const n of d.nodes) {
      window._nodeData = window._nodeData || {};
      window._nodeData[n.id] = n;
      const dot = n.running ? '<span class="status-dot on"></span>运行' : '<span class="status-dot off"></span>停止';
      const startBtn = n.running ? '' : `<button class="btn btn-green" onclick="nodeAction(${n.id},'start')">▶</button>`;
      const stopBtn = n.running ? `<button class="btn btn-red" onclick="nodeAction(${n.id},'stop')">⏹</button>` : '';
      nodeHtml += `<tr>
        <td>${n.id}</td><td>📟 ${n.name}</td>
        <td><span class="tag ${TYPE_TAG[n.sensor_type]||''}">${TYPE_LABEL[n.sensor_type]||n.sensor_type}</span></td>
        <td>${gwMap[n.gateway_id] || 'GW'+n.gateway_id}</td><td>${n.interval}s</td><td>${n.count}</td>
        <td>🔋${n.battery}V</td><td>${dot}</td>
        <td>${startBtn} ${stopBtn} <button class="btn btn-gray" onclick="editNode(${n.id})">⚙</button> <button class="btn btn-gray" onclick="nodeDelete(${n.id})">🗑</button></td>
      </tr>`;
    }
    document.getElementById('node-table').innerHTML = nodeHtml;

    // Populate gateway dropdown for create node form
    const sel = document.getElementById('nf-gw');
    if (sel.options.length === 0 || d.gateways.length !== sel.options.length) {
      sel.innerHTML = d.gateways.map(g => `<option value="${g.id}">[${g.id}] ${g.name}</option>`).join('');
    }
  } catch(e) {}

  // Logs
  try {
    const lines = await api('api/logs?since=' + lastLog);
    if (lines.length) {
      const logEl = document.getElementById('log');
      if (logEl.querySelector('.empty')) logEl.innerHTML = '';
      for (const l of lines) {
        const div = document.createElement('div');
        div.textContent = l;
        logEl.appendChild(div);
      }
      logEl.scrollTop = logEl.scrollHeight;
      lastLog += lines.length;
    }
  } catch(e) {}
}

setInterval(poll, 1500);
poll();
</script>
</body>
</html>"""


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    server = HTTPServer(("0.0.0.0", port), Handler)
    print("=" * 55)
    print("🥝 Kiwi 模拟平台")
    print(f"   http://localhost:{port}")
    print(f"   预设: POST /api/preset {{\"preset\":\"small\"|\"full\"}}")
    print("=" * 55)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        for g in gateways.values(): g.stop()
        for n in nodes.values(): n.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
