"""
Auto-detect meter types on serial ports via pymodbus.
=====================================================
Scans available ports, tries baud rates, reads signature registers
to identify connected meter types. Used at startup (when meters list
is empty) and at runtime (when a meter becomes unresponsive).

Supported meters: SPM32, PMAC211, PMAC202, SPM206, SMP20
KITT (serial JSON) cannot be auto-detected via Modbus.
"""

import time
import logging
import threading

from pymodbus.client.sync import ModbusSerialClient as ModbusClient

try:
    import serial.tools.list_ports
    import serial as _serial
except ImportError:
    serial = None
    _serial = None

# ── Constants ──────────────────────────────────────────────────

SCAN_BAUDS = [9600, 19200, 4800, 2400]
RETRY_DELAY = 0.2       # seconds between Modbus reads (RS485 timing)
READ_TIMEOUT = 0.8      # serial timeout for scanning (longer than normal)
PROBE_TIMEOUT = 0.3     # fast timeout for initial port check
PORT_OPEN_TIMEOUT = 2.0 # max seconds to wait for port open (blocks on Windows)

# ── Meter signature definitions ────────────────────────────────
# Each entry defines how to identify one meter type:
#   baudrates   – list of baud rates to try
#   slave_ids   – list of slave IDs to try
#   probe       – list of (address, count) tuples to attempt reading
#   identify    – function(client) → bool  (True if meter matches)
#   ct_register – address of first CT register (for display)
#   ct_range    – (min, max) valid CT values (for range-type meters)
#   ct_presets  – dict of valid preset codes (for preset-type meters)

def _probe_spm32(client):
    """Read SPM32 CTRatio register (wire addr 212) and PTRatio (wire addr 42).
    
    CTRatio (addr 212) must be 1..99999.
    PTRatio (addr 42) must be > 100 (SPM32 has large PT ratio).
    This distinguishes SPM32 from PMAC202 where addr 42 is VTHDc (small).
    """
    try:
        result = client.read_holding_registers(address=212, count=1, unit=1)
        if result.isError():
            return False
        ct = result.registers[0]
        if not (1 <= ct <= 99999):
            return False
        # Check PTRatio at wire addr 42 — should be large for SPM32 (2000-10000)
        result2 = client.read_holding_registers(address=42, count=1, unit=1)
        if result2.isError():
            return False
        pt = result2.registers[0]
        return pt > 100
    except Exception:
        return False

def _probe_pmac211(client):
    """Read Circuit 1 CT register (wire addr 5017) — must be 50..600."""
    try:
        result = client.read_holding_registers(address=5017, count=1, unit=1)
        if result.isError():
            return False
        val = result.registers[0]
        return 50 <= val <= 600
    except Exception:
        return False

def _probe_pmac202(client):
    """Distinguish PMAC202 from SPM32.
    
    Both have data at addr 0..59, but:
    - SPM32: addr 41=CTRatio, addr 42=PTRatio (large, e.g. 2300)
    - PMAC202: addr 41=VTHDb, addr 42=VTHDc (small, typically < 100)
    
    So check: addr 42 < 1000 to exclude SPM32 where PTRatio is large.
    Also check the frequency register (wire addr 37 for PMAC202) is in range.
    """
    try:
        result = client.read_holding_registers(address=0, count=60, unit=1)
        if result.isError():
            return False
        regs = result.registers
        if len(regs) < 43:
            return False
        # AV (wire addr 0) should be > 100
        if regs[0] <= 100:
            return False
        # addr 42 (VTHDc for PMAC202 / PTRatio for SPM32) must be < 1000
        # SPM32 PTRatio is typically 2000-10000, PMAC202 VTHDc is typically 0-500
        if regs[42] >= 1000:
            return False
        # addr 41 (VTHDb) should also be small for PMAC202
        if regs[41] >= 1000:
            return False
        return True
    except Exception:
        return False

