# Meter App v2 — Aug 2-6 Downtime: Root Cause & Fix Report

**Date**: 2026-08-06  
**Hub**: Dammam  
**App Version**: meter-app-v2 v2.1.0  
**Affected Period**: Aug 2, 22:29 → Aug 6, 11:06 (~3.5 days)

---

## 1. Problem Summary

The meter application stopped reading energy meters from August 2nd to August 6th. During this period, **no meter data was collected** — not even locally. When the hub came back online on August 6th, the app restarted and recovered, but **3.5 days of data was permanently lost**.

The app was designed to continue reading meters and storing data locally even without internet. It failed to do so.

---

## 2. What Should Happen vs What Actually Happened

### Expected Behavior
```
Meter → Read every 60s → Store in SQLite → Push to cloud when internet available
                                  ↓
                          (no internet = data stays local, push later)
```

### Actual Behavior
```
Meter → Serial port hung → Main loop blocked → No reading for 3.5 days
                                  ↓
                          (nothing stored, nothing pushed)
```

---

## 3. Root Cause Analysis

### 3.1 The Blocking Chain

The application's main loop reads meters every 60 seconds. Before each read, it runs a **signature check** to verify the correct meter is connected. This signature check calls `read_holding_registers()` on the serial port **with no timeout**.

When the serial port hung (likely due to a USB disconnect or RS485 bus issue), the signature check blocked the entire main loop:

```
Main Loop (blocked)
    └─ read_data()
        └─ meter.read_and_store()
            └─ _check_meter_signature()
                └─ client.read_holding_registers() ← HUNG HERE (no timeout)
```

### 3.2 Timeline from Logs

| Time | Event | Block Duration |
|------|-------|----------------|
| Aug 2, 22:29:45 | Last successful meter read | — |
| Aug 2, 22:29:58 | Last API retry (internet lost) | — |
| **Aug 3, 15:05:20** | Next "Reading meter" log entry | **16.5 hours blocked** |
| Aug 3, 17:56:49 | "Read timed out after 30s (port stuck)" | 2.8 hours (rescan running) |
| Aug 3, 18:01:31 | "modbus disconnected" | — |
| **Aug 5, 10:19:34** | "Rescanning for SPM206" | **~2 days blocked** |
| Aug 5, various | Spike corrections (stale data) | — |
| **Aug 6, 11:06** | App shutdown + restart | Recovery begins |
| Aug 6, 11:40 | Fresh start, old data pushed | ✅ Normal |

### 3.3 Five Bugs Identified

| # | Bug | Impact | Location |
|---|-----|--------|----------|
| 1 | `_check_meter_signature()` has **no timeout** on `read_holding_registers()` | Main loop blocks for hours/days when serial port hangs | `meter.py` |
| 2 | `_try_rescan()` runs port scanning **synchronously** in main thread | Main loop blocks for minutes during port scan | `meter.py` |
| 3 | `Modbus.connect()` has **no timeout** | Main loop blocks if serial port is stuck | `modbus.py` |
| 4 | API Pusher retries every **5 seconds** with no backoff | 360 log lines in 15 minutes, log flooding | `api_pusher.py` |
| 5 | No **main-loop watchdog** | Nothing detects or recovers from a stuck loop | `run.py` |

---

## 4. Fixes Applied

### 4.1 `run.py` — Main Loop Watchdog

**Before**: `read_data()` called directly in main loop. If it blocks, the loop hangs forever.

**After**: `read_data()` wrapped in a thread with **5-minute timeout**. If stuck, skips to next cycle.

```python
# NEW: Watchdog timeout
CYCLE_WATCHDOG_TIMEOUT = 300  # 5 min

cycle_thread = threading.Thread(target=_cycle, daemon=True)
cycle_thread.start()
cycle_thread.join(timeout=CYCLE_WATCHDOG_TIMEOUT)
if cycle_thread.is_alive():
    print(f"[main] WATCHDOG: read_data() stuck for {CYCLE_WATCHDOG_TIMEOUT}s, skipping")
    timer = 0  # retry immediately
```

### 4.2 `meter.py` — Signature Check Timeout

**Before**: `read_holding_registers()` called directly. If serial port hangs, blocks forever.

