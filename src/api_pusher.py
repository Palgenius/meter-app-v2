"""
API Pusher — sends 15-min samples to server. v2.0.0

Same JSON format as api15pusher/API_15_PUSH.py for backward compatibility.
Runs as a background thread, retries on failure.
"""

import json
import time
import requests


class APIPusher:
    """Sends pending 15-min readings to the remote API server."""

    def __init__(self, storage, config, logger=None, socket_server=None):
        self.storage = storage
        self.config = config
        self.logger = logger
        self.socket_server = socket_server
        self.enabled = config.getConfigVal("api_push_enabled", False)
        self.url = config.getConfigVal("api_push_url", "https://tools.ampenergy.io/data")
        self.api_push_time = config.getConfigVal("api_push_time", ["03", "18", "33", "48"])
        self.interval = config.getConfigVal("api_push_interval", 30)
        self.exiting = False

        # Push status tracking (for health broadcast to Bluetooth app)
        self.last_push_success = False
        self.last_push_time = None  # timestamp of last successful push
        self.last_push_payload = None  # last 15-min sample pushed to cloud
        self._consecutive_failures = 0  # track for alert threshold

    def push_thread(self):
        """Background thread: check for pending 15-min records and push them.
        
        Retries failed records every retry_interval (default 5 min)
        so they don't stay stuck until next app restart.
        """
        self._log_info("API Pusher thread starting")
        retry_interval = self.config.getConfigVal("push_retry_interval", 300)  # 5 min
        last_retry_time = time.time()
        while not self.exiting:
            if not self.enabled:
                time.sleep(60)
                continue

            try:
                # Periodically reset failed records back to pending for retry
                if time.time() - last_retry_time > retry_interval:
                    last_retry_time = time.time()
                    self.retry_failed()

                pending = self.storage.get_pending_15min(limit=20)
                if pending:
                    for record in pending:
                        if self.exiting:
                            break
                        success = self._send_record(record)
                        if success:
                            self.storage.mark_15min_sent(record["id"])
                            # Alert recovery if we had consecutive failures
                            if self._consecutive_failures >= 3:
                                self._send_alert("INFO", f"API push recovered after {self._consecutive_failures} failures")
                            self._consecutive_failures = 0  # reset on success
                            self._log_info(f"Sent 15min record id={record['id']} ts={record['datetime_str']}")
                        else:
                            self.storage.mark_15min_failed(record["id"])
                            self._consecutive_failures += 1
                            self._log_error(f"Failed to send record id={record['id']}, will retry")
                            # Alert hub-agent after 3 consecutive failures
                            if self._consecutive_failures == 3:
                                self._send_alert("WARNING", f"API push failed {self._consecutive_failures} times. Last error: check logs")
                            break  # stop trying more, wait for next cycle
                        time.sleep(0.5)
                    time.sleep(5)
                else:
                    time.sleep(self.interval)
            except Exception as ex:
                self._log_error("push_thread error", ex)
                time.sleep(self.interval)

    def _send_record(self, record):
        """Send a single 15-min record to the API.
        
        Format matches api15pusher for server compatibility.
        """
        try:
            channels_data = json.loads(record["channels_json"])
            grid_data = json.loads(record["grid_json"])
            totals_data = json.loads(record["totals_json"])
            channel_count = record["channel_count"]

            payload = {
                "reading_time": record["datetime_str"],
                "panelid": record["panel_id"],
                "channel_count": channel_count,
                "total": [
                    grid_data.get("v", 0),
                    totals_data.get("ti", 0),
                    totals_data.get("tp", 0),
                    totals_data.get("tq", 0),
                    totals_data.get("ts", 0),
                    totals_data.get("tpf", 0),
                    totals_data.get("tae", 0),
                    totals_data.get("tre", 0)
                ],
                "channels": self._format_channels(channels_data, grid_data)
            }

            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json"
            }

            response = requests.post(self.url, data=json.dumps(payload), headers=headers, timeout=15)
            if response.status_code == 200:
                # Check if the response body indicates an upstream error
                try:
                    body = response.json()
                    # Server wraps upstream status in statusCode field
                    upstream_status = body.get("statusCode", 200)
                    if upstream_status >= 400:
                        # Check for duplicate key — already on server (not a real failure)
                        resp_text = str(response.text)
                        if '23505' in resp_text or 'already exists' in resp_text:
                            self._log_info('Record already on server, marking as sent')
                            self.last_push_success = True
                            self.last_push_time = time.time()
                            return True
                        self._log_error(f"API upstream error: statusCode={upstream_status}")
                        self.last_push_success = False
                        return False
                    # Also check azurestatus inside nested body
                    inner = body.get("body", "")
                    if isinstance(inner, str) and "azurestatus" in inner:
                        import re
                        m = re.search(r'"azurestatus"\s*:\s*(\d+)', inner)
                        if m and int(m.group(1)) >= 400:
                            # Check for duplicate key — already pushed to server
                            resp_text = str(response.text)
                            if '23505' in resp_text or 'already exists' in resp_text:
                                self._log_info('Record already on server, marking as sent')
                                self.last_push_success = True
                                self.last_push_time = time.time()
                                return True
                            self._log_error(f"API upstream error: azurestatus={m.group(1)}")
                            self.last_push_success = False
                            return False
                except (ValueError, KeyError):
                    pass  # Not JSON — treat as success
                self._log_info(f"API response OK: {response.json()}")
                self.last_push_success = True
                self.last_push_time = time.time()
                # Save last push payload for health broadcast
                self.last_push_payload = {
                    'reading_time': record['datetime_str'],
                    'total_power': totals_data.get('tp', 0),
                    'total_current': totals_data.get('ti', 0),
                    'total_energy': totals_data.get('tae', 0),
                    'frequency': grid_data.get('f', 0),
                    'power_factor': totals_data.get('tpf', 0),
                    'channel_count': channel_count,
                }
                return True
            else:
                self._log_error(f"API returned status {response.status_code}")
                self.last_push_success = False
                return False

        except requests.exceptions.ConnectionError:
            self._log_error("No internet connection")
            self.last_push_success = False
            return False
        except requests.exceptions.Timeout:
            self._log_error("API request timed out")
            self.last_push_success = False
            return False
        except Exception as ex:
            self._log_error("_send_record error", ex)
            return False

    def _format_channels(self, channels_data, grid_data):
        """Format channels list for API compatibility.
        
        Each channel: [voltage, channel_num, phase_letter, I, P, Q, S, PF, AE, RE]
        """
        result = []
        for ch in channels_data:
            ch_num = ch["ch"]
            phase_idx = (ch_num - 1) % 3
            phase_letter = ['a', 'b', 'c'][phase_idx]
            voltage = ch.get("v", grid_data.get(['av', 'bv', 'cv'][phase_idx], 0))

            result.append([
                voltage,
                ch_num,
                phase_letter,
                ch.get("i", 0),
                ch.get("p", 0),
                ch.get("q", 0),
                ch.get("s", 0),
                ch.get("pf", 0),
                ch.get("ae", 0),
                ch.get("re", 0)
            ])
        return result

    def retry_failed(self):
        """Reset failed records back to pending for retry."""
        try:
            self.storage._conn.execute(
                "UPDATE readings_15min SET send_status='pending' WHERE send_status='failed'"
            )
            self.storage._conn.commit()
        except Exception as ex:
            self._log_error("retry_failed error", ex)

    def _send_alert(self, level, message):
        """Send an alert to hub-agent via TCP socket server."""
        if self.socket_server:
            self.socket_server.send_alert({
                "level": level,
                "meter_id": "api_pusher",
                "meter_type": "system",
                "message": message
            })

    def stop(self):
        self.exiting = True

    def _log_info(self, msg):
        if self.logger:
            self.logger.insert_Info_APP_log(f"[APIPusher] {msg}")

    def _log_error(self, msg, ex=None):
        if self.logger:
            self.logger.insert_Error_APP_log(f"[APIPusher] {msg}", ex if ex else "")
