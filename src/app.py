"""
App orchestrator — creates meters, starts threads, manages lifecycle. v2.0.0
"""

import json
import time as _time
from _thread import start_new_thread
from src.config import Config
from src.storage import Storage
from src.meter import Meter
from src.aggregator import Aggregator
from src.api_pusher import APIPusher
from src.backup import Backup
from src.logger import MainLogger, MeterLogger, check_log_size
from src.validator import DataValidator
from src.socket_server import SocketServer
from src.modbus import Modbus
from src.dSerial import DSerial
from src import VERSION
import os

class App:
    def __init__(self):
        self._closing = False
        self.config = Config('config.json')
        self.Node = self.config.getConfigVal("Node", "SAN00011")
        self.main_logger = MainLogger(self.config)

        self.main_logger.insert_Info_APP_log(f"meter-app-v2 version {VERSION} starting")

        # Alert level config: 'none', 'critical', 'warning', 'info'
        self.alert_level = self.config.getConfigVal("alert_level", "warning")
        # Map level names to numeric priority for filtering
        self._alert_priority = {"none": 0, "critical": 1, "warning": 2, "info": 3}

        # Storage (shared SQLite)
        db_path = self.config.getConfigVal("database_path", "database/")
        self.storage = Storage(db_dir=db_path, logger=self.main_logger)

        # Meters
        info_meters = self.config.getConfigVal("meters", [])
        self.meters = []

        # Auto-detect if meters list is empty (e.g. config was wiped)
        if not info_meters:
            self.main_logger.insert_Info_APP_log(
                "No meters in config — running auto-detect...")
            try:
                from src.auto_detect import detect_meters
                detected = detect_meters()
                if detected:
                    info_meters = []
                    for d in detected:
                        info_meters.append({
                            "Meter_type": d["meter_type"],
                            "MeterID": d["meter_type"].lower() + "_1",
                            "PanelID": d["meter_type"] + "_1",
                            "Serail_Port": d["port"],
                            "Serial_Baudrate": d["baudrate"],
                            "slave_id": d["slave_id"],
                            "serial": False,
                            "MQTT_topic": d["meter_type"].lower() + "_1",
                            "Node": self.Node,
                        })
                    # Save detected meters to config so we don't re-detect next time
                    self.config.setConfigVal("meters", info_meters)
                    self.main_logger.insert_Info_APP_log(
                        f"Auto-detected {len(info_meters)} meter(s), saved to config")
                else:
                    self.main_logger.insert_Error_APP_log(
                        "Auto-detect found no meters on any serial port")
            except Exception as ex:
                self.main_logger.insert_Error_APP_log(
                    f"Auto-detect failed: {ex}")

        for info in info_meters:
            meter_label = info.get("MQTT_topic", str(info.get("MeterID", "1")))
            meter_logger = MeterLogger(
                log_header=self._get_format_header(info),
                meter_type=info["Meter_type"],
                meter_label=meter_label,
                config=self.config
            )
            meter = Meter(info, self.config, self.storage, meter_logger)
            self.meters.append(meter)

        # Aggregator
        self.aggregator = Aggregator(self.storage, logger=self.main_logger)

        # Phase 3: TCP Socket Server (created early so other components can use it for alerts)
        self.socket_server = SocketServer(host="127.0.0.1", port=5555, logger=self.main_logger)
        self.socket_server.start()

        # Set up socket server callbacks
        self.socket_server._config_read_callback = self.config.read_config
        self.socket_server._config_write_callback = self.config.write_config
        self.socket_server._reload_callback = self._reload_config
        self.socket_server._ct_read_callback = self._ct_read_values
        self.socket_server._ct_write_callback = self._ct_write_value

        # API Pusher
        self.api_pusher = APIPusher(self.storage, self.config, logger=self.main_logger, socket_server=self.socket_server)
        if self.config.getConfigVal("api_push_enabled", False):
            start_new_thread(self.api_pusher.push_thread, ())
            self.main_logger.insert_Info_APP_log("API Pusher thread started")

        # Backup
        self.backup = Backup(self.storage, self.config, logger=self.main_logger)
        if self.config.getConfigVal("backup_enabled", False):
            start_new_thread(self.backup.backup_thread, ())
            self.main_logger.insert_Info_APP_log("Backup thread started")

        # Retry any previously failed sends
        self.api_pusher.retry_failed()

        # Health monitoring (Phase 1.6)
        self._last_cycle_time = _time.time()
        self._last_log_check = _time.time()
        self._log_check_interval = 3600  # 1 hour

        # Phase 2: Data validation
        self.validator = DataValidator(config=self.config, logger=self.main_logger)

        # Health: feed initial state to socket server
        self._update_health()

        self.main_logger.insert_Info_APP_log(
            f"Initialized {len(self.meters)} meter(s), ready to read")

    def _update_health(self):
        """Feed system health state to the socket server for broadcasting."""
        now_ms = _time.time() * 1000
        for meter in self.meters:
            last_ts = self.storage.get_last_1min_timestamp(
                meter.PanelID, str(meter.meter_id)
            )
            age_ms = int(now_ms - last_ts) if last_ts > 0 else -1
            meter_connected = 0 < age_ms < 10000  # within 10 seconds

            self.socket_server.set_health(
                meter_connected=meter_connected,
                meter_type=meter.meter_type,
                last_reading_age_ms=age_ms,
                push_enabled=self.api_pusher.enabled,
                last_push_success=self.api_pusher.last_push_success,
                last_push_time=self.api_pusher.last_push_time,
                pending_push_count=len(self.storage.get_pending_15min(limit=1)),
                last_push_sample=self.api_pusher.last_push_payload or {},
            )

    def _get_format_header(self, info):
        """Get LOG_HEADER from the meter's format class."""
        try:
            from src.meters_format.format import Format
            fmt = Format(info["Meter_type"])
            instance = fmt.getInstance(
                info.get("PanelID", ""),
                info.get("MeterID", "1"),
                self.Node, info
            )
            return instance.LOG_HEADER
        except Exception as ex:
            self.main_logger.insert_Error_APP_log(
                f"_get_format_header failed for {info.get('Meter_type', '?')}: {ex}")
            return ['Time', 'PanelID', 'MeterID', 'Node']

    def is_closing(self):
        self._closing = True

    def has_meters(self):
        return len(self.meters) > 0

    def try_redetect(self):
        """Try to auto-detect and add meters if none are currently configured.
        
        Called from the main loop when no meters are found.
        Scans serial ports for connected meters and initializes them.
        Returns True if at least one meter was found and added.
        """
        if self.meters:
            return True
        self.main_logger.insert_Info_APP_log(
            "No meters connected — scanning serial ports...")
        try:
            from src.auto_detect import detect_meters
            detected = detect_meters()
            if not detected:
                return False
            info_meters = []
            for d in detected:
                info_meters.append({
                    "Meter_type": d["meter_type"],
                    "MeterID": d["meter_type"].lower() + "_1",
                    "PanelID": d["meter_type"] + "_1",
                    "Serail_Port": d["port"],
                    "Serial_Baudrate": d["baudrate"],
                    "slave_id": d["slave_id"],
                    "serial": False,
                    "MQTT_topic": d["meter_type"].lower() + "_1",
                    "Node": self.Node,
                })
            # Save to config so it persists
            self.config.setConfigVal("meters", info_meters)
            # Initialize meter objects
            for info in info_meters:
                meter_label = info.get("MQTT_topic", str(info.get("MeterID", "1")))
                meter_logger = MeterLogger(
                    log_header=self._get_format_header(info),
                    meter_type=info["Meter_type"],
                    meter_label=meter_label,
                    config=self.config
                )
                meter = Meter(info, self.config, self.storage, meter_logger)
                self.meters.append(meter)
            self.main_logger.insert_Info_APP_log(
                f"Auto-detected {len(self.meters)} meter(s) on the fly")
            self._update_health()
            return True
        except Exception as ex:
            self.main_logger.insert_Error_APP_log(
                f"Redetect failed: {ex}")
            return False

    def read_data(self):
        """Poll all meters, then check for 15-min aggregation. Phase 1.4 + 1.6."""
        cycle_start = _time.time()

        # Phase 1.4: Log size monitoring (check hourly)
        if cycle_start - self._last_log_check > self._log_check_interval:
            self._last_log_check = cycle_start
            try:
                size_mb, cleaned, deleted = check_log_size()
                if size_mb > 500:
                    msg = f"Log size critical: {size_mb:.1f}MB"
                    self.main_logger.insert_Error_APP_log(msg)
                    self.socket_server.send_alert({
                        "level": "CRITICAL",
                        "meter_id": "system",
                        "meter_type": "system",
                        "message": msg
                    })
                if cleaned:
                    self.main_logger.insert_Info_APP_log(f"Log cleanup: deleted {deleted} files, size now {size_mb:.1f}MB")
            except Exception as ex:
                self.main_logger.insert_Error_APP_log(f"Log check failed: {ex}")

        # Phase 1.6: Health check timer
        expected_interval = self.get_request_time()
        elapsed = cycle_start - self._last_cycle_time
        if self._last_cycle_time > 0 and elapsed > expected_interval * 2:
            msg = f"Health warning: cycle took {elapsed:.1f}s (expected {expected_interval:.1f}s)"
            self.main_logger.insert_Error_APP_log(msg)
            self.socket_server.send_alert({
                "level": "WARNING",
                "meter_id": "system",
                "meter_type": "system",
                "message": msg
            })

        for meter in self.meters:
            if self._closing:
                break
            
            # Check if meter type changed during rescan — needs new logger
            if meter.needs_reinit:
                meter.needs_reinit = False
                self.main_logger.insert_Info_APP_log(
                    f"Meter type changed to {meter.meter_type} — reinitializing logger and config")
                try:
                    # Update config.json with new meter type
                    self.config.setConfigVal("meters", [meter.meter_info])
                    
                    # Create new logger with correct paths for the new meter type
                    new_logger = MeterLogger(
                        log_header=self._get_format_header(meter.meter_info),
                        meter_type=meter.meter_type,
                        meter_label=meter.meter_label,
                        config=self.config
                    )
                    meter.logger = new_logger
                    
                    # Recreate modbus with new logger
                    if meter.meter_info.get("serial", False):
                        meter.modbus = DSerial(meter.meterFormat, 
                            meter.meter_info["Serail_Port"], meter.meter_info["Serial_Baudrate"],
                            meter.productionMode, new_logger)
                    else:
                        meter.modbus = Modbus(meter.meterFormat,
                            meter.meter_info["Serail_Port"], meter.meter_info["Serial_Baudrate"],
                            meter.productionMode, new_logger)
                except Exception as ex:
                    self.main_logger.insert_Error_APP_log(f"Meter reinit failed: {ex}")
            
            success = meter.read_and_store()
            if success:
                # Phase 2 + 3: Validate and broadcast via socket
                self._validate_and_broadcast(meter)
                # Check for meter-level errors (energy spikes, interference, etc.)
                self._check_meter_errors(meter)
            else:
                msg = f"[{meter.meter_type}_{meter.meter_id}] read failed, will retry next cycle"
                self.main_logger.insert_Error_APP_log(msg)
                self.socket_server.send_alert({
                    "level": "ERROR",
                    "meter_id": str(meter.meter_id),
                    "meter_type": meter.meter_type,
                    "message": msg
                })

        # Check if any 15-min windows need aggregation
        if not self._closing:
            self._run_aggregation()

        # Update health state for socket broadcast
        self._update_health()

        self._last_cycle_time = _time.time()

    def _run_aggregation(self):
        """Run 15-min aggregation for all meters."""
        for meter in self.meters:
            if self._closing:
                break
            try:
                count = self.aggregator.check_and_aggregate(
                    meter.PanelID, str(meter.meter_id),
                    meter.meter_type, meter.Node,
                    meter.channel_count
                )
                if count > 0:
                    self.main_logger.insert_Info_APP_log(
                        f"[{meter.meter_type}_{meter.meter_id}] aggregated {count} 15-min window(s)")
                    # Log all pending samples for this meter to CSV
                    self._log_samples_to_csv(meter)
            except Exception as ex:
                msg = f"[{meter.meter_type}_{meter.meter_id}] aggregation error: {ex}"
                self.main_logger.insert_Error_APP_log(msg)
                self.socket_server.send_alert({
                    "level": "ERROR",
                    "meter_id": str(meter.meter_id),
                    "meter_type": meter.meter_type,
                    "message": msg
                })

    def _log_samples_to_csv(self, meter):
        """Write all pending 15-min records for this meter to the samples CSV log.
        
        Queries the database for all pending records for this specific meter
        and logs each one. Records are written to CSV at aggregation time.
        """
        try:
            import json
            records = self.storage.get_pending_15min_by_meter(
                meter.PanelID, str(meter.meter_id))
            if not records:
                return
            for rec in records:
                grid = json.loads(rec.get("grid_json", "{}"))
                totals = json.loads(rec.get("totals_json", "{}"))
                row = [
                    rec.get("datetime_str", ""),
                    rec.get("panel_id", ""),
                    rec.get("meter_id", ""),
                    rec.get("node", ""),
                    rec.get("channel_count", 0),
                    rec.get("sample_count", 0),
                    rec.get("send_status", ""),
                    grid.get("av", 0), grid.get("bv", 0), grid.get("cv", 0),
                    grid.get("v", 0), grid.get("f", 0),
                    totals.get("ti", 0), totals.get("tp", 0), totals.get("tq", 0),
                    totals.get("ts", 0), totals.get("tpf", 0),
                    totals.get("tae", 0), totals.get("tre", 0),
                    rec.get("channels_json", "")
                ]
                meter.logger.insert_samples_log(row)
        except Exception as ex:
            self.main_logger.insert_Error_APP_log(
                f"[samples_log] Failed to write: {ex}")

    def _reload_config(self):
        """Reload config.json after changes from dashboard."""
        try:
            self.config = Config('config.json')
            self.main_logger.insert_Info_APP_log("Config reloaded from disk")
            return True
        except Exception as ex:
            self.main_logger.insert_Error_APP_log(f"Config reload failed: {ex}")
            return False

    def _ct_read_values(self):
        """Read CT values from all meters via Modbus.
        
        Returns dict: {meter_id: {meter_type, channel_count, ct_values, ct_info}}
        ct_info contains meter-specific metadata (range, presets, etc.)
        """
        # Meter-specific CT register maps
        CT_SPECS = {
            "PMAC211": {
                "registers": {5018: 1, 5019: 2, 5020: 3, 5021: 4},
                "type": "range", "min": 50, "max": 600, "unit": "A",
                "presets": None,
            },
            "SPM206": {
                "registers": {
                    2202: "Ch 1-3", 2203: "Ch 4-6", 2204: "Ch 7-9",
                    2205: "Ch 10-12", 2206: "Ch 13-15", 2207: "Ch 16-18",
                    2208: "Ch 19-21", 2209: "Ch 22-24", 2210: "Ch 25-27",
                    2211: "Ch 28-30", 2212: "Ch 31-33", 2213: "Ch 34-36",
                    2214: "Ch 37-39", 2215: "Ch 40-42",
                },
                "type": "preset", "min": 0, "max": 5, "unit": "code",
                "presets": {0: "50A", 1: "100A", 2: "200A", 3: "400A", 4: "600A", 5: "25A"},
            },
            "SPM32": {
                "registers": {213: "CT Primary"},
                "type": "range", "min": 1, "max": 99999, "unit": "A",
                "presets": None,
            },
        }
        
        result = {}
        for meter in self.meters:
            if not hasattr(meter, 'modbus') or not hasattr(meter.modbus, 'client'):
                continue
            try:
                client = meter.modbus.client
                mtype = getattr(meter, 'meter_type', 'PMAC211')
                spec = CT_SPECS.get(mtype, CT_SPECS["PMAC211"])
                ct_registers = spec["registers"]
                
                # Try bulk read first (only for PMAC211 with contiguous addresses)
                ct_values = {}
                if mtype == "PMAC211":
                    try:
                        wire_addrs = [addr - 1 for addr in ct_registers.keys()]
                        res = client.read_holding_registers(wire_addrs[0], 4, unit=1)
                        if not res.isError() and len(res.registers) == 4:
                            for i, (manual_addr, ch_num) in enumerate(ct_registers.items()):
                                ct_values[ch_num] = res.registers[i]
                        else:
                            raise Exception('Bulk read failed')
                    except Exception:
                        # Fallback: one-by-one
                        for reg_addr, ch_num in ct_registers.items():
                            try:
                                wire_addr = reg_addr - 1
                                val = client.read_holding_registers(wire_addr, 1, unit=1)
                                ct_values[ch_num] = val.registers[0] if not val.isError() and val.registers else 0
                            except Exception:
                                ct_values[ch_num] = 0
                else:
                    # For SPM206/SPM32, always read one-by-one
                    for reg_addr, label in ct_registers.items():
                        try:
                            wire_addr = reg_addr - 1
                            val = client.read_holding_registers(wire_addr, 1, unit=1)
                            raw = val.registers[0] if not val.isError() and val.registers else 0
                            # SPM206: convert preset code (0-5) to amperes for mobile app
                            if mtype == "SPM206" and spec.get("presets"):
                                # presets = {0: "50A", 1: "100A", ...} — code→label
                                # Build reverse map: code→amps  e.g. {0: 50, 1: 100, ...}
                                code_to_amp = {code: int(label.rstrip('A')) for code, label in spec["presets"].items()}
                                ct_values[str(label)] = code_to_amp.get(raw, raw)
                            else:
                                ct_values[str(label)] = raw
                        except Exception:
                            ct_values[str(label)] = 0
                
                result[str(meter.meter_id)] = {
                    "meter_type": mtype,
                    "channel_count": getattr(meter, 'channel_count', 0),
                    "ct_values": ct_values,
                    "ct_info": {
                        "type": spec["type"],
                        "min": spec["min"],
                        "max": spec["max"],
                        "unit": spec["unit"],
                        "presets": spec["presets"],
                    }
                }
                self.main_logger.insert_Info_APP_log(f'CT read {mtype}: {ct_values}')
            except Exception as ex:
                self.main_logger.insert_Error_APP_log(f"CT read failed for meter {meter.meter_id}: {ex}")
                result[str(meter.meter_id)] = {"error": str(ex)}
        
        return result

    def _ct_write_value(self, params):
        """Write CT value(s) to a meter via Modbus.
        
        Supports two formats:
        1. Single: {"meter_id": "1", "channel": 1, "value": 200}
        2. Batch:  {"1": {"1": 200, "2": 100}}  (meter_id → channel → value)
        
        Returns True if all writes succeed.
        """
        # Detect batch format: if first non-reserved key maps to a dict, it's batch
        reserved_keys = {"meter_id", "channel", "value", "requestId", "type"}
        is_batch = any(k not in reserved_keys and isinstance(v, dict) for k, v in params.items())
        
        if is_batch:
            all_ok = True
            for meter_id, channels in params.items():
                if meter_id in reserved_keys or not isinstance(channels, dict):
                    continue
                for channel_key, value in channels.items():
                    # channel_key can be int (1,2,3...) or string ("Ch 1-3", "CT Primary")
                    # _ct_write_single handles both via reg_keys index lookup
                    ok = self._ct_write_single(meter_id, channel_key, value)
                    if not ok:
                        all_ok = False
            return all_ok
        else:
            # Single write format
            meter_id = params.get("meter_id", "1")
            channel = params.get("channel", 1)
            value = params.get("value", 0)
            return self._ct_write_single(meter_id, channel, value)
    
    def _ct_write_single(self, meter_id, channel, value):
        """Write a single CT channel value to a meter."""
        # Meter-specific CT write configs
        CT_WRITE_SPECS = {
            "PMAC211": {
                "registers": {1: 5018, 2: 5019, 3: 5020, 4: 5021},
                "validate": lambda v: 50 <= v <= 600,
                "unit": "A",
            },
            "SPM206": {
                "registers": {
                    'Ch 1-3': 2202, 'Ch 4-6': 2203, 'Ch 7-9': 2204,
                    'Ch 10-12': 2205, 'Ch 13-15': 2206, 'Ch 16-18': 2207,
                    'Ch 19-21': 2208, 'Ch 22-24': 2209, 'Ch 25-27': 2210,
                    'Ch 28-30': 2211, 'Ch 31-33': 2212, 'Ch 34-36': 2213,
                    'Ch 37-39': 2214, 'Ch 40-42': 2215,
                },
                "amp_to_code": {50: 0, 100: 1, 200: 2, 400: 3, 600: 4, 25: 5},
                "validate": lambda v: v in {50, 100, 200, 400, 600, 25},
                "unit": "A",
            },
            "SPM32": {
                "registers": {"CT Primary": 213},
                "validate": lambda v: 1 <= v <= 99999,
                "unit": "A",
            },
        }
        
        for meter in self.meters:
            if str(meter.meter_id) != str(meter_id):
                continue
            if not hasattr(meter, 'modbus') or not hasattr(meter.modbus, 'client'):
                self.main_logger.insert_Error_APP_log(f"Meter {meter_id} has no modbus client")
                return False
            try:
                client = meter.modbus.client
                mtype = getattr(meter, 'meter_type', 'PMAC211')
                spec = CT_WRITE_SPECS.get(mtype, CT_WRITE_SPECS['PMAC211'])
                
                # Resolve register address based on channel
                ct_registers = spec['registers']
                reg_keys = list(ct_registers.keys())
                
                # BLE sends integer keys (1, 2, 3...) but register keys may be
                # labels ("CT Primary", "Ch 1-3") or integers (PMAC211: 1,2,3,4)
                reg_addr = ct_registers.get(channel)
                if reg_addr is None and str(channel).isdigit():
                    ch_int = int(channel)
                    if 1 <= ch_int <= len(reg_keys):
                        reg_addr = ct_registers[reg_keys[ch_int - 1]]
                if reg_addr is None:
                    reg_addr = ct_registers.get(str(channel))
                
                if reg_addr is None:
                    self.main_logger.insert_Error_APP_log(f"Invalid channel {channel} for meter {meter_id} ({mtype})")
                    return False
                
                value = int(value)
                
                # SPM206: accept both preset codes (0-5) and amperes (25,50,100,200,400,600)
                write_value = value
                if mtype == 'SPM206' and 'amp_to_code' in spec:
                    code_to_amp = {code: amp for amp, code in spec['amp_to_code'].items()}
                    if value in code_to_amp:
                        # Value is a preset code (0-5) — convert to amperes for validation
                        value = code_to_amp[value]
                    if value in spec['amp_to_code']:
                        write_value = spec['amp_to_code'][value]
                    else:
                        self.main_logger.insert_Error_APP_log(f"SPM206: {value} is not a valid ampere value or preset code")
                        return False
                elif not spec['validate'](value):
                    self.main_logger.insert_Error_APP_log(f"CT value {value} out of range for {mtype} channel {channel}")
                    return False
                
                wire_addr = reg_addr - 1
                _time.sleep(0.1)
                res = client.write_register(wire_addr, write_value, unit=1)
                # pymodbus returns an error response object (no exception) if the
                # meter rejects the write — check isError() before declaring success.
                if res is not None and hasattr(res, 'isError') and res.isError():
                    # FC06 rejected — try FC16 (write multiple registers) as fallback
                    fc06_error = str(res)
                    self.main_logger.insert_Info_APP_log(
                        f"FC06 write_register failed ({fc06_error}), retrying with FC16 write_registers...")
                    _time.sleep(0.2)
                    res = client.write_registers(wire_addr, [write_value], unit=1)
                    if res is not None and hasattr(res, 'isError') and res.isError():
                        self.main_logger.insert_Error_APP_log(
                            f"CT write rejected by meter: FC06={fc06_error}, FC16={res} (meter {meter_id}, ch={channel}, reg={reg_addr})")
                        return False

                # Verify by reading back the register
                _time.sleep(0.2)
                verify = client.read_holding_registers(wire_addr, 1, unit=1)
                if verify.isError() or not verify.registers:
                    self.main_logger.insert_Error_APP_log(
                        f"CT write verify read failed for meter {meter_id} ch={channel}")
                    return False
                actual = verify.registers[0]
                if actual != write_value:
                    self.main_logger.insert_Error_APP_log(
                        f"CT write verify mismatch: wrote {write_value} to reg {reg_addr}, "
                        f"read back {actual} (meter {meter_id} ch={channel})")
                    return False

                self.main_logger.insert_Info_APP_log(f"CT written: meter {meter_id} ({mtype}) ch={channel} (reg {reg_addr}, wire {wire_addr}) = {value}A (code={write_value})")
                # Persist CT rate to config.json
                self._save_ct_rate_to_config(meter_id, channel, value)
                return True
            except Exception as ex:
                self.main_logger.insert_Error_APP_log(f"CT write failed: {ex}")
                return False
        
        return False

    def _save_ct_rate_to_config(self, meter_id, channel, value):
        """Save CT rate to meter-app-v2 config.json after successful Modbus write."""
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
            with open(config_path, "r") as f:
                cfg = json.load(f)
            
            for meter_cfg in cfg.get("meters", []):
                if str(meter_cfg.get("MeterID")) == str(meter_id):
                    if "ct_rates" not in meter_cfg:
                        meter_cfg["ct_rates"] = {}
                    meter_cfg["ct_rates"][str(channel)] = int(value)
                    break
            
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=4)
            self.main_logger.insert_Info_APP_log(f"CT rate saved to config: meter {meter_id} ch={channel} = {value}")
        except Exception as ex:
            self.main_logger.insert_Error_APP_log(f"Failed to save CT rate to config: {ex}")

    def get_request_time(self):
        """Returns polling interval in seconds."""
        return self.config.getConfigVal("request_time", 1) * 60

    def _validate_and_broadcast(self, meter):
        """Phase 2+3: Validate meter data and broadcast via TCP socket."""
        try:
            # Get the last stored reading from SQLite for validation
            last_readings = self.storage.get_1min_range(
                meter.PanelID, str(meter.meter_id),
                _time.time() * 1000 - 120000,  # last 2 minutes
                _time.time() * 1000
            )
            if not last_readings:
                return

            current_data = last_readings[-1]
            prev_data = last_readings[-2] if len(last_readings) > 1 else None
            expected_interval_ms = self.get_request_time() * 1000

            # Validate
            result = self.validator.validate(
                current_data, str(meter.meter_id), expected_interval_ms
            )

            # Store validation in SQLite
            self.storage.insert_validation(
                result.timestamp_ms, str(meter.meter_id),
                result.overall, result.checks, result.confidence, result.issues
            )

            # Broadcast reading via TCP socket
            self.socket_server.send_reading({
                "timestamp": current_data.get("time", 0),
                "meter_id": str(meter.meter_id),
                "meter_type": meter.meter_type,
                "panel_id": meter.PanelID,
                "node": meter.Node,
                "data": current_data,
            })

            # Broadcast validation via TCP socket (with cloud push status)
            validation_data = result.to_dict()
            validation_data["cloud_push"] = self.api_pusher.last_push_success
            push_age = -1
            if self.api_pusher.last_push_time:
                push_age = int(_time.time() * 1000 - self.api_pusher.last_push_time * 1000)
            validation_data["cloud_push_age_ms"] = push_age
            self.socket_server.send_validation(validation_data)

            # Send critical alert if validation failed
            if result.overall == "CRITICAL":
                self.socket_server.send_alert({
                    "level": "CRITICAL",
                    "meter_id": str(meter.meter_id),
                    "meter_type": meter.meter_type,
                    "message": f"Validation CRITICAL: {'; '.join(result.issues[:3])}",
                    "issues": result.issues,
                })

        except Exception as ex:
            self.main_logger.insert_Error_APP_log(f"Validation/broadcast error: {ex}")

    def _check_meter_errors(self, meter):
        """Check for errors collected during Modbus read and send as alerts.
        
        Errors include: energy spikes, data interference, low voltage, read failures.
        Each error is sent to the hub-agent via TCP socket which forwards to server.
        Respects alert_level config to filter which alerts are sent.
        """
        try:
            if not hasattr(meter, 'modbus') or not hasattr(meter.modbus, 'get_and_clear_errors'):
                return
            errors = meter.modbus.get_and_clear_errors()
            for err in errors:
                alert_level = err.get("level", "ERROR")
                # Map ERROR to critical, WARNING to warning, INFO to info
                mapped = "critical" if alert_level in ("ERROR", "CRITICAL") else "warning" if alert_level == "WARNING" else "info"
                priority = self._alert_priority.get(mapped, 3)
                max_priority = self._alert_priority.get(self.alert_level, 2)
                if priority <= max_priority:
                    self.socket_server.send_alert({
                        "level": alert_level,
                        "meter_id": str(meter.meter_id),
                        "meter_type": meter.meter_type,
                        "source": err.get("source", "meter-app"),
                        "message": err.get("message", "Unknown meter error"),
                    })
        except Exception as ex:
            self.main_logger.insert_Error_APP_log(f"Error checking meter errors: {ex}")

    def close(self):
        """Graceful shutdown."""
        self.main_logger.insert_Info_APP_log("Shutting down...")
        self.socket_server.stop()
        self.api_pusher.stop()
        self.backup.stop()
        for meter in self.meters:
            meter.close()
        self.storage.close()
        self.main_logger.insert_Info_APP_log("Shutdown complete")
