"""
Cloud backup — uploads active.db daily and archives monthly. v2.0.0

Sends DB files to a remote endpoint or Dropbox with the device UUID for identification.
Phase 6: Dropbox API v2 upload support added.
"""

import os
import time
import json
import requests
from datetime import datetime


class Backup:
    """Handles uploading SQLite DB files to cloud backup endpoint."""

    def __init__(self, storage, config, logger=None):
        self.storage = storage
        self.logger = logger
        self.enabled = config.getConfigVal("backup_enabled", False)
        self.url = config.getConfigVal("backup_url", "")
        self.uuid = config.getConfigVal("Node", "unknown")
        # Try to get a proper UUID from the meter config
        meters = config.getConfigVal("meters", [])
        if meters and meters[0].get("PanelID"):
            self.uuid = meters[0]["PanelID"]
        self.daily_enabled = config.getConfigVal("backup_daily", True)
        self.monthly_enabled = config.getConfigVal("backup_monthly", True)
        self.exiting = False
        self._last_daily_date = None
        self._last_archive_month = None

        # Phase 6: Dropbox
        self.dropbox_enabled = config.getConfigVal("dropbox_backup_enabled", False)
        self.dropbox_token = config.getConfigVal("dropbox_token", "")
        self.dropbox_path = config.getConfigVal("dropbox_path", "/meter-backups/")

    def backup_thread(self):
        """Background thread: check for daily/monthly backup needs.
        
        Runs once per hour to check:
        - Daily: upload active.db snapshot if not uploaded today
        - Monthly: archive previous month + upload archive if 1st of month
        """
        self._log_info("Backup thread starting")
        # Wait a bit on startup to let other things initialize
        time.sleep(30)

        while not self.exiting:
            if not self.enabled:
                time.sleep(3600)
                continue

            try:
                now = datetime.now()

                # Monthly archive (1st of month, after 00:30)
                if self.monthly_enabled and now.day == 1 and now.hour >= 1:
                    month_key = now.strftime("%Y-%m")
                    if self._last_archive_month != month_key:
                        self._do_monthly_archive()
                        self._last_archive_month = month_key

                # Daily active.db backup
                if self.daily_enabled:
                    today = now.strftime("%Y-%m-%d")
                    if self._last_daily_date != today:
                        self._do_daily_backup()
                        self._last_daily_date = today

                # Retry any pending backups
                self._retry_pending()

            except Exception as ex:
                self._log_error("backup_thread error", ex)

            time.sleep(3600)  # Check once per hour

    def _do_monthly_archive(self):
        """Archive previous month's data and queue for upload."""
        self._log_info("Starting monthly archive...")
        archive_path = self.storage.archive_previous_month()
        if archive_path and os.path.exists(archive_path):
            filename = os.path.basename(archive_path)
            self.storage.insert_backup_record(filename, archive_path, file_type="archive")
            self._log_info(f"Monthly archive queued: {filename}")

    def _do_daily_backup(self):
        """Create a snapshot of active.db and queue for upload."""
        self._log_info("Starting daily backup...")
        snapshot_path = self.storage.get_active_db_copy_path()
        if snapshot_path and os.path.exists(snapshot_path):
            today_str = datetime.now().strftime("%Y-%m-%d")
            filename = f"active_{today_str}.db"
            self.storage.insert_backup_record(filename, snapshot_path, file_type="active")
            self._log_info(f"Daily backup queued: {filename}")

    def _retry_pending(self):
        """Upload any pending backup files."""
        pending = self.storage.get_pending_backups()
        for backup in pending:
            if self.exiting:
                break
            file_path = backup["file_path"]
            if not os.path.exists(file_path):
                self._log_error(f"Backup file missing: {file_path}")
                self.storage.mark_backup_done(backup["id"])  # remove from queue
                continue

            success = self._upload_file(file_path, backup["filename"], backup["file_type"])
            if success:
                self.storage.mark_backup_done(backup["id"])
                self._log_info(f"Backup uploaded: {backup['filename']}")
                # Clean up snapshot file if it was a daily backup
                if backup["file_type"] == "active" and "snapshot" in file_path:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
            else:
                self._log_error(f"Backup upload failed: {backup['filename']}, will retry")
                break  # stop trying, wait for next cycle

    def _upload_file(self, file_path, filename, file_type):
        """Upload a DB file via HTTP endpoint AND/OR Dropbox.
        
        Tries both if configured. Returns True if at least one succeeds.
        """
        http_ok = False
        dropbox_ok = False

        # HTTP upload
        if self.url:
            http_ok = self._upload_http(file_path, filename, file_type)

        # Dropbox upload
        if self.dropbox_enabled and self.dropbox_token:
            dropbox_ok = self._upload_to_dropbox(file_path, filename, file_type)

        return http_ok or dropbox_ok

    def _upload_http(self, file_path, filename, file_type):
        """Upload a DB file to the HTTP backup endpoint."""
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, 'application/octet-stream')}
                data = {'uuid': self.uuid, 'type': file_type, 'filename': filename}
                response = requests.post(self.url, files=files, data=data, timeout=120)

            if response.status_code == 200:
                self._log_info(f"HTTP upload OK: {filename}")
                return True
            else:
                self._log_error(f"HTTP upload failed: {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            self._log_error("No internet connection for HTTP backup")
            return False
        except requests.exceptions.Timeout:
            self._log_error("HTTP upload timed out")
            return False
        except Exception as ex:
            self._log_error(f"_upload_http error: {ex}")
            return False

    def _upload_to_dropbox(self, file_path, filename, file_type):
        """Upload a file to Dropbox using API v2.
        
        Uses Dropbox API v2 with OAuth2 token.
        Endpoint: https://content.dropboxapi.com/2/files/upload
        """
        if not self.dropbox_token:
            self._log_error("No Dropbox token configured")
            return False

        try:
            # Build remote path: /meter-backups/{uuid}/{type}/{filename}
            # Dropbox API requires path starting with /
            remote_path = f"/{self.dropbox_path.strip('/')}/{self.uuid}/{file_type}/{filename}"

            headers = {
                'Authorization': f'Bearer {self.dropbox_token}',
                'Dropbox-API-Arg': json.dumps({
                    'path': remote_path,
                    'mode': 'overwrite',
                    'autorename': False,
                    'mute': False
                }),
                'Content-Type': 'application/octet-stream'
            }

            file_size = os.path.getsize(file_path)
            self._log_info(f"Dropbox upload: {filename} ({file_size/1024:.1f}KB) -> {remote_path}")

            with open(file_path, 'rb') as f:
                response = requests.post(
                    'https://content.dropboxapi.com/2/files/upload',
                    headers=headers,
                    data=f,
                    timeout=120
                )

            if response.status_code == 200:
                result = response.json()
                self._log_info(f"Dropbox upload OK: {result.get('name', filename)} ({result.get('size', 0)/1024:.1f}KB)")
                return True
            else:
                error_msg = "Unknown error"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error_summary', str(response.status_code))
                except Exception:
                    error_msg = f"HTTP {response.status_code}"
                self._log_error(f"Dropbox upload failed: {error_msg}")
                return False

        except requests.exceptions.ConnectionError:
            self._log_error("No internet connection for Dropbox backup")
            return False
        except requests.exceptions.Timeout:
            self._log_error("Dropbox upload timed out")
            return False
        except Exception as ex:
            self._log_error(f"_upload_to_dropbox error: {ex}")
            return False

    def test_dropbox_connection(self):
        """Test Dropbox API connection and token validity.
        Returns (success: bool, message: str).
        """
        if not self.dropbox_token:
            return False, "No Dropbox token configured"

        try:
            headers = {
                'Authorization': f'Bearer {self.dropbox_token}',
                'Content-Type': ''
            }
            response = requests.post(
                'https://api.dropboxapi.com/2/users/get_current_account',
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                account = response.json()
                name = account.get('name', {}).get('display_name', 'Unknown')
                email = account.get('email', 'Unknown')
                return True, f"Connected to Dropbox: {name} ({email})"
            else:
                try:
                    error = response.json()
                    return False, f"Dropbox auth failed: {error.get('error_summary', response.status_code)}"
                except Exception:
                    return False, f"Dropbox auth failed: HTTP {response.status_code}"

        except requests.exceptions.ConnectionError:
            return False, "No internet connection"
        except requests.exceptions.Timeout:
            return False, "Connection timed out"
        except Exception as ex:
            return False, f"Error: {ex}"

    def stop(self):
        self.exiting = True

    def _log_info(self, msg):
        if self.logger:
            self.logger.insert_Info_APP_log(f"[Backup] {msg}")

    def _log_error(self, msg, ex=None):
        if self.logger:
            self.logger.insert_Error_APP_log(f"[Backup] {msg}", ex if ex else "")