def _probe_spm206(client):
    """Read Group 1 CT register (wire addr 2201) — must be 0..5 (preset code)."""
    try:
        result = client.read_holding_registers(address=2201, count=1, unit=1)
        if result.isError():
            return False
        val = result.registers[0]
        return val in (0, 1, 2, 3, 4, 5)
    except Exception:
        return False

def _probe_smp20(client):
    """Read first register (wire addr 0) — AV raw value should be >100.
    Then read register 10 (wire addr 9) for frequency which should be ~5000."""
    try:
        result = client.read_holding_registers(address=0, count=11, unit=1)
        if result.isError():
            return False
        regs = result.registers
        if len(regs) < 11:
            return False
        # AV raw (position 0) should be >100
        if regs[0] <= 100:
            return False
        # F raw (position 10, wire addr 9) should be ~4800-5200
        if 4800 <= regs[10] <= 5200:
            return True
        return False
    except Exception:
        return False

# NOTE: Order matters — more specific probes first, SPM32 last (broadest range)
METER_SIGNATURES = [
    {
        "type": "PMAC211",
        "baudrates": [9600],
        "slave_ids": [1],
        "probe": _probe_pmac211,
        "description": "PMAC211 multi-circuit power meter",
    },
    {
        "type": "PMAC202",
        "baudrates": [9600],
        "slave_ids": [1],
        "probe": _probe_pmac202,
        "description": "PMAC202 multi-circuit power meter (42 CTs)",
    },
    {
        "type": "SPM206",
        "baudrates": [19200],
        "slave_ids": [1],
        "probe": _probe_spm206,
        "description": "Pilot SPM206-54 branch-circuit power meter",
    },
    {
        "type": "SMP20",
        "baudrates": [9600],
        "slave_ids": [1],
        "probe": _probe_smp20,
        "description": "SMP20 / SPM20 multi-circuit power meter (30 CTs)",
    },
    {
        "type": "SPM32",
        "baudrates": [9600],
        "slave_ids": [1],
        "probe": _probe_spm32,
        "description": "Pilot SPM32 single-circuit power meter",
    },
]


# ── Serial port scanning ──────────────────────────────────────

def scan_ports():
    """Return list of available serial port device names."""
    ports = []
    if serial is None:
        return ports
    try:
        ports = [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        pass
    return ports


def _validate_port(port):
    """Fast check: can we open this port without blocking?
    
    Uses a thread with timeout to catch Bluetooth/virtual ports that hang.
    Returns True if the port can be opened, False otherwise.
    """
    if _serial is None:
        return True  # can't validate, assume OK
    result = [None]
    def _try_open():
        try:
            s = _serial.Serial(port, timeout=0.1)
            s.close()
            result[0] = True
        except Exception:
            result[0] = False
    t = threading.Thread(target=_try_open, daemon=True)
    t.start()
    t.join(timeout=PORT_OPEN_TIMEOUT)
    if t.is_alive():
        # Thread is stuck — port blocks on open (Bluetooth, etc.)
        return False
    return result[0] is True


# ── Core detection ─────────────────────────────────────────────

def _create_client(port, baudrate, slave_id, timeout=READ_TIMEOUT):
    """Create a pymodbus ModbusSerialClient for scanning."""
    client = ModbusClient(
        method='rtu',
        port=port,
        baudrate=baudrate,
        stopbits=1,
        parity='N',
        bytesize=8,
        timeout=timeout,
    )
    return client


def _test_meter(port, baudrate, slave_id, signature):
    """Try to identify a specific meter type on a port.
    
    Uses threading to prevent blocking on problematic ports.
    Returns dict with detection info or None.
    """
    result = [None]

    def _probe():
        client = _create_client(port, baudrate, slave_id)
        try:
            if not client.connect():
                return
            time.sleep(RETRY_DELAY)
            if signature["probe"](client):
                result[0] = {
                    "port": port,
                    "baudrate": baudrate,
                    "slave_id": slave_id,
                    "meter_type": signature["type"],
                    "description": signature["description"],
                }
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout=PORT_OPEN_TIMEOUT)
    return result[0]


