"""
Data Validation Engine for meter-app-v2. v2.0.0

Validates each meter reading against 8 rules and produces a validation
result with status (OK/WARNING/CRITICAL), confidence score, and issues list.

Validation ranges:
- Voltage: 90-140V OR 180-240V (dual range for different grid standards)
- Frequency: 45-62 Hz
"""

from collections import defaultdict


class ValidationResult:
    """Result of validating a single meter reading."""
    __slots__ = ['timestamp_ms', 'overall', 'checks', 'confidence', 'issues']

    def __init__(self, timestamp_ms=0, overall="OK", checks=None, confidence=1.0, issues=None):
        self.timestamp_ms = timestamp_ms
        self.overall = overall
        self.checks = checks or []
        self.confidence = confidence
        self.issues = issues or []

    def to_dict(self):
        return {
            "status": self.overall,
            "score": round(self.confidence, 4),
            "checks": self.checks,
            "issues": self.issues,
        }


class DataValidator:
    """Validates meter readings against plausibility rules.

    Rules:
    V1: Voltage plausibility   — AV/BV/CV in (90-140) OR (180-240)  [CRITICAL]
    V2: Frequency plausibility — F in 45-62 Hz                       [CRITICAL]
    V3: Current plausibility   — C{n}I in 0-max_i                    [WARNING]
    V4: Power factor range     — C{n}PF in 0-1.0                     [WARNING]
    V5: Energy monotonicity    — AE/RE never decreases               [CRITICAL]
    V6: Zero data detection    — all channels I=0 for 3+ readings    [CRITICAL]
    V7: Spike detection        — power jumps > 10x                   [WARNING]
    V8: Time gap detection     — gap > 2x expected interval          [WARNING]
    """

    def __init__(self, config=None, logger=None):
        self.logger = logger
        self.v_min_low = 90
        self.v_max_low = 140
        self.v_min_high = 180
        self.v_max_high = 240
        self.f_min = 45
        self.f_max = 62
        self.max_i = 100  # default CT max, can be overridden
        self.spike_threshold = 10  # power jump > 10x
        self.zero_data_count = 3   # consecutive zero readings
        self.gap_multiplier = 2    # gap > 2x expected

        # History for stateful checks (V5, V6, V7)
        self._prev_readings = defaultdict(lambda: None)  # meter_id -> last reading
        self._consecutive_zeros = defaultdict(int)       # meter_id -> count

    def validate(self, data, meter_id="1", expected_interval_ms=None):
        """Validate a meter reading dict.

        Args:
            data: normalized meter data dict (lowercase keys like 'av', 'c1i', etc.)
            meter_id: identifier for this meter
            expected_interval_ms: expected time between readings (for V8)

        Returns:
            ValidationResult with overall status, checks, confidence, issues
        """
        checks = []
        issues = []
        timestamp_ms = data.get('time', 0)

        # V1: Voltage plausibility
        self._check_voltage(data, checks, issues)

        # V2: Frequency plausibility
        self._check_frequency(data, checks, issues)

        # V3: Current plausibility
        self._check_current(data, checks, issues)

        # V4: Power factor range
        self._check_power_factor(data, checks, issues)

        # V5: Energy monotonicity
        prev = self._prev_readings[meter_id]
        self._check_energy_monotonicity(data, prev, checks, issues)

        # V6: Zero data detection
        self._check_zero_data(data, meter_id, checks, issues)

        # V7: Spike detection
        self._check_spike(data, prev, checks, issues)

        # V8: Time gap detection
        self._check_time_gap(data, prev, expected_interval_ms, checks, issues)

        # Calculate overall status and confidence
        critical_count = sum(1 for c in checks if c['status'] == 'CRITICAL')
        warning_count = sum(1 for c in checks if c['status'] == 'WARNING')

        if critical_count > 0:
            overall = "CRITICAL"
        elif warning_count > 0:
            overall = "WARNING"
        else:
            overall = "OK"

        confidence = max(0.0, 1.0 - (critical_count * 0.3 + warning_count * 0.1))

        # Store for next comparison
        self._prev_readings[meter_id] = data

        return ValidationResult(
            timestamp_ms=timestamp_ms,
            overall=overall,
            checks=checks,
            confidence=confidence,
            issues=issues,
        )

    def _check_voltage(self, data, checks, issues):
        """V1: AV/BV/CV must be in (90-140) OR (180-240)."""
        for key, label in [('av', 'AV'), ('bv', 'BV'), ('cv', 'CV')]:
            v = data.get(key, 0)
            if v == 0:
                continue  # skip zero (not connected)
            in_low = self.v_min_low <= v <= self.v_max_low
            in_high = self.v_min_high <= v <= self.v_max_high
            if in_low or in_high:
                checks.append({"rule": "V1", "status": "OK", "message": f"{label}={v:.1f}V"})
            else:
                msg = f"{label}={v:.1f}V out of range ({self.v_min_low}-{self.v_max_low} or {self.v_min_high}-{self.v_max_high})"
                checks.append({"rule": "V1", "status": "CRITICAL", "message": msg})
                issues.append(msg)

    def _check_frequency(self, data, checks, issues):
        """V2: F must be 45-62 Hz."""
        f = data.get('f', 0)
        if f == 0:
            return
        if self.f_min <= f <= self.f_max:
            checks.append({"rule": "V2", "status": "OK", "message": f"F={f:.1f}Hz"})
        else:
            msg = f"F={f:.1f}Hz out of range ({self.f_min}-{self.f_max})"
            checks.append({"rule": "V2", "status": "CRITICAL", "message": msg})
            issues.append(msg)

    def _check_current(self, data, checks, issues):
        """V3: Channel current must be 0-CT_max."""
        max_warnings = 0
        n = 1
        while True:
            key = f'c{n}i'
            if key not in data:
                break
            i_val = data[key]
            if i_val > self.max_i:
                msg = f"C{n}I={i_val:.2f}A exceeds max {self.max_i}A"
                issues.append(msg)
                max_warnings += 1
            n += 1

        if max_warnings == 0:
            checks.append({"rule": "V3", "status": "OK", "message": f"All currents within range"})
        else:
            checks.append({"rule": "V3", "status": "WARNING", "message": f"{max_warnings} channel(s) exceed current limit"})

    def _check_power_factor(self, data, checks, issues):
        """V4: PF must be 0-1.0."""
        bad_count = 0
        n = 1
        while True:
            key = f'c{n}pf'
            if key not in data:
                break
            pf = data[key]
            if pf < 0 or pf > 1.0:
                bad_count += 1
                issues.append(f"C{n}PF={pf:.3f} out of range [0-1]")
            n += 1

        if bad_count == 0:
            checks.append({"rule": "V4", "status": "OK", "message": "All power factors in range"})
        else:
            checks.append({"rule": "V4", "status": "WARNING", "message": f"{bad_count} channel(s) have invalid PF"})

    def _check_energy_monotonicity(self, data, prev, checks, issues):
        """V5: AE/RE must not decrease between readings."""
        if prev is None:
            checks.append({"rule": "V5", "status": "OK", "message": "First reading — skip monotonicity"})
            return

        rollbacks = 0
        n = 1
        while True:
            for suffix in ['ae', 're']:
                key = f'c{n}{suffix}'
                if key not in data:
                    continue
                curr = data[key]
                prev_val = prev.get(key, 0)
                if curr < prev_val and prev_val > 0:
                    rollbacks += 1
                    issues.append(f"C{n}{suffix.upper()} rolled back: {prev_val:.4f} → {curr:.4f}")
            if f'c{n}i' not in data and f'c{n}p' not in data:
                break
            n += 1

        if rollbacks == 0:
            checks.append({"rule": "V5", "status": "OK", "message": "Energy values monotonic"})
        else:
            checks.append({"rule": "V5", "status": "CRITICAL", "message": f"{rollbacks} energy rollback(s) detected"})

    def _check_zero_data(self, data, meter_id, checks, issues):
        """V6: If all channels read 0 for 3+ consecutive readings, flag as critical."""
        n = 1
        all_zero = True
        while True:
            key = f'c{n}i'
            if key not in data:
                if n == 1:
                    all_zero = False
                break
            if data[key] != 0:
                all_zero = False
                break
            n += 1

        if all_zero and n > 1:
            self._consecutive_zeros[meter_id] += 1
        else:
            self._consecutive_zeros[meter_id] = 0

        count = self._consecutive_zeros[meter_id]
        if count >= self.zero_data_count:
            msg = f"All channels zero for {count} consecutive readings"
            checks.append({"rule": "V6", "status": "CRITICAL", "message": msg})
            issues.append(msg)
        else:
            checks.append({"rule": "V6", "status": "OK", "message": "Channels have data"})

    def _check_spike(self, data, prev, checks, issues):
        """V7: Power jump > 10x from previous reading."""
        if prev is None:
            checks.append({"rule": "V7", "status": "OK", "message": "First reading — skip spike check"})
            return

        spikes = 0
        n = 1
        while True:
            key_p = f'c{n}p'
            if key_p not in data:
                break
            curr_p = abs(data[key_p])
            prev_p = abs(prev.get(key_p, 0))
            if prev_p > 0 and curr_p > self.spike_threshold * prev_p:
                spikes += 1
                issues.append(f"C{n}P spike: {prev_p:.1f} → {curr_p:.1f} ({curr_p/prev_p:.1f}x)")
            n += 1

        if spikes == 0:
            checks.append({"rule": "V7", "status": "OK", "message": "No power spikes detected"})
        else:
            checks.append({"rule": "V7", "status": "WARNING", "message": f"{spikes} power spike(s) detected"})

    def _check_time_gap(self, data, prev, expected_interval_ms, checks, issues):
        """V8: Gap between readings > 2x expected interval."""
        if prev is None or expected_interval_ms is None:
            checks.append({"rule": "V8", "status": "OK", "message": "Skip — no previous reading or interval"})
            return

        curr_ts = data.get('time', 0)
        prev_ts = prev.get('time', 0)
        if curr_ts == 0 or prev_ts == 0:
            checks.append({"rule": "V8", "status": "OK", "message": "Skip — missing timestamps"})
            return

        gap_ms = curr_ts - prev_ts
        threshold = expected_interval_ms * self.gap_multiplier

        if gap_ms <= threshold:
            gap_min = gap_ms / 60000
            checks.append({"rule": "V8", "status": "OK", "message": f"Gap {gap_min:.1f}min within tolerance"})
        else:
            gap_min = gap_ms / 60000
            expected_min = expected_interval_ms / 60000
            msg = f"Gap {gap_min:.1f}min exceeds {expected_min * self.gap_multiplier:.1f}min threshold"
            checks.append({"rule": "V8", "status": "WARNING", "message": msg})
            issues.append(msg)
