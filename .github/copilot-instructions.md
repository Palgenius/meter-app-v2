# Copilot Instructions - Meter Reading App

## Project Overview

This is an **embedded IoT Python application** that runs on an **Orange Pi Zero 3 (2 GB RAM)** as a systemd service. It continuously reads electrical meter data via **RS485 Modbus RTU** (or direct serial JSON), stores readings locally when offline, and forwards them to a remote server over **MQTT** (optionally with TLS / AWS IoT).

The app is designed to be always-on, headless, and resource-constrained. It must never crash, leak memory, or block indefinitely.

---

## Hardware and Runtime Environment

| Item | Detail |
|---|---|
| Board | Orange Pi Zero 3, Allwinner H618, 2 GB RAM |
| OS | Armbian / Debian-based Linux (ARM64) |
| Python | 3.10+ (CPython) |
| Serial | RS485 via USB-to-serial or UART (/dev/ttyUSB*, /dev/ttyS*) |
| Protocol | Modbus RTU over RS485 or direct serial JSON |
| Connectivity | Wi-Fi (wlan0), MQTT broker (local mosquitto or AWS IoT) |
| Deployment | systemd service (meterapp.service), auto-restart on failure |
| Production build | Cython-compiled .so files via exportApp.py |

### Resource constraints - keep in mind at all times

- **2 GB RAM total** - avoid large in-memory buffers, unnecessary copies, or heavy libraries.
- **SD-card storage** - minimise disk writes; use rotating log files (already configured).
- **No GPU / display** - purely headless; all output is log files or MQTT.
- **Continuous 24/7 operation** - no memory leaks, no unbounded growth of lists/queues.

---

## Architecture and Data Flow

```
Meter(s) --[Modbus RTU / Serial JSON]--> Modbus.py / DSerial.py (read raw registers / JSON)
    --> meter.py (per-meter: decode, quarter-split, queue)
    --> database.py (pickle FIFO queue) <--> mqttClient.py (paho-mqtt publish)
```

### Key modules

| File | Responsibility |
|---|---|
| run.py | Entry point - signal handling, main polling loop |
| src/main.py | Orchestrator - loads config, creates Meter instances, starts MQTT sending threads |
| src/config.py | Loads/saves config.json, derives a deterministic UUID from the device MAC address |
| src/meter.py | Per-meter logic: grab data, decode, divide-to-quarters, store/publish |
| src/modbus.py | Modbus RTU client via pymodbus 2.5.3 (sync ModbusSerialClient) |
| src/dSerial.py | Alternative serial reader - sends a command (pushmm/push00), reads JSON from the device |
| src/mqttClient.py | MQTT publish with auto-reconnect; TLS support for AWS IoT |
| src/database.py | Simple pickle-based FIFO queue for offline buffering |
| src/logger.py | Rotating file loggers for APP, MQTT CSV, and raw METER data |
| src/meters_format/ | Meter-specific register maps and decoders (Factory pattern via format.py) |
| exportApp.py | Cython build script for production .so distribution |
| config.json | Runtime configuration (meters list, MQTT broker, logging, node ID) |

---

## Supported Meter Types

Each meter type has its own format class in src/meters_format/:

| Meter Type | Class | Comm | Channels | File |
|---|---|---|---|---|
| SMP20 / SPM20 | SMP20 | Modbus RTU | 30 CTs, 3-phase | SMP20Format.py |
| PMAC202 | PMAC202 | Modbus RTU | 42 CTs, 3-phase | PMAC202Format.py |
| PMAC211 | PMAC211 | Modbus RTU | 4 groups x 3 phases | PMAC211Format.py |
| SPM206CT42 | SPM206 | Modbus RTU | 42 CTs, 3-phase | SPM206CT42Format.py |
| SPM206CT54 | SPM206 | Modbus RTU | up to 54 CTs, 3-phase | SPM206CT54Format.py |
| SPM32 / SMP32 | SPM32 | Modbus RTU | 3 CTs + totals | SPM32Format.py |
| Kitty / Kitt | KITT | Serial JSON (DSerial) | 12 CTs, 3-phase | KittFormat.py |

### Electrical parameters vocabulary

- V - Voltage (AV, BV, CV = phase A/B/C)
- I - Current, P - Active Power (kW), Q - Reactive Power (kVAR)
- S - Apparent Power (kVA), PF - Power Factor
- AE - Active Energy (kWh cumulative), RE - Reactive Energy (kVARh cumulative)
- T prefix - Total (sum of all channels), C{n} prefix - Channel n
- Suffix a/b/c = phase A/B/C

---

## Configuration (config.json)

Key fields:

