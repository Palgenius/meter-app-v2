# meter-app-v2 Development Plan

> Version 2.2.0 — Updated 2026-06-16

---

## ✅ Completed Features

### Core Reading
- [x] Modbus RTU communication via RS485 USB adapter
- [x] Auto-detect meter on `/dev/ttyUSB0` (PMAC211 default)
- [x] 1-minute polling (configurable via `request_time`)
- [x] Bulk read fallback for PMAC211 firmware quirks
- [x] Dead register handling (failed registers get value 0)

### Data Storage
- [x] SQLite with WAL mode for concurrent reads/writes
- [x] 1-minute raw readings (`readings_1min` table)
- [x] 15-minute aggregated samples (`readings_15min` table)
- [x] Monthly archiving to separate database files
- [x] Corruption recovery with integrity checks on startup

### 15-Minute Aggregation
- [x] Automatic window detection
- [x] Statistical aggregation (mean for V/I/P/Q/S/PF, sum for AE/RE)
- [x] Zero-ignoring for averages
- [x] CSV logging of all aggregated records per meter

### Cloud API Push
- [x] POST to https://tools.ampenergy.ae/data
- [x] Response validation (HTTP status + body statusCode)
- [x] Auto-retry failed records every 5 minutes
- [x] Status tracking: pending → sent/failed

### TCP Socket Server (localhost:5555)
- [x] Broadcasts readings, validation, alerts, health
- [x] BLE app + hub-agent connect as clients
- [x] Bidirectional commands: config_read/write, reload, status
- [x] On-demand: last_reading, ct_read, ct_write

### Data Validation (8 Rules)
- [x] V1: Voltage plausibility (90-140V or 180-240V)
- [x] V2: Frequency plausibility (45-62 Hz)
- [x] V3: Current within CT max
- [x] V4: Power factor 0-1.0
- [x] V5: Energy monotonicity
- [x] V6: Zero data detection (3+ consecutive)
- [x] V7: Spike detection (>10x power jump)
- [x] V8: Time gap detection (>2x expected)

### Alert System (v2.2.0)
- [x] Energy spikes (modbus.py) → TCP socket → server
- [x] API push failures (after 3 consecutive) → alerts
- [x] API push recovery → alerts
- [x] Meter read failures → alerts
- [x] Aggregation errors → alerts
- [x] Health warnings → alerts
- [x] Critical log size → alerts
- [x] Configurable alert levels (none/critical/warning/info)

### Backup
- [x] Daily and monthly SQLite backups
- [x] Dropbox upload (requires valid token)

### CT Configuration (v2.2.0)
- [x] Read CT values via Modbus (registers 5018-5021)
- [x] Write CT values via Modbus
- [x] Exposed via TCP socket commands (ct_read, ct_write)
- [x] Accessible from server dashboard

---

## ⚠️ Known Issues

| Issue | Status | Impact |
|-------|--------|--------|
| API returns 401 "Panel not registered" | Pending | Data stored locally, not pushed to cloud |
| Dropbox token expired | Pending | Backup uploads fail |
| PMAC211 bulk read slow (~12s) | Optimization needed | One-by-one fallback works but slow |

---

## 📋 Remaining Development

### Priority 1 — Critical
- [ ] **Panel registration on Azure backend** — API returns 401, data not reaching cloud
- [ ] **Dropbox token refresh** — Backup uploads failing with expired token

### Priority 2 — Important
- [ ] **BLE testing with IntegratorAPP** — Commissioning wizard not tested with real device
- [ ] **Validation alerts for WARNING level** — Currently only CRITICAL triggers alerts
- [ ] **CT configuration via Bluetooth manager** — Same CT config should work via BLE

### Priority 3 — Enhancement
- [ ] **PMAC211 bulk read optimization** — Current ~12s for 208 registers, could optimize
- [ ] **Configurable voltage/frequency thresholds** — Currently hardcoded in validator.py
- [ ] **Channel-specific CT max values** — Use CT config for V3 validation
- [ ] **Historical alert viewing on dashboard** — Already implemented, verify working

### Priority 4 — Nice to Have
- [ ] **Cython build for production** — exportApp.py exists but not tested
- [ ] **Multi-meter support testing** — Config supports multiple meters, needs testing
- [ ] **MQTT integration** — MQTT_topic in config but not implemented
- [ ] **Data export to CSV** — Manual export of historical readings

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2026-06-11 | Initial modular rewrite from legacy code |
| 2.1.0 | 2026-06-11 | Bug fixes: serial key, bulk read, push URL, false success, samples log |
| 2.2.0 | 2026-06-16 | Alert system, CT config, on-demand reading, auto-retry, configurable alert levels |
