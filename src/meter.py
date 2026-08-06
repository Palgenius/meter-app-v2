"""
Meter reader — reads, decodes, normalizes, stores, logs. v2.0.0

One Meter instance per physical meter. Called from the main loop.
"""

import time
import threading
from src.meters_format.format import Format
from src.modbus import Modbus
from src.dSerial import DSerial
from src.normalizer import normalize
from src.auto_detect import rescan_for_meter, detect_any_meter

MAX_READ_FAILURES = 3  # consecutive failures before rescan
READ_TIMEOUT = 30  # seconds — kill grapData if it hangs
RESCAN_TIMEOUT = 120  # seconds — kill rescan if it takes too long
SIGNATURE_TIMEOUT = 15  # seconds — kill signature check if it hangs


class Meter:
    def __init__(self, info, config, storage, logger):
        self.lastReadingTime = 0
        self.exiting = False
        self.meter_type = info["Meter_type"]
        self.meter_id = info["MeterID"]
        self.PanelID = info["PanelID"]
        self.meter_label = info.get("MQTT_topic", str(self.meter_id))

        self.productionMode = config.getConfigVal("productionMode", True)
        self.Node = config.getConfigVal("Node", "SAN00011")
        self.version = config.getConfigVal("version", "2.0.0")
        self.meterFormat = Format(self.meter_type).getInstance(self.PanelID, self.meter_id, self.Node, info)
        self.logger = logger
        self.storage = storage
        self.channel_count = 0  # set after first normalize
        self.consecutive_failures = 0  # track read failures for rescan
        self.needs_reinit = False  # set True when meter type changes (app.py will recreate)

        # Meter signature registers: read ONE register before each data read
        # to verify we're talking to the correct meter type (hot swap detection).
        # All baud rate registers return CODES not actual values — use CT/config
        # registers instead, matching the auto-detect probes that already work.
        self._signature = {
            "PMAC211": {"wire_addr": 5017, "min": 50, "max": 600},  # CT register (probe: addr 5017, 50-600)
            "SPM32":   {"wire_addr": 212,  "min": 1, "max": 99999}, # CTRatio (probe: addr 212, 1-99999)
            "SPM206":  {"wire_addr": 2201, "min": 0, "max": 5},     # CT preset (probe: addr 2201, 0-5)
        }

        self.meter_info = info  # save for port/baud info during rescan
        if info.get("serial", False):
            self.modbus = DSerial(self.meterFormat, info["Serail_Port"], info["Serial_Baudrate"],
                                  self.productionMode, self.logger)
        else:
            self.modbus = Modbus(self.meterFormat, info["Serail_Port"], info["Serial_Baudrate"],
                                 self.productionMode, self.logger)

    def close(self):
        """Graceful shutdown — close serial/modbus connection."""
        self.modbus.closeConnection()

    def _try_rescan(self):
        """Attempt to re-detect this meter on any available port.
        
        Called after MAX_READ_FAILURES consecutive read failures.
        First tries to find the same meter type on any port.
        If not found, detects ANY meter type and reconfigures.
        
        Runs the scan in a background thread with RESCAN_TIMEOUT to prevent
        blocking the main loop indefinitely.
        """
        known_port = self.meter_info.get("Serail_Port")
        self.logger.insert_Info_APP_log(
            f"[{self.meter_type}_{self.meter_id}] Rescanning for {self.meter_type} (last known: {known_port})")
        
        # Close old connection
        try:
            self.modbus.closeConnection()
        except Exception:
            pass
        
        # Run scan in a thread with timeout to prevent blocking the main loop
        result = [None]
        def _scan():
            try:
                # Try 1: Find the same meter type on any port
                detection = rescan_for_meter(self.meter_type, known_port)
                # Try 2: If not found, detect ANY meter type
                if not detection:
                    self.logger.insert_Info_APP_log(
                        f"[{self.meter_type}_{self.meter_id}] {self.meter_type} not found — scanning for any meter...")
                    detection = detect_any_meter(known_port)
                result[0] = detection
            except Exception as ex:
                self.logger.insert_Error_APP_log(
                    f"[{self.meter_type}_{self.meter_id}] Rescan exception: {ex}")
                result[0] = None
        
        scan_thread = threading.Thread(target=_scan, daemon=True)
        scan_thread.start()
        scan_thread.join(timeout=RESCAN_TIMEOUT)
        
        if scan_thread.is_alive():
            # Scan took too longer — abandon and reconnect to known port
            self.logger.insert_Error_APP_log(
                f"[{self.meter_type}_{self.meter_id}] Rescan timed out after {RESCAN_TIMEOUT}s — "
                f"reconnecting to known port {known_port}")
            self._reconnect_to_port(known_port)
            return
        
        detection = result[0]
        
        if detection:
            new_port = detection["port"]
            new_baud = detection["baudrate"]
            new_type = detection["meter_type"]
            
            if new_type != self.meter_type:
                # Different meter type — reconfigure everything!
                self.logger.insert_Info_APP_log(
                    f"[{self.meter_type}_{self.meter_id}] Meter changed! {self.meter_type} → {new_type} on {new_port}")
                self.meter_type = new_type
                self.meter_info["Meter_type"] = new_type
                self.meter_info["MQTT_topic"] = new_type.lower() + "_1"
                self.meter_label = self.meter_info["MQTT_topic"]
                
                # Create new format instance
                from src.meters_format.format import Format
                self.meterFormat = Format(new_type).getInstance(
                    self.PanelID, self.meter_id, self.Node, self.meter_info)
                
                # Signal app.py to recreate this meter with a new logger
                self.needs_reinit = True
            else:
                self.logger.insert_Info_APP_log(
                    f"[{self.meter_type}_{self.meter_id}] Found on {new_port} @ {new_baud} baud")
            
            # Update meter info and recreate Modbus client
            self.meter_info["Serail_Port"] = new_port
            self.meter_info["Serial_Baudrate"] = new_baud
            if self.meter_info.get("serial", False):
                self.modbus = DSerial(self.meterFormat, new_port, new_baud,
                                      self.productionMode, self.logger)
            else:
                self.modbus = Modbus(self.meterFormat, new_port, new_baud,
                                     self.productionMode, self.logger)
            self.consecutive_failures = 0
        else:
            self.logger.insert_Error_APP_log(
                f"[{self.meter_type}_{self.meter_id}] Rescan failed — no meter found on any port")
            self._reconnect_to_port(known_port)
    
    def _reconnect_to_port(self, port):
        """Reconnect to a specific port, non-blocking."""
        try:
            if self.meter_info.get("serial", False):
                self.modbus = DSerial(self.meterFormat, port,
                                      self.meter_info["Serial_Baudrate"],
                                      self.productionMode, self.logger)
            else:
                self.modbus = Modbus(self.meterFormat, port,
                                     self.meter_info["Serial_Baudrate"],
                                     self.productionMode, self.logger)
        except Exception as ex:
            self.logger.insert_Error_APP_log(
                f"[{self.meter_type}_{self.meter_id}] Reconnect to {port} failed: {ex}")
        self.consecutive_failures = 0

    @staticmethod
    def _sig_matches(sig, val):
        """Check if register value matches a signature (exact or range)."""
        if "expected" in sig:
            return val == sig["expected"]
        if "min" in sig and "max" in sig:
            return sig["min"] <= val <= sig["max"]
        return False

    def _check_meter_signature(self):
        """Fast check: read one signature register to verify the connected meter.
        
        Returns True if the meter matches, False if it has been swapped.
        Supports two signature formats:
        - exact: {"wire_addr": N, "expected": V}  — value must equal V
        - range:  {"wire_addr": N, "min": A, "max": B}  — value must be in [A..B]
        
        On first failure, reconnects and retries once before triggering rescan.
        Runs in a thread with SIGNATURE_TIMEOUT to prevent blocking the main loop.
        """
        if not hasattr(self.modbus, 'client'):
            return True  # can't check, assume OK
        
        expected_type = self.meter_type
        sig = self._signature.get(expected_type)
        if not sig:
            return True  # unknown type, skip check
        
        # Run signature check in a thread with timeout.
        # IMPORTANT: Do NOT call _try_rescan() from inside this thread —
        # rescan can take 120s which exceeds SIGNATURE_TIMEOUT (15s),
        # causing a race condition. Just return False and let
        # read_and_store() handle rescan via the failure counter.
        result = [None]  # True/False/None(timeout)
        def _check():
            try:
                for attempt in range(2):
                    client = self.modbus.client if hasattr(self.modbus, 'client') else None
                    if client is None:
                        result[0] = True
                        return
                    time.sleep(0.1)
                    res = client.read_holding_registers(sig["wire_addr"], 1, unit=1)
                    if res.isError() or not res.registers:
                        if attempt == 0:
                            self.logger.insert_Info_APP_log(
                                f"[{self.meter_type}_{self.meter_id}] Signature read failed — "
                                f"reconnecting and retrying...")
                            if hasattr(self.modbus, 'reconnect'):
                                self.modbus.reconnect()
                            continue
                        # Second failure — return False, read_and_store will handle rescan
                        self.logger.insert_Info_APP_log(
                            f"[{self.meter_type}_{self.meter_id}] Signature read failed after retry")
                        result[0] = False
                        return
                    
                    val = res.registers[0]
                    if self._sig_matches(sig, val):
                        result[0] = True
                        return
                    
                    # Wrong value — return False (let failure counter handle rescan)
                    self.logger.insert_Info_APP_log(
                        f"[{self.meter_type}_{self.meter_id}] Signature mismatch (val={val})")
                    result[0] = False
                    return
            except Exception:
                # On exception, reconnect but don't rescan (let failure counter handle it)
                try:
                    if hasattr(self.modbus, 'reconnect'):
                        self.modbus.reconnect()
                except Exception:
                    pass
                result[0] = False  # return False so failure counter increments
        
        check_thread = threading.Thread(target=_check, daemon=True)
        check_thread.start()
        check_thread.join(timeout=SIGNATURE_TIMEOUT)
        
        if check_thread.is_alive():
            # Signature check hung — skip it and proceed to read
            self.logger.insert_Error_APP_log(
                f"[{self.meter_type}_{self.meter_id}] Signature check timed out after {SIGNATURE_TIMEOUT}s — skipping")
            return True  # proceed with read attempt
        
        return result[0] if result[0] is not None else True

    def read_and_store(self):
        """Read meter, normalize, store 1-min, log. Returns True on success."""
        self.logger.insert_Info_APP_log(f"Reading meter [{self.meter_type}_{self.meter_id}] ..")

        # Fast signature check before reading data — verifies we're talking
        # to the correct meter type. If swapped, immediately reconfigures.
        if not self._check_meter_signature():
            return False  # meter was swapped, will reconfigure on next read

        # Phase 1.6: Wrap grapData with timeout
        result = [None]
        def _read():
            result[0] = self.modbus.grapData()
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=READ_TIMEOUT)

        if t.is_alive():
            # grapData hung — port stuck, force reconnect
            self.consecutive_failures += 1
            self.logger.insert_Error_APP_log(
                f"[{self.meter_type}_{self.meter_id}] Read timed out after {READ_TIMEOUT}s (port stuck)")
            try:
                self.modbus.closeConnection()
            except Exception:
                pass
            self._try_rescan()
            return False

        data = result[0]
        if not data:
            self.consecutive_failures += 1
            self.logger.insert_Error_APP_log(
                f"[{self.meter_type}_{self.meter_id}] ERROR: no data (failure #{self.consecutive_failures})")
            
            # Trigger rescan after N consecutive failures
            if self.consecutive_failures >= MAX_READ_FAILURES:
                self.logger.insert_Error_APP_log(
                    f"[{self.meter_type}_{self.meter_id}] {self.consecutive_failures} consecutive failures — triggering rescan")
                self._try_rescan()
            return False

        # Successful read — reset failure counter
        self.consecutive_failures = 0
        data['version'] = self.version

        # Split into sub-intervals if we missed readings (>10 min gap)
        packets = self._divide_to_quarters(data)

        for packet in packets:
            # Normalize channels (PMAC211 flatten, others pass-through)
            normalized, ch_count = normalize(packet, self.meter_type)
            self.channel_count = ch_count

            # Store in SQLite
            timestamp_ms = normalized.get('time', int(time.time() * 1000))
            self.storage.insert_1min(
                self.PanelID, str(self.meter_id), self.meter_type,
                self.Node, timestamp_ms, normalized
            )

            # Log to 1-min CSV — skip first 2 columns (sendingDate, level) auto-filled by csv_logger
            # Header is UPPERCASE (AV, BV, C1I, ...) but normalizer outputs lowercase (av, bv, c1i, ...)
            # Build a lowercase lookup so we match regardless of case
            norm_lower = {k.lower(): v for k, v in normalized.items()}
            header_keys = self.logger.readings_header[2:]  # skip 'sendingDate', 'level'
            log_values = [norm_lower.get(h.lower(), '') for h in header_keys]
            self.logger.insert_readings_log(log_values)

            self.logger.insert_Info_APP_log(
                f"[{self.meter_type}_{self.meter_id}] data stored, ts={timestamp_ms}")

        return True

    def _divide_to_quarters(self, data):
        """If gap between polls exceeds 10 minutes, interpolate into 5-min windows.
        
        Same logic as v1 meter.py divideToQuarters.
        """
        def make_row(rowtime, divider_time, interval, times=1):
            row = {}
            for key, val in data.items():
                if 're' in key and val > 0:
                    row[key] = round(data[key] / divider_time * times, 4)
                    ae = key.replace('re', 'ae')
                    row[ae] = round(data[ae] / divider_time * times, 4)

                    p = key.replace('re', 'p')
                    row[p] = round(row[ae] * (60 / interval), 4)
                    q = key.replace('re', 'q')
                    row[q] = round(row[key] * (60 / interval), 4)

                    pf = key.replace('re', 'pf')
                    s = key.replace('re', 's')
                    if pf in row and p in row:
                        row[s] = round(row[pf] * row[p], 4)
                    else:
                        row[s] = 0.0

                    i_key = key.replace('re', 'i')
                    v_key = key.replace('re', 'v')
                    try:
                        v_val = data[v_key] if v_key in data else (data[s] * 1000) / data[i_key]
                        row[i_key] = round((row[s] * 1000) / v_val, 4)
                    except ZeroDivisionError:
                        row[i_key] = 0.0
                else:
                    row[key] = data[key]

            row['time'] = int(self.lastReadingTime + (rowtime * 60 * 1000))
            return row

        packets = [data]
        currentTime = int(time.time() * 1000)

        if self.lastReadingTime != 0 and currentTime - self.lastReadingTime > 60 * 10000:
            packets = []
            interval = 5
            divider_time = (currentTime - self.lastReadingTime) / (1000 * 60 * interval)
            iterator = int(divider_time) - 1

            for i in range(iterator):
                row = make_row(interval * (i + 1), divider_time, interval)
                packets.append(row)

            packets.append(make_row(
                divider_time * interval, divider_time,
                (divider_time - iterator) * interval,
                times=divider_time - iterator
            ))

        self.lastReadingTime = currentTime
        return packets

    def close(self):
        self.exiting = True
        self.modbus.closeConnection()
