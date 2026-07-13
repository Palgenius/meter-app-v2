"""
Logging module for meter-app-v2. v2.0.0

Log types:
- MainLogger: app lifecycle, orchestrator events
- MeterLogger: per-meter app events + 1-min CSV + 15-min CSV + raw meter data
"""

from csv_logger import CsvLogger
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from os import makedirs, path, walk, remove
from os.path import getsize


def check_log_size(log_dir="logs/", max_size_mb=500, warn_size_mb=400):
    """Phase 1.4: Check total log directory size and clean up if needed.
    
    Returns (total_size_mb, was_cleaned, files_deleted).
    """
    total_size = 0
    all_files = []
    
    for root, dirs, files in walk(log_dir):
        for f in files:
            fp = path.join(root, f)
            try:
                size = getsize(fp)
                total_size += size
                all_files.append((fp, size))
            except OSError:
                pass
    
    total_size_mb = total_size / (1024 * 1024)
    was_cleaned = False
    files_deleted = 0
    
    if total_size_mb > max_size_mb:
        # Sort by modification time (oldest first) and delete until under warn_size_mb
        all_files.sort(key=lambda x: path.getmtime(x[0]))
        target_bytes = warn_size_mb * 1024 * 1024
        
        for fp, size in all_files:
            if total_size <= target_bytes:
                break
            try:
                remove(fp)
                total_size -= size
                files_deleted += 1
                was_cleaned = True
            except OSError:
                pass
    
    return total_size_mb, was_cleaned, files_deleted


class MainLogger:
    """Main application logger — lifecycle events, errors."""

    def __init__(self, config):
        self.max_size = config.getConfigVal("log_file_max_size", 10) * 1000000
        self.max_files = config.getConfigVal("log_max_files", 50)
        self.visible = config.getConfigVal("visible_App_Log", True)
        self.filename = f'{config.getConfigVal("log_main_path", "logs/main/")}log.txt'
        makedirs(path.dirname(self.filename), exist_ok=True)

        self.app_logger = logging.getLogger("main_logger_v2")
        if not self.app_logger.handlers:
            info_handler = RotatingFileHandler(self.filename, maxBytes=self.max_size, backupCount=self.max_files)
            info_handler.setLevel(logging.INFO)
            info_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self.app_logger.addHandler(info_handler)
        self.app_logger.setLevel(logging.INFO)

    def insert_Info_APP_log(self, *args):
        text = ' '.join(map(str, args))
        if self.visible:
            print(f"[main][{datetime.now()}] : {text}")
        self.app_logger.info(text)

    def insert_Error_APP_log(self, *args):
        text = ' '.join(map(str, args))
        if self.visible:
            print(f"[main][{datetime.now()}] ERROR: {text}")
        self.app_logger.error(text)


