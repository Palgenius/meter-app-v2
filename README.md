# meter-app-v2 — Energy Meter Application (v2.2.0)

## Overview

Python application that reads energy meters via Modbus RTU, stores data locally in SQLite, aggregates 15-minute intervals, and pushes to the cloud API. Runs on Orange Pi Zero 3 devices at commercial building sites.

## Architecture

```
Energy Meter (PMAC211)
    │ RS485 Modbus RTU
    ▼
meter-app-v2 (Python)
    ├── meter.py          → Reads Modbus registers
    ├── modbus.py         → Modbus RTU communication
    ├── aggregator.py     → 15-min interval aggregation
    ├── api_pusher.py     → Pushes to cloud API
    ├── storage.py        → SQLite database (WAL mode)
    ├── socket_server.py  → TCP :5555 for BLE + hub-agent
    ├── validator.py      → Data validation rules
    ├── backup.py         → Dropbox backup
    └── app.py            → Orchestrator
```

## Implemented Features

### ✅ Core Meter Reading
- **Modbus RTU** communication via RS485 USB adapter
- **Auto-detect** meter on `/dev/ttyUSB0` (PMAC211 default)
- **1-minute polling** (configurable via `request_time`)
- **Register read fallback**: bulk read → one-by-one for PMAC211 firmware quirks
- **Dead register handling**: failed registers get value 0, continue reading

### ✅ Data Storage
- **SQLite with WAL mode** for concurrent reads/writes
- **1-minute raw readings** (`readings_1min` table)
- **15-minute aggregated samples** (`readings_15min` table)
- **Monthly archiving** to separate database files
- **Corruption recovery** with integrity checks on startup

### ✅ 15-Minute Aggregation
- **Automatic window detection**: aggregates completed 15-min windows
- **Statistical aggregation**: mean for V/I/P/Q/S/PF/F, sum for AE/RE
- **Zero-ignoring**: dead registers don't skew averages
- **CSV logging**: all aggregated records written to samples CSV

### ✅ Cloud API Push
- **POST to https://tools.ampenergy.ae/data**
- **Schedule**: minutes :03, :18, :33, :48
- **Retry logic**: failed records retry every 5 minutes (configurable)
- **Response validation**: checks HTTP status AND response body `statusCode`
- **Status tracking**: pending → sent/failed

### ✅ TCP Socket Server (localhost:5555)
- **Broadcasts** readings, validation, alerts, health every 30s
- **BLE app** (bluetooth_manager) connects for real-time data
- **Hub-agent** connects for server-side dashboard
- **Bidirectional commands**: config read/write, reload, status, last_reading

### ✅ Data Validation
- **Voltage range check**: 90-140V or 180-240V
- **Frequency check**: 49-51Hz
- **Zero-value detection**: flags channels with all zeros
- **Confidence scoring**: 0.0 to 1.0

### ✅ Backup
- **Daily and monthly** SQLite backups
- **Dropbox upload** (requires valid token)

### ✅ Alert System (v2.2.0)
- **API push failure**: alerts after 3 consecutive failures
- **Push recovery**: alerts when push resumes after failures
- **Meter read failure**: alerts when Modbus read fails
- **Aggregation errors**: alerts on aggregation failures
- **Health warnings**: alerts when cycle takes too long
- **Critical log size**: alerts when logs exceed 500MB
- **Forwarded to hub-agent** → server → dashboard via Socket.IO

## Configuration (config.json)

| Key | Default | Description |
|-----|---------|-------------|
| `auto_detect` | true | Auto-detect meters on startup |
| `request_time` | 1 | Polling interval in minutes |
| `api_push_enabled` | true | Enable cloud API push |
| `api_push_url` | https://tools.ampenergy.ae/data | API endpoint |
| `api_push_interval` | 30 | Seconds between push retries |
| `push_retry_interval` | 300 | Seconds between failed record retries |
| `backup_enabled` | true | Enable backups |
| `dropbox_backup_enabled` | true | Enable Dropbox upload |

## Known Issues

| Issue | Status | Impact |
|-------|--------|--------|
| API returns 401 "Panel not registered" | ⚠️ Pending | Data stored locally, not pushed to cloud |
| Dropbox token expired | ⚠️ Pending | Backup uploads fail |
| PMAC211 bulk read slow (~12s) | ⚠️ Optimization needed | One-by-one fallback works but slow |

## Deployment

```bash
# Deploy to Orange Pi
scp -r src/ orangepi@192.168.0.112:/opt/meter-app-v2/
scp config.json orangepi@192.168.0.112:/opt/meter-app-v2/

# Restart
ssh orangepi@192.168.0.112 "echo 'orangepi' | sudo -S systemctl restart meterapp"
```

## Service

- **Name**: meterapp.service
- **User**: orangepi
- **Path**: /opt/meter-app-v2/
- **Logs**: /opt/meter-app-v2/logs/main/log.txt
- **Database**: /opt/meter-app-v2/database/active.db