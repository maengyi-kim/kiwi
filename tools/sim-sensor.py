#!/usr/bin/env python3
"""
厂区监控 — 传感器模拟器
模拟传感器通过 MQTT 向服务器发送数据，用于端到端验证。
"""

import json
import random
import time
import sys
import os
from datetime import datetime

# ─── 使用项目 venv 的 paho-mqtt ───
VENV_PYTHON = os.path.expanduser("~/monitor/venv/bin/python")
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# ─── 虚拟设备定义 ───
DEVICES = [
    {"id": 1, "name": "冷库1号", "sensors": ["temperature", "humidity"],
     "temp_range": (-25, -18), "humidity_range": (55, 75), "battery": 3.85},
    {"id": 2, "name": "冷库2号", "sensors": ["temperature", "humidity"],
     "temp_range": (-24, -17), "humidity_range": (50, 70), "battery": 3.72},
    {"id": 3, "name": "冷库3号", "sensors": ["temperature", "humidity"],
     "temp_range": (-26, -19), "humidity_range": (60, 80), "battery": 3.91},
    {"id": 10, "name": "水箱1号", "sensors": ["water_level"],
     "water_range": (600, 1500), "battery": 3.78},
    {"id": 11, "name": "水箱2号", "sensors": ["water_level"],
     "water_range": (400, 1200), "battery": 3.65},
    {"id": 20, "name": "车间温湿度", "sensors": ["temperature", "humidity"],
     "temp_range": (15, 30), "humidity_range": (40, 65), "battery": 3.95},
    {"id": 21, "name": "宿舍温湿度", "sensors": ["temperature", "humidity"],
     "temp_range": (18, 28), "humidity_range": (45, 70), "battery": 3.88},
]


def gen_sensor_data(device):
    """生成一条传感器数据"""
    sensors = []
    for stype in device["sensors"]:
        if stype == "temperature":
            tmin, tmax = device["temp_range"]
            value = round(random.uniform(tmin, tmax), 1)
            sensors.append({"type": "temperature", "value": value, "unit": "°C"})
        elif stype == "humidity":
            hmin, hmax = device["humidity_range"]
            value = round(random.uniform(hmin, hmax), 1)
            sensors.append({"type": "humidity", "value": value, "unit": "%"})
        elif stype == "water_level":
            wmin, wmax = device["water_range"]
            value = round(random.uniform(wmin, wmax))
            sensors.append({"type": "water_level", "value": value, "unit": "mm"})

    # 电池微微波动
    battery = round(device["battery"] + random.uniform(-0.05, 0.02), 2)

    return {
        "device_id": device["id"],
        "dev_eui": f"DEADBEEF{device['id']:04X}",
        "sensors": sensors,
        "battery": battery,
        "rssi": random.randint(-110, -60),
        "snr": round(random.uniform(-5, 12), 1),
        "frame_counter": random.randint(1, 255),
        "data_rate": random.randint(2, 5),
        "timestamp": int(time.time()),
    }


def publish_mqtt(client, topic, payload):
    """发布到 MQTT"""
    import paho.mqtt.client as mqtt_client
    result = client.publish(topic, json.dumps(payload), qos=0)
    return result.rc == mqtt_client.MQTT_ERR_SUCCESS


def run_once():
    """发送一轮数据（所有设备各一条）"""
    import paho.mqtt.client as mqtt_client
    client = mqtt_client.Client(
        client_id="sensor-simulator",
        protocol=mqtt_client.MQTTv5,
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
    )
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=10)

    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'='*50}")
    print(f"  📡 传感器模拟器 — {now}")
    print(f"{'='*50}")

    total_sensors = 0
    for device in DEVICES:
        payload = gen_sensor_data(device)
        topic = f"monitor/{device['id']}/data"
        ok = publish_mqtt(client, topic, payload)
        status = "✅" if ok else "❌"

        sensors_str = " | ".join(
            f"{s['type']}={s['value']}{s['unit']}" for s in payload["sensors"]
        )
        print(f"  {status} {device['name']:12s} ({topic:20s}) → {sensors_str}  🔋{payload['battery']}V")
        total_sensors += len(payload["sensors"])

    # 网关心跳
    gw_payload = {
        "gateway_id": "gw-001",
        "status": "online",
        "nodes_heard": len(DEVICES),
        "uptime": random.randint(3600, 86400),
        "timestamp": int(time.time()),
    }
    publish_mqtt(client, "monitor/gateway/status", gw_payload)
    print(f"  ✅ {'网关':12s} (monitor/gateway/status) → 在线, {len(DEVICES)}节点")

    client.disconnect()
    print(f"\n  📊 共发送 {len(DEVICES)} 条设备数据 | {total_sensors} 个传感器读数 | 1 条网关心跳")
    print()


def run_loop(interval=10):
    """循环发送，interval=间隔秒数"""
    print(f"🔄 循环模式，每 {interval} 秒发送一轮 (Ctrl+C 停止)")
    round_num = 0
    try:
        while True:
            round_num += 1
            print(f"\n--- 第 {round_num} 轮 ---")
            run_once()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹ 模拟器已停止")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "loop":
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            run_loop(interval)
        elif arg == "once":
            run_once()
        elif arg == "help":
            print(__doc__)
            print("用法:")
            print("  python3 sim-sensor.py once      发送一轮")
            print("  python3 sim-sensor.py loop [N]  每N秒循环发送（默认10秒）")
        else:
            print(f"未知参数: {arg}，请用 'once' 或 'loop'")
    else:
        # 默认：发送一轮
        run_once()


if __name__ == "__main__":
    main()
