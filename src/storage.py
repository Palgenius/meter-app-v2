import sqlite3
import json
import shutil
import os
import time
from datetime import datetime, timedelta
from os import makedirs, path


class Storage:
    """SQLite storage with WAL mode and monthly archiving. v2.0.0"""

    def __init__(self, db_dir="database/", logger=None):
        self.db_dir = db_dir
        self.archive_dir = path.join(db_dir, "archive")
        self.db_path = path.join(db_dir, "active.db")
        self.logger = logger
        makedirs(db_dir, exist_ok=True)
        makedirs(self.archive_dir, exist_ok=True)
        self._conn = None
        self._archive_conn = None
        self._connect()
        self._connect_archive()
        self._create_tables()

    def _connect(self):
        """Connect to SQLite with WAL mode, integrity check, and corruption recovery."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row

        # Phase 1.2: Integrity check on startup
        self._check_integrity()

    def _check_integrity(self):
        """Check database integrity and recover if corrupted."""
        try:
            result = self._conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] == "ok":
                return  # Database is healthy

            # Corruption detected — recover
            self._log_error("CRITICAL: Database corruption detected!", None)
            corrupt_name = f"active_corrupt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            corrupt_path = path.join(self.db_dir, corrupt_name)
            self._conn.close()
            shutil.copy2(self.db_path, corrupt_path)
            self._log_error(f"Corrupt database backed up to: {corrupt_name}", None)

            # Try restoring from latest archive
            restored = self._try_restore_from_archive()
            if restored:
                self._log_info(f"Restored database from archive: {restored}")
            else:
                # Create fresh database
                self._log_error("No archive available. Creating fresh database.", None)
                os.remove(self.db_path)
                self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.row_factory = sqlite3.Row

        except Exception as ex:
            self._log_error(f"Integrity check failed: {ex}", None)

    def _try_restore_from_archive(self):
        """Try to restore active.db from the most recent archive file."""
        try:
            archives = sorted(
                [f for f in os.listdir(self.archive_dir) if f.endswith('.db')],
                reverse=True
            )
            if not archives:
                return None

            latest = path.join(self.archive_dir, archives[0])
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
            return archives[0]
        except Exception as ex:
            self._log_error(f"Archive restore failed: {ex}", None)
            return None

    def _create_tables(self):
        c = self._conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS readings_1min (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_id     TEXT NOT NULL,
                meter_id     TEXT NOT NULL,
                meter_type   TEXT NOT NULL,
                node         TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                data_json    TEXT NOT NULL,
                created_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS readings_15min (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_id       TEXT NOT NULL,
                meter_id       TEXT NOT NULL,
                meter_type     TEXT NOT NULL,
                node           TEXT NOT NULL,
                channel_count  INTEGER NOT NULL,
                timestamp_ms   INTEGER NOT NULL,
                datetime_str   TEXT NOT NULL,
                grid_json      TEXT NOT NULL,
                channels_json  TEXT NOT NULL,
                totals_json    TEXT NOT NULL,
                sample_count   INTEGER DEFAULT 0,
                send_status    TEXT DEFAULT 'pending',
                sent_at        TEXT,
                created_at     TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                filename      TEXT NOT NULL,
                file_path     TEXT NOT NULL,
                file_type     TEXT DEFAULT 'active',
                upload_status TEXT DEFAULT 'pending',
                uploaded_at   TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_1min_ts ON readings_1min(panel_id, meter_id, timestamp_ms)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_15min_send ON readings_15min(send_status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_15min_ts ON readings_15min(panel_id, meter_id, timestamp_ms)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_backup ON backups(upload_status)")
        # Phase 2: Validation table
        c.execute("""CREATE TABLE IF NOT EXISTS readings_validation (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ms   INTEGER NOT NULL,
                meter_id       TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                checks_json    TEXT NOT NULL,
                confidence     REAL DEFAULT 1.0,
                issues_json    TEXT DEFAULT '[]',
                created_at     TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_val_ts ON readings_validation(meter_id, timestamp_ms)")
        self._conn.commit()

    # ── 1-min readings ──────────────────────────────────────────────

    def insert_1min(self, panel_id, meter_id, meter_type, node, timestamp_ms, data):
        try:
            self._conn.execute(
                "INSERT INTO readings_1min (panel_id, meter_id, meter_type, node, timestamp_ms, data_json) VALUES (?,?,?,?,?,?)",
                (panel_id, meter_id, meter_type, node, timestamp_ms, json.dumps(data))
            )
            self._conn.commit()
            return True
        except Exception as ex:
            self._log_error("insert_1min failed", ex)
            return False

    def get_1min_range(self, panel_id, meter_id, start_ms, end_ms):
        try:
            rows = self._conn.execute(
                "SELECT data_json FROM readings_1min WHERE panel_id=? AND meter_id=? AND timestamp_ms>=? AND timestamp_ms<? ORDER BY timestamp_ms",
                (panel_id, meter_id, start_ms, end_ms)
            ).fetchall()
            return [json.loads(r["data_json"]) for r in rows]
        except Exception as ex:
            self._log_error("get_1min_range failed", ex)
            return []

    def get_last_1min_timestamp(self, panel_id, meter_id):
        try:
            row = self._conn.execute(
                "SELECT MAX(timestamp_ms) as ts FROM readings_1min WHERE panel_id=? AND meter_id=?",
                (panel_id, meter_id)
            ).fetchone()
            return row["ts"] if row and row["ts"] else 0
        except Exception as ex:
            self._log_error("get_last_1min_timestamp failed", ex)
            return 0

    # ── 15-min samples ──────────────────────────────────────────────

    def insert_15min(self, panel_id, meter_id, meter_type, node, channel_count,
                     timestamp_ms, datetime_str, grid, channels, totals, sample_count):
        try:
            self._conn.execute(
                """INSERT INTO readings_15min
                   (panel_id, meter_id, meter_type, node, channel_count,
                    timestamp_ms, datetime_str, grid_json, channels_json, totals_json, sample_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (panel_id, meter_id, meter_type, node, channel_count,
                 timestamp_ms, datetime_str,
                 json.dumps(grid), json.dumps(channels), json.dumps(totals), sample_count)
            )
            self._conn.commit()
            return True
        except Exception as ex:
            self._log_error("insert_15min failed", ex)
            return False

    def get_pending_15min(self, limit=50):
        try:
            rows = self._conn.execute(
                "SELECT * FROM readings_15min WHERE send_status='pending' ORDER BY timestamp_ms LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as ex:
            self._log_error("get_pending_15min failed", ex)
            return []

    def mark_15min_sent(self, record_id):
        try:
            self._conn.execute(
                "UPDATE readings_15min SET send_status='sent', sent_at=datetime('now') WHERE id=?",
                (record_id,)
            )
            self._conn.commit()
        except Exception as ex:
            self._log_error("mark_15min_sent failed", ex)

    def mark_15min_failed(self, record_id):
        try:
            self._conn.execute(
                "UPDATE readings_15min SET send_status='failed' WHERE id=?",
                (record_id,)
            )
            self._conn.commit()
        except Exception as ex:
            self._log_error("mark_15min_failed failed", ex)

    def get_last_15min_timestamp(self, panel_id, meter_id):
        try:
            row = self._conn.execute(
                "SELECT MAX(timestamp_ms) as ts FROM readings_15min WHERE panel_id=? AND meter_id=?",
                (panel_id, meter_id)
            ).fetchone()
            return row["ts"] if row and row["ts"] else 0
        except Exception as ex:
            self._log_error("get_last_15min_timestamp failed", ex)
            return 0

    def get_latest_15min(self, panel_id, meter_id, limit=1):
        """Get the most recent 15-min records for a specific meter."""
        try:
            rows = self._conn.execute(
                "SELECT * FROM readings_15min WHERE panel_id=? AND meter_id=? ORDER BY timestamp_ms DESC LIMIT ?",
                (panel_id, meter_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as ex:
            self._log_error("get_latest_15min failed", ex)
            return []

    def get_pending_15min_by_meter(self, panel_id, meter_id):
        """Get all pending 15-min records for a specific meter."""
        try:
            rows = self._conn.execute(
                "SELECT * FROM readings_15min WHERE panel_id=? AND meter_id=? AND send_status='pending' ORDER BY timestamp_ms",
                (panel_id, meter_id)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as ex:
            self._log_error("get_pending_15min_by_meter failed", ex)
            return []

    # ── Backups ─────────────────────────────────────────────────────

    def insert_backup_record(self, filename, file_path, file_type="active"):
        try:
            self._conn.execute(
                "INSERT INTO backups (filename, file_path, file_type) VALUES (?,?,?)",
                (filename, file_path, file_type)
            )
            self._conn.commit()
        except Exception as ex:
            self._log_error("insert_backup_record failed", ex)

    def get_pending_backups(self):
        try:
            rows = self._conn.execute(
                "SELECT * FROM backups WHERE upload_status='pending' ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as ex:
            self._log_error("get_pending_backups failed", ex)
            return []

    def mark_backup_done(self, backup_id):
        try:
            self._conn.execute(
                "UPDATE backups SET upload_status='sent', uploaded_at=datetime('now') WHERE id=?",
                (backup_id,)
            )
            self._conn.commit()
        except Exception as ex:
            self._log_error("mark_backup_done failed", ex)

    # ── Monthly archive ─────────────────────────────────────────────

    def archive_previous_month(self):
        now = datetime.now()
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end_ms = int(first_of_month.timestamp() * 1000)

        prev = first_of_month - timedelta(days=1)
        archive_name = prev.strftime("%Y-%m") + ".db"
        archive_path = path.join(self.archive_dir, archive_name)

        if path.exists(archive_path):
            self._log_info(f"Archive {archive_name} already exists, skipping")
            return archive_path

        try:
            archive_conn = sqlite3.connect(archive_path)
            archive_conn.execute("PRAGMA journal_mode=WAL")

            # Create same tables in archive
            for table in ["readings_1min", "readings_15min"]:
                schema = self._conn.execute(
                    f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
                ).fetchone()
                if schema:
                    archive_conn.execute(schema[0])

            # Move old 1-min data
            rows_1min = self._conn.execute(
                "SELECT * FROM readings_1min WHERE timestamp_ms < ?", (last_month_end_ms,)
            ).fetchall()
            if rows_1min:
                cols = [desc[0] for desc in self._conn.execute("SELECT * FROM readings_1min LIMIT 1").description]
                placeholders = ",".join(["?"] * len(cols))
                archive_conn.executemany(
                    f"INSERT INTO readings_1min ({','.join(cols)}) VALUES ({placeholders})",
                    [tuple(r) for r in rows_1min]
                )

            # Move old 15-min data
            rows_15min = self._conn.execute(
                "SELECT * FROM readings_15min WHERE timestamp_ms < ?", (last_month_end_ms,)
            ).fetchall()
            if rows_15min:
                cols = [desc[0] for desc in self._conn.execute("SELECT * FROM readings_15min LIMIT 1").description]
                placeholders = ",".join(["?"] * len(cols))
                archive_conn.executemany(
                    f"INSERT INTO readings_15min ({','.join(cols)}) VALUES ({placeholders})",
                    [tuple(r) for r in rows_15min]
                )

            archive_conn.commit()
            archive_conn.close()

            # Delete moved data from active
            self._conn.execute("DELETE FROM readings_1min WHERE timestamp_ms < ?", (last_month_end_ms,))
            self._conn.execute("DELETE FROM readings_15min WHERE timestamp_ms < ?", (last_month_end_ms,))
            self._conn.commit()
            self._conn.execute("VACUUM")

            self._log_info(f"Archived {len(rows_1min)} 1min + {len(rows_15min)} 15min records to {archive_name}")
            return archive_path

        except Exception as ex:
            self._log_error("archive_previous_month failed", ex)
            if path.exists(archive_path):
                os.remove(archive_path)
            return None

    def get_active_db_copy_path(self):
        """Create a snapshot copy of active.db for backup upload."""
        snapshot_path = path.join(self.db_dir, "active_snapshot.db")
        try:
            # Use SQLite backup API for consistency
            dst = sqlite3.connect(snapshot_path)
            self._conn.backup(dst)
            dst.close()
            return snapshot_path
        except Exception as ex:
            self._log_error("get_active_db_copy_path failed", ex)
            return None

    def list_archives(self):
        try:
            return [f for f in os.listdir(self.archive_dir) if f.endswith(".db")]
        except Exception:
            return []

    # ── WAL cleanup + VACUUM (Phase 1.3) ──────────────────────────

    def vacuum_and_cleanup(self):
        """Run VACUUM to reclaim space and check WAL file size."""
        try:
            # Check WAL file size
            wal_path = self.db_path + "-wal"
            if path.exists(wal_path):
                wal_size_mb = os.path.getsize(wal_path) / (1024 * 1024)
                if wal_size_mb > 10:
                    self._log_error(f"WAL file is {wal_size_mb:.1f}MB (threshold: 10MB)", None)

            # VACUUM to reclaim space
            self._conn.execute("VACUUM")
            self._log_info("VACUUM completed")
        except Exception as ex:
            self._log_error(f"VACUUM failed: {ex}", None)

    # ── Validation ────────────────────────────────────────────────

    def insert_validation(self, timestamp_ms, meter_id, overall_status, checks, confidence, issues):
        try:
            self._conn.execute(
                """INSERT INTO readings_validation
                   (timestamp_ms, meter_id, overall_status, checks_json, confidence, issues_json)
                   VALUES (?,?,?,?,?,?)""",
                (timestamp_ms, meter_id, overall_status, json.dumps(checks), confidence, json.dumps(issues))
            )
            self._conn.commit()
        except Exception as ex:
            self._log_error("insert_validation failed", ex)

    def get_recent_validations(self, meter_id, limit=100):
        try:
            rows = self._conn.execute(
                "SELECT * FROM readings_validation WHERE meter_id=? ORDER BY timestamp_ms DESC LIMIT ?",
                (meter_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as ex:
            self._log_error("get_recent_validations failed", ex)
            return []

    # ── Helpers ──────────────────────────────────────────────────────

    def close(self):
        """Close both active and archive database connections."""
        if self._archive_conn:
            try:
                self._archive_conn.close()
            except Exception:
                pass
        if self._conn:
            self._conn.close()

    # ── Archive Database (Phase 2) ─────────────────────────────────

    def _connect_archive(self):
        """Connect to archive.db with WAL mode. Creates tables if needed."""
        archive_path = path.join(self.db_dir, "archive.db")
        try:
            self._archive_conn = sqlite3.connect(archive_path, check_same_thread=False)
            self._archive_conn.execute("PRAGMA journal_mode=WAL")
            self._archive_conn.execute("PRAGMA synchronous=NORMAL")
            self._archive_conn.row_factory = sqlite3.Row
            # Create readings_1min table (same schema as active.db)
            self._archive_conn.execute("""
                CREATE TABLE IF NOT EXISTS readings_1min (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id     TEXT NOT NULL,
                    meter_id     TEXT NOT NULL,
                    meter_type   TEXT NOT NULL,
                    node         TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    data_json    TEXT NOT NULL,
                    created_at   TEXT DEFAULT (datetime('now'))
                )
            """)
            self._archive_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_arc_1min_ts ON readings_1min(panel_id, meter_id, timestamp_ms)")
            self._archive_conn.commit()
            self._log_info("Archive database connected")
        except Exception as ex:
            self._log_error(f"Archive DB connection failed: {ex}", ex)
            self._archive_conn = None

    def move_1min_to_archive(self, max_age_hours=2):
        """Move 1-min readings older than max_age_hours from active.db to archive.db.
        
        Called daily from backup thread. Keeps active.db small.
        Returns number of rows moved.
        """
        if not self._archive_conn:
            self._connect_archive()
        if not self._archive_conn:
            return 0

        try:
            cutoff_ms = int((time.time() - max_age_hours * 3600) * 1000)
            # Count rows to move
            count_row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM readings_1min WHERE timestamp_ms < ?",
                (cutoff_ms,)
            ).fetchone()
            count = count_row["cnt"] if count_row else 0
            if count == 0:
                return 0

            # Copy to archive.db in batches
            batch_size = 1000
            moved = 0
            while moved < count:
                rows = self._conn.execute(
                    "SELECT * FROM readings_1min WHERE timestamp_ms < ? ORDER BY timestamp_ms LIMIT ?",
                    (cutoff_ms, batch_size)
                ).fetchall()
                if not rows:
                    break
                cols = [d[0] for d in self._conn.execute("SELECT * FROM readings_1min LIMIT 1").description]
                placeholders = ",".join(["?"] * len(cols))
                col_names = ",".join(cols)
                self._archive_conn.executemany(
                    f"INSERT INTO readings_1min ({col_names}) VALUES ({placeholders})",
                    [tuple(r) for r in rows]
                )
                self._archive_conn.commit()
                # Delete from active
                ids = [r["id"] for r in rows]
                id_placeholders = ",".join(["?"] * len(ids))
                self._conn.execute(
                    f"DELETE FROM readings_1min WHERE id IN ({id_placeholders})", ids
                )
                self._conn.commit()
                moved += len(rows)

            self._log_info(f"Moved {moved} 1-min records to archive.db (>{max_age_hours}h old)")
            return moved
        except Exception as ex:
            self._log_error(f"move_1min_to_archive failed: {ex}", ex)
            return 0

    def delete_sent_15min(self, min_age_days=7):
        """Delete 15-min records that were sent to server and are older than min_age_days.
        
        Called daily from backup thread. These records are confirmed on the server
        so we don't need them locally anymore (15-min can be recalculated from 1-min).
        Returns number of rows deleted.
        """
        try:
            cutoff_ms = int((time.time() - min_age_days * 86400) * 1000)
            count_row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM readings_15min WHERE send_status='sent' AND timestamp_ms < ?",
                (cutoff_ms,)
            ).fetchone()
            count = count_row["cnt"] if count_row else 0
            if count == 0:
                return 0
            self._conn.execute(
                "DELETE FROM readings_15min WHERE send_status='sent' AND timestamp_ms < ?",
                (cutoff_ms,)
            )
            self._conn.commit()
            self._log_info(f"Deleted {count} sent 15-min records (>{min_age_days} days old)")
            return count
        except Exception as ex:
            self._log_error(f"delete_sent_15min failed: {ex}", ex)
            return 0

    def get_db_size_mb(self, db_path=None):
        """Get database file size in MB."""
        if db_path is None:
            db_path = self.db_path
        try:
            return os.path.getsize(db_path) / (1024 * 1024)
        except Exception:
            return 0

    def check_and_vacuum(self, max_active_mb=200):
        """Check active.db size and VACUUM if needed.
        
        Logs current sizes of both databases.
        Emergency: if active.db exceeds max_active_mb, force-move all 1-min data.
        Returns (active_mb, archive_mb) tuple.
        """
        try:
            import time as _time
            active_mb = self.get_db_size_mb()
            archive_mb = self.get_db_size_mb(path.join(self.db_dir, "archive.db"))

            self._log_info(f"DB sizes: active={active_mb:.1f}MB, archive={archive_mb:.1f}MB")

            # Emergency cleanup if active.db too large
            if active_mb > max_active_mb:
                self._log_error(f"active.db is {active_mb:.1f}MB (>{max_active_mb}MB) — emergency cleanup!", None)
                # Force-move ALL 1-min data to archive
                self.move_1min_to_archive(max_age_hours=0)
                # Also delete old sent 15-min records
                self.delete_sent_15min(min_age_days=1)

            # VACUUM to reclaim space
            self._conn.execute("VACUUM")
            self._log_info("VACUUM completed")

            # Check WAL file
            wal_path = self.db_path + "-wal"
            if path.exists(wal_path):
                wal_size_mb = os.path.getsize(wal_path) / (1024 * 1024)
                if wal_size_mb > 10:
                    self._log_error(f"WAL file is {wal_size_mb:.1f}MB (threshold: 10MB)", None)

            # Re-check after cleanup
            final_mb = self.get_db_size_mb()
            if final_mb != active_mb:
                self._log_info(f"active.db after VACUUM: {final_mb:.1f}MB (was {active_mb:.1f}MB)")

            return (final_mb, archive_mb)
        except Exception as ex:
            self._log_error(f"check_and_vacuum failed: {ex}", ex)
            return (0, 0)

    def compress_archive(self, month_str=None):
        """Export a month of archive.db data to a compressed .db.gz file.
        
        Args:
            month_str: Month in 'YYYY-MM' format. If None, uses previous month.
        
        Returns:
            Path to the .db.gz file, or None on failure.
        """
        import gzip
        import time as _time

        if not self._archive_conn:
            self._connect_archive()
        if not self._archive_conn:
            return None

        if month_str is None:
            now = datetime.now()
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            prev = first_of_month - timedelta(days=1)
            month_str = prev.strftime("%Y-%m")

        export_name = f"{month_str}.db"
        export_path = path.join(self.archive_dir, export_name)
        gz_path = path.join(self.archive_dir, f"{export_name}.gz")

        if path.exists(gz_path):
            self._log_info(f"Compressed archive {export_name}.gz already exists, skipping")
            return gz_path

        try:
            # Calculate timestamp range for the month
            year, month = int(month_str[:4]), int(month_str[5:7])
            start_dt = datetime(year, month, 1)
            if month == 12:
                end_dt = datetime(year + 1, 1, 1)
            else:
                end_dt = datetime(year, month + 1, 1)
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms = int(end_dt.timestamp() * 1000)

            # Create export database
            export_conn = sqlite3.connect(export_path)
            export_conn.execute("PRAGMA journal_mode=WAL")
            export_conn.execute("""
                CREATE TABLE IF NOT EXISTS readings_1min (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id     TEXT NOT NULL,
                    meter_id     TEXT NOT NULL,
                    meter_type   TEXT NOT NULL,
                    node         TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    data_json    TEXT NOT NULL,
                    created_at   TEXT DEFAULT (datetime('now'))
                )
            """)

            # Copy data from archive.db for the target month
            rows = self._archive_conn.execute(
                "SELECT * FROM readings_1min WHERE timestamp_ms >= ? AND timestamp_ms < ? ORDER BY timestamp_ms",
                (start_ms, end_ms)
            ).fetchall()
            if rows:
                cols = [d[0] for d in self._archive_conn.execute("SELECT * FROM readings_1min LIMIT 1").description]
                placeholders = ",".join(["?"] * len(cols))
                col_names = ",".join(cols)
                export_conn.executemany(
                    f"INSERT INTO readings_1min ({col_names}) VALUES ({placeholders})",
                    [tuple(r) for r in rows]
                )
                export_conn.commit()
            export_conn.close()

            # Compress with gzip
            with open(export_path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Remove uncompressed copy
            os.remove(export_path)

            gz_size_mb = os.path.getsize(gz_path) / (1024 * 1024)
            self._log_info(f"Compressed archive: {export_name}.gz ({gz_size_mb:.1f}MB, {len(rows)} records)")

            # Delete exported month from archive.db to keep it manageable
            if rows:
                self._archive_conn.execute(
                    "DELETE FROM readings_1min WHERE timestamp_ms >= ? AND timestamp_ms < ?",
                    (start_ms, end_ms)
                )
                self._archive_conn.commit()
                self._archive_conn.execute("VACUUM")
                self._log_info(f"Cleaned {month_str} from archive.db after export")

            return gz_path
        except Exception as ex:
            self._log_error(f"compress_archive failed: {ex}", ex)
            # Clean up partial files
            for p in [export_path, gz_path]:
                if path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            return None

    # Phase 1.3: WAL cleanup + VACUUM
    def vacuum_and_cleanup(self):
        """Run VACUUM to reclaim space and check WAL file size."""
        try:
            wal_path = self.db_path + "-wal"
            if os.path.exists(wal_path):
                wal_size_mb = os.path.getsize(wal_path) / (1024 * 1024)
                if wal_size_mb > 10:
                    self._log_error(f"WAL file is {wal_size_mb:.1f}MB (threshold: 10MB)", None)
            self._conn.execute("VACUUM")
            self._log_info("VACUUM completed")
        except Exception as ex:
            self._log_error(f"VACUUM failed: {ex}", None)

    # Phase 2: Validation storage
    def insert_validation(self, timestamp_ms, meter_id, overall_status, checks, confidence, issues):
        """Store a validation result."""
        try:
            self._conn.execute(
                """INSERT INTO readings_validation
                   (timestamp_ms, meter_id, overall_status, checks_json, confidence, issues_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (timestamp_ms, meter_id, overall_status, json.dumps(checks), confidence, json.dumps(issues))
            )
            self._conn.commit()
        except Exception as ex:
            self._log_error("insert_validation failed", ex)

    def get_recent_validations(self, meter_id, limit=20):
        """Get recent validation results for a meter."""
        try:
            rows = self._conn.execute(
                """SELECT * FROM readings_validation
                   WHERE meter_id=? ORDER BY timestamp_ms DESC LIMIT ?""",
                (meter_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as ex:
            self._log_error("get_recent_validations failed", ex)
            return []

    def _log_info(self, msg):
        if self.logger:
            self.logger.insert_Info_APP_log(f"[Storage] {msg}")

    def _log_error(self, msg, ex=None):
        if self.logger:
            self.logger.insert_Error_APP_log(f"[Storage] {msg}", ex if ex else "")
