"""
Watchdog for meter-app-v2. v2.0.0

Checks if the meterapp service is healthy by verifying:
1. The systemd service is active
2. The app is actually reading data (checks last timestamp in SQLite)

If unhealthy, restarts the service. After 3 consecutive restart failures, forces reboot.
"""

import subprocess
import sqlite3
import json
import os
import time
from datetime import datetime

SERVICE_NAME = "meterapp"
DB_PATH = "/home/orangepi/meter-app-v2/database/active.db"
HEALTH_FILE = "/tmp/meter-health.json"
MAX_RESTART_ATTEMPTS = 3
RESTART_COOLDOWN = 300  # 5 minutes between restart cycles


def _log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [watchdog] {msg}"
    print(line)
    try:
        with open("/home/orangepi/meter-app-v2/logs/watchdog.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_service_active():
    """Check if meterapp.service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def get_last_reading_timestamp():
    """Get the timestamp of the most recent reading from SQLite."""
    if not os.path.exists(DB_PATH):
        return 0
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute(
            "SELECT MAX(timestamp_ms) FROM readings_1min"
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] else 0
    except Exception:
        return 0


def get_restart_count():
    """Get the current restart attempt count."""
    try:
        if os.path.exists(HEALTH_FILE):
            with open(HEALTH_FILE, "r") as f:
                data = json.load(f)
                return data.get("restart_count", 0), data.get("last_restart", 0)
    except Exception:
        pass
    return 0, 0


def save_health(status, restart_count=0, last_restart=0):
    """Save health status to file for other apps to read."""
    try:
        data = {
            "status": status,
            "restart_count": restart_count,
            "last_restart": last_restart,
            "last_check": datetime.now().isoformat(),
            "service_active": is_service_active(),
            "last_reading_age_s": time.time() - (get_last_reading_timestamp() / 1000) if get_last_reading_timestamp() > 0 else -1,
        }
        with open(HEALTH_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def restart_service():
    """Restart the meterapp service."""
    try:
        _log(f"Restarting {SERVICE_NAME}...")
        result = subprocess.run(
            ["sudo", "systemctl", "restart", SERVICE_NAME],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            _log("Service restarted successfully")
            time.sleep(5)  # wait for service to start
            return is_service_active()
        else:
            _log(f"Restart failed: {result.stderr}")
            return False
    except Exception as e:
        _log(f"Restart exception: {e}")
        return False


def force_reboot():
    """Force a full system reboot."""
    _log("CRITICAL: Force reboot after 3 failed restarts!")
    try:
        subprocess.run(["sudo", "reboot"], timeout=10)
    except Exception:
        os.system("sudo reboot")


def main():
    _log("Watchdog check starting")

    # Check if service is active
    service_ok = is_service_active()
    last_ts = get_last_reading_timestamp()
    last_reading_age = (time.time() - last_ts / 1000) if last_ts > 0 else -1

    # Check data freshness: if last reading is > 10 minutes old and service is "active",
    # the app may be stuck
    data_fresh = last_reading_age < 600 if last_ts > 0 else False

    restart_count, last_restart = get_restart_count()

    # If last restart was more than 5 minutes ago, reset counter
    if time.time() - last_restart > RESTART_COOLDOWN:
        restart_count = 0

    if service_ok and data_fresh:
        # Everything is healthy
        _log(f"Healthy: service active, last reading {last_reading_age:.0f}s ago")
        save_health("healthy", restart_count, last_restart)

    elif service_ok and not data_fresh and last_ts > 0:
        # Service is running but no recent data — app may be stuck
        _log(f"WARNING: Service active but last reading was {last_reading_age:.0f}s ago — restarting")
        restart_count += 1
        if restart_count > MAX_RESTART_ATTEMPTS:
            force_reboot()
            return
        if restart_service():
            save_health("restarted_stuck", restart_count, time.time())
        else:
            save_health("restart_failed", restart_count, time.time())

    elif not service_ok:
        # Service is not running
        _log(f"WARNING: Service not active — restarting (attempt {restart_count + 1})")
        restart_count += 1
        if restart_count > MAX_RESTART_ATTEMPTS:
            force_reboot()
            return
        if restart_service():
            save_health("restarted_crashed", restart_count, time.time())
        else:
            save_health("restart_failed", restart_count, time.time())

    else:
        # No data yet (fresh start)
        _log("OK: Service active, no readings yet (fresh start)")
        save_health("starting", restart_count, last_restart)

    _log("Watchdog check complete")


if __name__ == "__main__":
    main()