def _port_has_modbus(port, baudrate, slave_id=1, timeout=PROBE_TIMEOUT):
    """Fast check: can we read ANY register from this port?
    
    Returns True if a Modbus device responds, False otherwise.
    Uses threading to prevent blocking on problematic ports.
    """
    result = [False]

    def _probe():
        client = _create_client(port, baudrate, slave_id, timeout=timeout)
        try:
            if not client.connect():
                return
            time.sleep(RETRY_DELAY)
            r = client.read_holding_registers(address=0, count=1, unit=slave_id)
            result[0] = not r.isError() or hasattr(r, 'registers')
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout=PORT_OPEN_TIMEOUT)
    return result[0]


def detect_meters(ports=None, baudrates=None, slave_ids=None):
    """Scan serial ports and identify connected meters.
    
    Args:
        ports: List of port paths to scan (None = auto-detect)
        baudrates: List of baud rates to try (None = SCAN_BAUDS)
        slave_ids: List of slave IDs to try (None = [1])
    
    Returns:
        list of dicts: [{"port", "baudrate", "slave_id", "meter_type", "description"}, ...]
    """
    if ports is None:
        ports = scan_ports()
    if baudrates is None:
        baudrates = SCAN_BAUDS
    if slave_ids is None:
        slave_ids = [1]

    if not ports:
        return []

    results = []
    found_ports = set()  # track which port+slave combos we already found

    for port in ports:
        # Skip ports that can't be opened (Bluetooth, virtual, etc.)
        if not _validate_port(port):
            continue

        for slave_id in slave_ids:
            for baudrate in baudrates:
                # Skip if this port+slave already found a meter
                key = (port, slave_id)
                if key in found_ports:
                    continue

                # Fast pre-check: is there any Modbus device on this port+baud?
                if not _port_has_modbus(port, baudrate, slave_id):
                    continue

                for sig in METER_SIGNATURES:
                    # Skip if this baud rate isn't in the meter's list
                    if baudrate not in sig["baudrates"]:
                        continue
                    if slave_id not in sig["slave_ids"]:
                        continue

                    detection = _test_meter(port, baudrate, slave_id, sig)
                    if detection is not None:
                        results.append(detection)
                        found_ports.add(key)
                        break  # found this meter, move to next port

                time.sleep(RETRY_DELAY)  # RS485 bus settle time

    return results


def rescan_for_meter(meter_type, known_port=None):
    """Re-scan ports to find a specific meter type.
    
    Used when a meter becomes unresponsive — tries the known port first,
    then all other ports.
    
    Args:
        meter_type: The meter type string to look for (e.g., "SPM32")
        known_port: The port where the meter was last seen (optional)
    
    Returns:
        dict with detection info or None
    """
    ports = scan_ports()
    if not ports:
        return None

    # Try known port first (fast path)
    if known_port and known_port in ports:
        for sig in METER_SIGNATURES:
            if sig["type"] == meter_type:
                detection = _test_meter(known_port, sig["baudrates"][0], 1, sig)
                if detection:
                    return detection
                break

    # Full scan on all ports for this specific type
    results = detect_meters(ports=ports)
    for r in results:
        if r["meter_type"] == meter_type:
            return r

    return None


def detect_any_meter(known_port=None):
    """Detect ANY meter on any port. Used when the meter type may have changed.
    
    Tries the known port first (fast path), then all ports.
    Returns the first meter found, or None.
    """
    if known_port:
        ports = scan_ports()
        if known_port in ports:
            for sig in METER_SIGNATURES:
                for baud in sig["baudrates"]:
                    detection = _test_meter(known_port, baud, 1, sig)
                    if detection:
                        return detection

    # Full scan on all ports — return first result
    results = detect_meters()
    return results[0] if results else None
