#!/usr/bin/env python3
"""
Kiwi HTTP→MQTT 桥接服务 v2.0
接收 LoRa 网关 HTTP POST → 路由到 MQTT broker
支持: 传感器数据、设备状态、心跳、离线、入网请求、网关心跳
"""
import json
import logging
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] bridge: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bridge")

mqtt_client = None


def init_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client(
        client_id="kiwi-ingest-bridge",
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    mqtt_client.loop_start()
    log.info("MQTT connected to %s:%s", MQTT_BROKER, MQTT_PORT)


def publish(payload: dict) -> bool:
    """根据 payload 内容路由到对应 MQTT topic"""
    if "gateway_id" in payload:
        # 网关心跳/状态
        topic = "monitor/gateway/status"
        label = "gw=%s nodes=%s" % (
            payload["gateway_id"],
            payload.get("nodes", "?"),
        )

    elif "device_id" in payload:
        device_id = payload["device_id"]
        ptype = payload.get("type", "data")

        if "sensors" in payload:
            # 传感器读数 → data topic
            topic = f"monitor/{device_id}/data"
        elif "dev_eui" in payload:
            # 入网请求(有 dev_eui) → data topic，触发 ingest auto-register
            topic = f"monitor/{device_id}/data"
        else:
            # 状态/心跳/离线 → status topic
            topic = f"monitor/{device_id}/status"

        label = "dev=%-4d type=%-9s" % (device_id, ptype)

    else:
        log.warning("Unknown payload (no device_id/gateway_id), skip")
        return False

    try:
        mqtt_client.publish(topic, json.dumps(payload), qos=0)
        log.info("→ %-32s %s", topic, label)
        return True
    except Exception as e:
        log.error("MQTT publish failed: %s", e)
        return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json_resp(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/ingest":
            self._json_resp({"ok": False, "error": "not found"}, 404)
            return

        body = b""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))

            ok = publish(payload)
            self._json_resp({"ok": ok})
        except json.JSONDecodeError:
            log.error("Invalid JSON: %s", body[:200])
            self._json_resp({"ok": False, "error": "invalid json"}, 400)
        except Exception as e:
            log.exception("Handler error")
            self._json_resp({"ok": False, "error": str(e)}, 500)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json_resp({"ok": True, "service": "kiwi-ingest-bridge"})
        else:
            self._json_resp({"ok": False, "error": "POST /ingest only"}, 405)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8883
    init_mqtt()

    server = HTTPServer(("127.0.0.1", port), Handler)
    log.info("Kiwi HTTP→MQTT bridge v2.0 listening on 127.0.0.1:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        server.shutdown()


if __name__ == "__main__":
    main()
