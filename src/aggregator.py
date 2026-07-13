"""
15-minute aggregator. v2.0.0

Pure Python — no pandas/numpy. Queries 1-min readings from SQLite,
computes mean/sum, stores into readings_15min.
"""

from datetime import datetime


def snap_to_quarter(timestamp_ms):
    """Snap a timestamp to the nearest 15-minute boundary (floor).
    Returns (snapped_ms, datetime_str).
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    minute = dt.minute
    if minute < 15:
        snapped_min = 0
    elif minute < 30:
        snapped_min = 15
    elif minute < 45:
        snapped_min = 30
    else:
        snapped_min = 45
    snapped = dt.replace(minute=snapped_min, second=0, microsecond=0)
    return int(snapped.timestamp() * 1000), snapped.strftime("%Y-%m-%d %H:%M:%S")


def next_quarter_ms(timestamp_ms):
    """Get the start of the NEXT 15-minute window after timestamp_ms."""
    snapped_ms, _ = snap_to_quarter(timestamp_ms)
    return snapped_ms + 15 * 60 * 1000


def get_current_quarter_start_ms():
    """Get the start of the current 15-min window."""
    now_ms = int(datetime.now().timestamp() * 1000)
    snapped_ms, _ = snap_to_quarter(now_ms)
    return snapped_ms


def aggregate_readings(readings, channel_count):
    """Aggregate a list of 1-min reading dicts into one 15-min sample.
    
    - V, I, P, Q, S, PF, F: mean (ignoring zeros for I/P/Q/S/PF)
    - AE, RE: sum
    
    Returns dict with grid, channels list, totals.
    """
    n = len(readings)
    if n == 0:
        return None

    grid = {}
    # Grid values: mean
    for key in ['av', 'bv', 'cv', 'v', 'f']:
        vals = [r[key] for r in readings if key in r and r[key] != 0]
        grid[key] = round(sum(vals) / len(vals), 2) if vals else 0

    # Per-channel
    channels = []
    for ch in range(1, channel_count + 1):
        ch_data = {"ch": ch}

        # Voltage: assign phase voltage if channel voltage not available
        v_key = f'c{ch}v'
        v_vals = [r.get(v_key, 0) for r in readings if r.get(v_key, 0) != 0]
        if v_vals:
            ch_data['v'] = round(sum(v_vals) / len(v_vals), 2)
        else:
            # Assign phase voltage based on channel number
            phase = (ch - 1) % 3
            phase_key = ['av', 'bv', 'cv'][phase]
            ch_data['v'] = grid.get(phase_key, 0)

        # Mean params (ignore zeros)
        for param in ['i', 'p', 'q', 's', 'pf']:
            key = f'c{ch}{param}'
            vals = [r.get(key, 0) for r in readings if r.get(key, 0) != 0]
            ch_data[param] = round(sum(vals) / len(vals), 4) if vals else 0

        # Delta params (AE, RE) — use cumulative values for accurate delta
        for param in ['ae', 're']:
            cum_key = f'c{ch}{param}_cum'
            plain_key = f'c{ch}{param}'
            # Prefer cumulative (raw counter) values for delta
            if cum_key in readings[0] and cum_key in readings[-1]:
                first_val = readings[0].get(cum_key, 0)
                last_val = readings[-1].get(cum_key, 0)
                ch_data[param] = round(last_val - first_val, 4) if last_val > first_val else 0
            else:
                # Fallback: sum per-interval values if no cumulative data
                vals = [r.get(plain_key, 0) for r in readings]
                ch_data[param] = round(sum(vals), 4) if vals else 0

        channels.append(ch_data)

    # Totals
    totals = {}
    for param in ['ti', 'tp', 'tq', 'ts', 'tpf']:
        vals = [r.get(param, 0) for r in readings if r.get(param, 0) != 0]
        totals[param] = round(sum(vals) / len(vals), 4) if vals else 0

    for param in ['tae', 'tre']:
        cum_key = f'{param}_cum'
        if cum_key in readings[0] and cum_key in readings[-1]:
            first_val = readings[0].get(cum_key, 0)
            last_val = readings[-1].get(cum_key, 0)
            totals[param] = round(last_val - first_val, 4) if last_val > first_val else 0
        else:
            vals = [r.get(param, 0) for r in readings]
            totals[param] = round(sum(vals), 4) if vals else 0

    return {
        "grid": grid,
        "channels": channels,
        "totals": totals,
        "sample_count": n
    }


class Aggregator:
    """Checks for completed 15-min windows and aggregates them."""

    def __init__(self, storage, logger=None):
        self.storage = storage
        self.logger = logger

    def check_and_aggregate(self, panel_id, meter_id, meter_type, node, channel_count):
        """Check if any complete 15-min windows need aggregation.
        
        A window is complete when current time has passed its end boundary.
        Returns count of aggregated windows.
        """
        current_quarter_start = get_current_quarter_start_ms()
        last_aggregated = self.storage.get_last_15min_timestamp(panel_id, meter_id)

        if last_aggregated == 0:
            # First run: start from the earliest 1-min reading, snapped to quarter
            first_ts = self._get_first_1min_ts(panel_id, meter_id)
            if first_ts == 0:
                return 0
            window_start, _ = snap_to_quarter(first_ts)
        else:
            window_start = next_quarter_ms(last_aggregated)

        aggregated_count = 0

        # Process all completed windows (not including the current one)
        while window_start < current_quarter_start:
            window_end = window_start + 15 * 60 * 1000
            readings = self.storage.get_1min_range(panel_id, meter_id, window_start, window_end)

            if readings:
                result = aggregate_readings(readings, channel_count)
                if result:
                    _, dt_str = snap_to_quarter(window_start)
                    self.storage.insert_15min(
                        panel_id, meter_id, meter_type, node, channel_count,
                        window_start, dt_str,
                        result["grid"], result["channels"], result["totals"],
                        result["sample_count"]
                    )
                    aggregated_count += 1
                    self._log_info(f"Aggregated {result['sample_count']} readings for {dt_str}")

            window_start = window_end

        return aggregated_count

    def _get_first_1min_ts(self, panel_id, meter_id):
        try:
            row = self.storage._conn.execute(
                "SELECT MIN(timestamp_ms) as ts FROM readings_1min WHERE panel_id=? AND meter_id=?",
                (panel_id, meter_id)
            ).fetchone()
            return row["ts"] if row and row["ts"] else 0
        except Exception:
            return 0

    def _log_info(self, msg):
        if self.logger:
            self.logger.insert_Info_APP_log(f"[Aggregator] {msg}")
