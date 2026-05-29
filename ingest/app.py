"""
厂区监控系统 — Python Ingest 服务
MQTT 订阅 → 解析 → TimescaleDB 入库 → 告警检查
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt
import psycopg2
import psycopg2.extras

# ─── Config ───────────────────────────────────────────────
TZ = timezone(timedelta(hours=8))

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPICS = [
    ("monitor/+/data", 0),
    ("monitor/+/status", 0),
    ("monitor/gateway/status", 0),
]

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5433"))
DB_NAME = os.getenv("DB_NAME", "monitor")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "monitor_sensor_2026")

ALARM_COOLDOWN = int(os.getenv("ALARM_COOLDOWN", "1800"))  # 同设备同类告警30分钟内不重复

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ingest")

# ─── Database ─────────────────────────────────────────────
_last_alarm = {}  # {(device_id, sensor_type, level): timestamp}


def get_db():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def get_device(db, device_id: int):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM devices WHERE device_id = %s", (device_id,)
        )
        return cur.fetchone()


def insert_sensor_data(db, data: dict, device: dict):
    """Insert one sensor reading. Returns True if inserted."""
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO sensor_data
                (time, device_id, device_name, sensor_type, value, unit,
                 battery, rssi, snr, frame_counter, data_rate)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get("timestamp", datetime.now(TZ)),
            data["device_id"],
            device["device_name"],
            data["sensor_type"],
            data["value"],
            data.get("unit", ""),
            data.get("battery"),
            data.get("rssi"),
            data.get("snr"),
            data.get("frame_counter", 0),
            data.get("data_rate", 3),
        ))
    return True


def update_heartbeat(db, device_id: int):
    with db.cursor() as cur:
        cur.execute(
            "UPDATE devices SET last_seen = NOW() WHERE device_id = %s",
            (device_id,),
        )


def check_alarm(db, device: dict, sensor_type: str, value: float):
    """Check alarm rules and insert alarm if threshold crossed."""
    rules = device.get("alarm_rules", {})
    if not rules:
        return

    sensor_rules = rules.get(sensor_type)
    if not sensor_rules:
        return

    device_id = device["device_id"]
    now = time.time()

    # Check thresholds
    for level, key in [("critical", "critical_max"), ("warning", "max")]:
        threshold = sensor_rules.get(key)
        if threshold is not None and value > threshold:
            # Cooldown check
            cache_key = (device_id, sensor_type, level)
            last = _last_alarm.get(cache_key, 0)
            if now - last < ALARM_COOLDOWN:
                continue
            _last_alarm[cache_key] = now

            msg = f"⚠️ {device['device_name']} {sensor_type}异常: {value}{sensor_rules.get('unit','')} (阈值 {threshold})"
            insert_alarm(db, device, sensor_type, level, msg, value, threshold)
            send_weixin_alert(msg)

    for level, key in [("critical", "critical_min"), ("warning", "min")]:
        threshold = sensor_rules.get(key)
        if threshold is not None and value < threshold:
            cache_key = (device_id, sensor_type, level)
            last = _last_alarm.get(cache_key, 0)
            if now - last < ALARM_COOLDOWN:
                continue
            _last_alarm[cache_key] = now

            msg = f"⚠️ {device['device_name']} {sensor_type}过低: {value}{sensor_rules.get('unit','')} (阈值 {threshold})"
            insert_alarm(db, device, sensor_type, level, msg, value, threshold)
            send_weixin_alert(msg)


def insert_alarm(db, device, sensor_type, level, message, value, threshold):
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO alarms (device_id, device_name, sensor_type, alarm_level, message, value, threshold)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (device["device_id"], device["device_name"], sensor_type, level, message, value, threshold))
    db.commit()
    log.warning("ALARM: %s", message)


def send_weixin_alert(message: str):
    """Send alert to WeChat via Hermes send_message webhook."""
    try:
        import urllib.request
        data = json.dumps({"action": "send", "message": message, "target": "weixin"}).encode()
        req = urllib.request.Request(
            "http://localhost:8100/api/message/send",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log.error("Failed to send WeChat alert: %s", e)


def process_data_payload(payload: dict):
    """Process a data payload from MQTT monitor/+/data topic."""
    device_id = payload.get("device_id")
    if device_id is None:
        log.warning("Missing device_id in payload")
        return

    db = get_db()
    try:
        device = get_device(db, device_id)
        if not device:
            # Auto-register unknown device
            with db.cursor() as cur:
                dev_eui = payload.get("dev_eui", f"unknown_{device_id}")
                cur.execute("""
                    INSERT INTO devices (device_id, dev_eui, device_name, sensor_types)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (device_id) DO NOTHING
                """, (device_id, dev_eui, f"设备#{device_id}", "[]"))
            db.commit()
            device = get_device(db, device_id)
            log.info("Auto-registered device %s", device_id)

        # Update heartbeat
        update_heartbeat(db, device_id)

        # Process sensors
        sensors = payload.get("sensors", [])
        if isinstance(sensors, dict):
            sensors = [sensors]

        for sensor in sensors:
            stype = sensor.get("type")
            value = sensor.get("value")
            if stype is None or value is None:
                continue

            data = {
                "device_id": device_id,
                "sensor_type": stype,
                "value": float(value),
                "unit": sensor.get("unit", ""),
                "battery": payload.get("battery"),
                "rssi": payload.get("rssi"),
                "snr": payload.get("snr"),
                "frame_counter": payload.get("frame_counter"),
                "data_rate": payload.get("data_rate"),
                "timestamp": payload.get("timestamp"),
            }
            if data["timestamp"] and isinstance(data["timestamp"], (int, float)):
                data["timestamp"] = datetime.fromtimestamp(data["timestamp"], tz=TZ)
            else:
                data["timestamp"] = datetime.now(TZ)

            insert_sensor_data(db, data, device)
            check_alarm(db, device, stype, value)

        db.commit()
        log.debug("Processed data from device %s: %d sensors", device_id, len(sensors))

    except Exception as e:
        db.rollback()
        log.error("Error processing data from device %s: %s", device_id, e)
    finally:
        db.close()


def process_status_payload(payload: dict):
    """Process a status/heartbeat payload."""
    device_id = payload.get("device_id")
    if device_id is None:
        return

    db = get_db()
    try:
        update_heartbeat(db, device_id)

        # Update battery/rssi in device metadata
        with db.cursor() as cur:
            cur.execute(
                "UPDATE devices SET updated_at = NOW() WHERE device_id = %s",
                (device_id,),
            )

        db.commit()
        log.debug("Heartbeat from device %s", device_id)
    except Exception as e:
        db.rollback()
        log.error("Error processing status: %s", e)
    finally:
        db.close()


# ─── MQTT Callbacks ──────────────────────────────────────
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to MQTT broker at %s:%s", MQTT_BROKER, MQTT_PORT)
        for topic, qos in MQTT_TOPICS:
            client.subscribe(topic, qos)
            log.info("Subscribed: %s", topic)
    else:
        log.error("MQTT connection failed, rc=%s", rc)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        topic = msg.topic
        log.debug("MQTT: %s → %s", topic, str(payload)[:200])

        if topic.endswith("/data"):
            process_data_payload(payload)
        elif topic.endswith("/status") or topic == "monitor/gateway/status":
            process_status_payload(payload)
        else:
            log.warning("Unknown topic: %s", topic)
    except json.JSONDecodeError:
        log.error("Invalid JSON payload on %s: %s", msg.topic, msg.payload[:100])
    except Exception as e:
        log.exception("Unhandled error in on_message")


def on_disconnect(client, userdata, rc, properties=None):
    log.warning("MQTT disconnected (rc=%s), will auto-reconnect", rc)


# ─── Main ─────────────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info("Monitor Ingest Service starting...")
    log.info("MQTT: %s:%s", MQTT_BROKER, MQTT_PORT)
    log.info("DB:   %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)
    log.info("=" * 50)

    # Verify DB connection
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM devices")
            count = cur.fetchone()[0]
            log.info("Database OK, %d devices registered", count)
        db.close()
    except Exception as e:
        log.error("Database connection failed: %s", e)
        sys.exit(1)

    # Create MQTT client
    client = mqtt.Client(
        client_id="monitor-ingest",
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Connect and loop
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            log.error("MQTT connection error: %s, retrying in 10s...", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