- productionMode - false uses sample data (no real serial hardware needed)
- request_time - polling interval in MINUTES (multiplied by 60 in code). 0.1 = 6 seconds.
- meters[] - array of meter definitions:
  - Meter_type - must match a key in format.py factory
  - MeterID - Modbus slave address
  - Serail_Port - serial port path (note: intentional misspelling, do NOT rename)
  - Serial_Baudrate - baud rate
  - MQTT_topic - per-meter MQTT sub-topic
  - serial: true - use DSerial (JSON over serial) instead of Modbus
- Node - unique node identifier for this device
- PanelID - auto-derived from the device wlan0 MAC address, do not manually set
- MQTT_broker_* - broker address, port, TLS cert paths

---

## Coding Conventions and Rules

### General

- Python 3.10+ - use compatible syntax; avoid 3.11+ features.
- Existing code uses mixed snake_case / camelCase - match the style of the surrounding code in each file.
- Prefer if(condition): parenthesised style that the codebase already uses.
- Imports at module top.

### Memory and Performance

- Never load entire files into memory when streaming would work.
- The pickle-based database stores a Python list - keep it short; data should flow to MQTT quickly.
- Avoid importing heavy libraries (pandas, numpy, etc.) - this is a 2 GB ARM device.
- Do not spawn unnecessary threads or processes.

### Serial / Modbus

- pymodbus 2.5.3 is pinned - use the sync ModbusSerialClient API from pymodbus.client.sync.
- Always include time.sleep() between consecutive Modbus reads (at least 0.2 s) to respect RS485 bus timing.
- When adding a new meter format, create a new file in src/meters_format/, add the class, and register it in format.py with an if branch.

### MQTT

- paho-mqtt 1.6.1 is pinned - use the 1.x callback API (on_connect(client, userdata, flags, rc)).
- MQTT topic structure: {meter.MQTT_topic} - data is published as JSON.
- The client handles reconnection internally via is_Connected() - do not add external reconnect loops.

### Database / Offline Queue

- database.py uses Python pickle as a FIFO list, not TinyDB (despite old comments).
- commit() writes the full list to disk on every insert/remove - be aware of SD card wear.
- get() returns the first item (0, data) or None.

### Logging

- Three log categories per meter: APP (text), MQTT (CSV via csv-logger), METER (raw registers).
- Logs use RotatingFileHandler with configurable max size and file count - do not change the rotation strategy.
- Use self.logger.insert_Info_APP_log(...) and self.logger.insert_Error_APP_log(...).

---

## Adding a New Meter Type

1. Create src/meters_format/<Name>Format.py with a class that implements:
   - LOG_HEADER (list) - CSV column names
   - READING_PAYLOADS (list of dicts) - Modbus register read commands {"address": int, "count": int}
   - values (list of dicts) - register-to-field mapping with key, remark (divisor), position, length
   - summingValues (dict) - aggregation rules for totals
   - __init__(self, PanelID, MeterID, Node, meter_info)
   - decode(self, bytes) -> dict - convert raw registers to a payload dict
   - getDeviceValues(self) -> dict
   - getValues(self) -> list
   - getSummingValues(self) -> dict
   - getsampleData(self) -> dict (optional, for productionMode=false testing)
2. Register it in src/meters_format/format.py __init__ with an if block.
3. Add the meter type string to config.json meters[].Meter_type.

---

## Energy Calculation Logic

- AE/RE are cumulative from the meter - Modbus.AE_RE_comulative_to_static() converts them to per-interval deltas.
- meter.divideToQuarters() interpolates readings when the gap between polls exceeds 10 minutes, splitting into 5-minute windows with proportional energy/power values.

---

## Testing

- Set productionMode to false in config.json to run without real hardware. Each meter format class provides getsampleData() that returns mock register data.
- Logs go to logs/app/, logs/mqtt/, logs/meter/ - check these for debugging.
- MQTT can be tested against a local mosquitto broker (localhost:1883, no TLS).

---

## Deployment

- The app runs as a systemd service defined in meterapp.service.
- Working directory: /home/amp/meter-app/ on the Orange Pi.
- The service auto-restarts on failure with a 10-second delay.
- For production, exportApp.py compiles all .py to .so via Cython.
- Wi-Fi reconnection is handled by an external cron script (not part of this repo).

---

## Common Pitfalls

1. Serail_Port is intentionally misspelled in the codebase - do NOT rename it; it would break config compatibility.
2. request_time is in minutes, not seconds - 0.1 = 6 seconds between reads.
3. Energy values (AE/RE) are cumulative from the meter - the app computes deltas internally.
4. pymodbus 2.5.3 import path is pymodbus.client.sync - newer versions changed this.
5. The database is a plain pickle list, not TinyDB - do not import or reference TinyDB.
6. divideToQuarters is not actually dividing into quarter-hours; it interpolates missed 5-minute windows when polling gaps exceed 10 minutes.
