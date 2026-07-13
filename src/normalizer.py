"""
Channel normalizer for meter data. v2.0.0

Converts meter-specific channel naming to a uniform format:
  C{n}I, C{n}V, C{n}P, C{n}Q, C{n}S, C{n}PF, C{n}AE, C{n}RE

PMAC211: C1Ia→C1, C1Ib→C2, C1Ic→C3, C2Ia→C4, ... (4 groups × 3 phases = 12 channels)
All others: already use C{n} format — pass through with lowercase.
"""

PARAMS = ['i', 'v', 'p', 'q', 's', 'pf', 'ae', 're']
PHASES = ['a', 'b', 'c']


def normalize(data, meter_type):
    """Normalize meter data dict to uniform lowercase c{n}{param} format.
    
    Returns (normalized_dict, channel_count).
    """
    if meter_type.upper() == "PMAC211":
        return _normalize_pmac211(data)
    return _normalize_standard(data)


def _normalize_pmac211(data):
    """PMAC211: C{group}{param}{phase} → C{ct}{param}
    where ct = 3*(group-1) + phase_index + 1
    """
    result = {}
    group_count = 4

    # Normalize input keys to lowercase for consistent lookup
    data_lower = {k.lower(): v for k, v in data.items()}

    # Copy grid and meta fields
    for key in ['panelid', 'meterid', 'node', 'time', 'version',
                'av', 'bv', 'cv', 'v', 'f']:
        if key in data_lower:
            result[key] = data_lower[key]

    # Remap per-channel fields: C{group}{param}{phase} → C{ct}{param}
    # PMAC211 doesn't have per-channel voltage (c1va etc), so assign phase voltage
    phase_voltage_map = {'a': 'av', 'b': 'bv', 'c': 'cv'}
    for group in range(1, group_count + 1):
        for phase_idx, phase in enumerate(PHASES):
            ct = 3 * (group - 1) + phase_idx + 1
            for param in PARAMS:
                old_key = f'c{group}{param}{phase}'
                new_key = f'c{ct}{param}'
                if old_key in data_lower:
                    result[new_key] = data_lower[old_key]
                # Also carry cumulative (raw) values for 15-min aggregation
                old_key_cum = f'{old_key}_cum'
                new_key_cum = f'{new_key}_cum'
                if old_key_cum in data_lower:
                    result[new_key_cum] = data_lower[old_key_cum]
            # Assign voltage from phase voltage if per-channel voltage missing
            if f'c{ct}v' not in result:
                phase_v = data_lower.get(phase_voltage_map[phase], 0)
                if phase_v:
                    result[f'c{ct}v'] = phase_v

    # Copy phase sums and totals
    for phase in PHASES:
        for param in PARAMS:
            key = f'{param}{phase}'
            if key in data_lower:
                result[key] = data_lower[key]

    for param in ['ti', 'tp', 'tq', 'ts', 'tpf', 'tae', 'tre']:
        if param in data_lower:
            result[param] = data_lower[param]
        # Carry cumulative totals for 15-min aggregation
        if f'{param}_cum' in data_lower:
            result[f'{param}_cum'] = data_lower[f'{param}_cum']

    # Carry cumulative phase sums (aea_cum, aeb_cum, etc.)
    for phase in PHASES:
        for param in ['ae', 're']:
            key_cum = f'{param}{phase}_cum'
            if key_cum in data_lower:
                result[key_cum] = data_lower[key_cum]

    # Count channels
    channel_count = group_count * len(PHASES)  # always 12

    return result, channel_count


def _normalize_standard(data):
    """Standard meters: already use c{n}{param} format after lowercase.
    Just count channels and pass through.
    """
    channel_count = 0
    n = 1
    while f'c{n}i' in data or f'c{n}p' in data:
        channel_count = n
        n += 1

    return data, channel_count


def get_channel_count(data):
    """Count how many channels exist in normalized data."""
    n = 1
    while f'c{n}i' in data or f'c{n}p' in data:
        n += 1
    return n - 1



