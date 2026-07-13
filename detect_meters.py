#!/usr/bin/env python3
"""
Standalone meter detection script.
===================================
Scans serial ports and identifies connected meters via Modbus.
Optionally writes detected meters into config.json.

Usage:
    python detect_meters.py              # scan and print results
    python detect_meters.py --save       # scan, print, and update config.json
    python detect_meters.py --port COM3  # scan only a specific port
"""

import json
import sys
import os

from src.auto_detect import detect_meters, scan_ports


def print_banner():
    print("=" * 60)
    print("   METER AUTO-DETECTION")
    print("   Scanning serial ports for Modbus meters...")
    print("=" * 60)
    print()


def print_results(results):
    """Print detection results in a formatted table."""
    if not results:
        print("  No meters detected.")
        print()
        print("  Possible reasons:")
        print("  - No serial ports available")
        print("  - No meters connected")
        print("  - Meters not powered on")
        print("  - Wrong baud rate or slave ID")
        return

    print(f"  {'#':<4} {'Port':<16} {'Baud':<8} {'Slave':<7} {'Meter Type':<12} Description")
    print(f"  {'─'*4} {'─'*16} {'─'*8} {'─'*7} {'─'*12} {'─'*30}")
    for i, r in enumerate(results, 1):
        print(f"  {i:<4} {r['port']:<16} {r['baudrate']:<8} {r['slave_id']:<7} {r['meter_type']:<12} {r.get('description', '')}")
    print()


def save_to_config(results):
    """Update config.json with detected meters."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        config = {}

    # Build meter entries
    meters = []
    for i, r in enumerate(results):
        meter = {
            "Meter_type": r["meter_type"],
            "MeterID": str(r["slave_id"]),
            "Serail_Port": r["port"],
            "Serial_Baudrate": r["baudrate"],
            "serial": False,
            "MQTT_topic": f"meter_{r['meter_type'].lower()}_{i+1}",
        }
        meters.append(meter)

    config["meters"] = meters
    config["auto_detect"] = False  # disable after successful detection

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  Config saved to: {config_path}")
    print(f"  Detected {len(results)} meter(s) written to config.json")


def main():
    print_banner()

    # Parse simple CLI args
    save_mode = "--save" in sys.argv
    specific_port = None
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            specific_port = sys.argv[i + 1]

    # Show available ports
    ports = scan_ports()
    if ports:
        print(f"  Available ports: {', '.join(ports)}")
    else:
        print("  No serial ports detected.")
        print()
        return
    print()

    # Run detection
    ports_to_scan = [specific_port] if specific_port else None
    results = detect_meters(ports=ports_to_scan)

    # Print results
    print_results(results)

    # Optionally save to config
    if save_mode and results:
        save_to_config(results)
    elif save_mode and not results:
        print("  Nothing to save — no meters detected.")


if __name__ == "__main__":
    main()