**After**: Runs in a thread with **15-second timeout**. If hung, skips check and proceeds to read.

```python
# NEW: Thread with timeout
SIGNATURE_TIMEOUT = 15  # seconds

check_thread = threading.Thread(target=_check, daemon=True)
check_thread.start()
check_thread.join(timeout=SIGNATURE_TIMEOUT)
if check_thread.is_alive():
    return True  # skip check, try reading anyway
```

### 4.3 `meter.py` — Rescan Timeout

**Before**: `_try_rescan()` scans all serial ports synchronously. Can take minutes.

**After**: Runs in a thread with **120-second timeout**. If scan takes too long, reconnects to known port.

```python
# NEW: Thread with timeout
RESCAN_TIMEOUT = 120  # seconds

scan_thread = threading.Thread(target=_scan, daemon=True)
scan_thread.start()
scan_thread.join(timeout=RESCAN_TIMEOUT)
if scan_thread.is_alive():
    self._reconnect_to_port(known_port)  # fallback
```

### 4.4 `modbus.py` — Connect Timeout

**Before**: `client.connect()` called directly. If serial port is stuck, blocks forever.

**After**: Wrapped in `_safe_connect()` with **10-second timeout**.

```python
# NEW: Safe connect with timeout
CONNECT_TIMEOUT = 10  # seconds

def _safe_connect(self, client, success_msg):
    result = [None]
    def _do_connect():
        try:
            result[0] = client.connect()
        except Exception as ex:
            result[0] = ex
    t = threading.Thread(target=_do_connect, daemon=True)
    t.start()
    t.join(timeout=CONNECT_TIMEOUT)
    if t.is_alive():
        raise ConnectionError(f"Modbus connect timed out on {self._port}")
```

### 4.5 `api_pusher.py` — Exponential Backoff

**Before**: Retries every 5 seconds when offline. 360 log lines in 15 minutes.

**After**: Exponential backoff: 5s → 10s → 20s → 40s → ... → 300s max. Resets on success.

```python
# NEW: Exponential backoff
backoff = 5       # start at 5s
MAX_BACKOFF = 300  # max 5 min

if had_failure:
    time.sleep(backoff)
    backoff = min(backoff * 2, MAX_BACKOFF)
```

---

## 5. Files Modified

| File | Changes |
|------|---------|
| `run.py` | Added watchdog thread around `read_data()` |
| `src/meter.py` | Signature check + rescan run in timeout threads |
| `src/modbus.py` | `connect()` wrapped in timeout thread, `closeConnection()` catches exceptions |
| `src/api_pusher.py` | Exponential backoff on retry |

---

## 6. Deployment

```bash
# Copy modified files to hub, then:
cd /opt/meter-app-v2
sudo systemctl restart meterapp

# Verify:
systemctl status meterapp
journalctl -u meterapp --since "5 min ago"
```

---

## 7. Verification Checklist

After deployment, verify:

- [ ] `systemctl status meterapp` shows `active (running)`
- [ ] `tail -f /opt/meter-app-v2/logs/app/log.txt` shows "Reading meter" every ~60s
- [ ] `tail -f /opt/meter-app-v2/logs/main/log.txt` shows "API Pusher thread starting"
- [ ] Disconnect ethernet → meter readings continue in app log
- [ ] Reconnect ethernet → pending data pushes to cloud
- [ ] Disconnect USB serial → app recovers within 5 minutes (watchdog)

---

## 8. Lessons Learned

1. **Every I/O call needs a timeout** — serial port operations, network calls, database locks
2. **Background tasks must not block the main loop** — port scanning, reconnection, signature checks
3. **Watchdog timers are essential** — detect stuck loops before they cause days of data loss
4. **Exponential backoff prevents log flooding** — 5s retry creates 360 log lines in 15 minutes
5. **Test without internet** — the app was never tested in an offline scenario for extended periods

---

## 9. Related: Minor Shutdown Issue

During the Aug 6 restart, a secondary issue was observed:

```
[Storage] insert_backup_record failed Cannot operate on a closed database.
[Storage] get_pending_backups failed Cannot operate on a closed database.
```

This is a race condition where the backup thread tries to use the database after it's been closed during shutdown. **Not related to the main outage**, but should be fixed separately.