class MeterLogger:
    """Per-meter logger — app events, 1-min CSV, 15-min CSV, raw meter data."""

    def __init__(self, log_header, meter_type, meter_label, config):
        self.meter_type = meter_type
        self.meter_label = meter_label
        self.max_size = config.getConfigVal("log_file_max_size", 10) * 1000000
        self.max_files = config.getConfigVal("log_max_files", 50)
        self.visible = config.getConfigVal("visible_App_Log", True)

        # App log (text)
        self.app_logger = None
        app_log_path = f'{config.getConfigVal("APP_log_path", "logs/app/")}{meter_type}_{meter_label}/log.txt'
        if config.getConfigVal("APP_log_enable", True):
            self._init_app_log(app_log_path)

        # 1-min readings CSV log
        self.readings_logger = None
        readings_path = f'{config.getConfigVal("readings_log_path", "logs/readings/")}{meter_type}_{meter_label}/log.csv'
        if config.getConfigVal("readings_log_enable", True):
            self._init_csv_log(readings_path, log_header, "readings")
            self.readings_header = log_header  # store for reordering

        # 15-min samples CSV log
        self.samples_logger = None
        samples_header = self._build_15min_header()
        samples_path = f'{config.getConfigVal("samples_log_path", "logs/samples/")}{meter_type}_{meter_label}/log.csv'
        if config.getConfigVal("samples_log_enable", True):
            self._init_csv_log(samples_path, samples_header, "samples")

        # Raw meter data log
        self.meter_logger = None
        meter_log_path = f'{config.getConfigVal("meter_log_path", "logs/meter/")}{meter_type}_{meter_label}/log'
        if config.getConfigVal("METER_log_enable", False):
            self._init_meter_log(meter_log_path)

    def _init_app_log(self, filepath):
        makedirs(path.dirname(filepath), exist_ok=True)
        logger_name = f"app_{self.meter_type}_{self.meter_label}"
        self.app_logger = logging.getLogger(logger_name)
        # Only add handler if this logger doesn't have one yet (prevents duplicates on redetect)
        if not self.app_logger.handlers:
            handler = RotatingFileHandler(filepath, maxBytes=self.max_size, backupCount=self.max_files)
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self.app_logger.addHandler(handler)
        self.app_logger.setLevel(logging.INFO)

    def _init_csv_log(self, filepath, header, log_type):
        makedirs(path.dirname(filepath), exist_ok=True)
        level_name = f'{log_type}_{self.meter_type}_{self.meter_label}'
        
        # CsvLogger.__init__ calls addLoggingLevel which raises AttributeError
        # if the level name already exists (e.g. on redetect). 
        # Pre-register it so CsvLogger's check passes silently.
        if hasattr(logging, level_name):
            # Level already exists from a previous MeterLogger instance —
            # create CsvLogger without add_level_names to avoid the crash.
            logger = CsvLogger(
                filename=filepath,
                level=logging.INFO,
                add_level_names=[],
                fmt='%(asctime)s,%(levelname)s,%(message)s',
                datefmt='%Y/%m/%d %H:%M:%S',
                max_size=self.max_size,
                max_files=self.max_files,
                header=header
            )
        else:
            logger = CsvLogger(
                filename=filepath,
                level=logging.INFO,
                add_level_names=[level_name],
                fmt='%(asctime)s,%(levelname)s,%(message)s',
                datefmt='%Y/%m/%d %H:%M:%S',
                max_size=self.max_size,
                max_files=self.max_files,
                header=header
            )
        
        if log_type == "readings":
            self.readings_logger = logger
            self._readings_level = level_name
        else:
            self.samples_logger = logger
            self._samples_level = level_name

    def _init_meter_log(self, filepath):
        makedirs(path.dirname(filepath), exist_ok=True)
        self.meter_logger = logging.getLogger(f"meter_{self.meter_type}_{self.meter_label}")
        if not self.meter_logger.handlers:
            handler = RotatingFileHandler(filepath, maxBytes=self.max_size, backupCount=self.max_files)
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
            self.meter_logger.addHandler(handler)
        self.meter_logger.setLevel(logging.INFO)

    def _build_15min_header(self):
        return ['sendingDate', 'level', 'DateTime', 'PanelID', 'MeterID', 'Node',
                'channel_count', 'sample_count', 'send_status',
                'AV', 'BV', 'CV', 'V', 'F',
                'TI', 'TP', 'TQ', 'TS', 'TPF', 'TAE', 'TRE',
                'channels_json']

    # ── App log ─────────────────────────────────────────────────────

    def insert_Info_APP_log(self, *args):
        text = ' '.join(map(str, args))
        if self.visible:
            print(f"[{self.meter_type}_{self.meter_label}][{datetime.now()}] : {text}")
        if self.app_logger:
            self.app_logger.info(text)

    def insert_Error_APP_log(self, *args):
        text = ' '.join(map(str, args))
        if self.visible:
            print(f"[{self.meter_type}_{self.meter_label}][{datetime.now()}] ERROR: {text}")
        if self.app_logger:
            self.app_logger.error(text)

    # ── 1-min CSV log ───────────────────────────────────────────────

    def insert_readings_log(self, data_values):
        """Log a 1-min reading to CSV. data_values: list of values."""
        if self.readings_logger:
            try:
                self.readings_logger.__getattribute__(self._readings_level)(data_values)
            except Exception:
                pass

    # ── 15-min CSV log ──────────────────────────────────────────────

    def insert_samples_log(self, data_values):
        """Log a 15-min sample to CSV. data_values: list of values."""
        if self.samples_logger:
            try:
                self.samples_logger.__getattribute__(self._samples_level)(data_values)
            except Exception:
                pass

    # ── Raw meter data log ──────────────────────────────────────────

    def insert_meter_log(self, *args):
        if self.meter_logger:
            text = ','.join(map(str, args))
            self.meter_logger.info(text)
