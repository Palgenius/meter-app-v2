"""
TCP Socket Server for meter-app-v2. v2.1.0

Provides real-time data broadcast to connected clients (Bluetooth app, hub-agent).
Clients connect to TCP localhost:5555 and receive newline-delimited JSON messages.

Protocol:
  {"type": "reading", "data": {...}}\n
  {"type": "validation", "data": {...}}\n
  {"type": "alert", "data": {...}}\n
  {"type": "health", "data": {...}}\n
"""

import socket
import json
import threading
import time


class SocketServer:
    """TCP socket server that broadcasts meter data to connected clients."""

    def __init__(self, host="127.0.0.1", port=5555, logger=None):
        self.host = host
        self.port = port
        self.logger = logger
        self._server_socket = None
        self._clients = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        # Health state (set by app.py via set_health())
        self._health_data = {
            "meter_connected": False,
            "meter_type": "unknown",
            "last_reading_age_ms": -1,
            "push_enabled": False,
            "last_push_success": False,
            "last_push_time": None,
            "pending_push_count": 0,
            "uptime_seconds": 0,
            "cpu_temp": 0.0,
            "memory_percent": 0.0,
        }
        self._health_start_time = time.time()

        # Command callbacks (set by app.py)
        self._config_read_callback = None
        self._config_write_callback = None
        self._reload_callback = None
        self._ct_read_callback = None
        self._ct_write_callback = None

        # Stored state for on-demand queries
        self._last_reading = None
        self._last_validation = None

    def start(self):
        """Start the TCP server in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Shutdown the server and close all connections."""
        self._running = False
        try:
            if self._server_socket:
                self._server_socket.close()
        except Exception:
            pass
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()

    def _run(self):
        """Main server loop — accept connections and broadcast health every 30s."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        try:
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
            self._log(f"Socket server listening on {self.host}:{self.port}")
        except OSError as e:
            self._log(f"Socket server bind failed: {e}")
            self._running = False
            return

        last_health_broadcast = 0
        while self._running:
            # Accept new clients
            try:
                client_sock, addr = self._server_socket.accept()
                client_sock.settimeout(60.0)
                with self._lock:
                    self._clients.append(client_sock)
                self._log(f"Client connected from {addr} (total: {len(self._clients)})")
                t = threading.Thread(target=self._handle_client, args=(client_sock, addr), daemon=True)
                t.start()
            except socket.timeout:
                pass
            except OSError:
                if self._running:
                    self._log("Socket server accept error")
                break

            # Phase 2 addition: Broadcast health every 30 seconds
            now = time.time()
            if now - last_health_broadcast >= 30:
                last_health_broadcast = now
                self._health_data["uptime_seconds"] = int(now - self._health_start_time)
                self.send_health(self._health_data)

    def _handle_client(self, client_sock, addr):
        """Handle a single client connection — process commands and keep alive."""
        try:
            while self._running:
                try:
                    data = client_sock.recv(4096)
                    if not data:
                        break  # client disconnected

                    # Process incoming commands from hub-agent
                    text = data.decode('utf-8', errors='replace').strip()
                    for line in text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                            msg_type = msg.get("type", "")
                            if msg_type == "command":
                                response = self._handle_command(msg)
                                if response:
                                    # Map to command_result format that hub-agent meterClient expects
                                    cmd_result = {
                                        "type": "command_result",
                                        "action": msg.get("action", ""),
                                        "cmdId": msg.get("id", 0),
                                        "success": response.get("status") == "ok",
                                        "data": response.get("data"),
                                        "error": response.get("message"),
                                    }
                                    response_bytes = json.dumps(cmd_result).encode('utf-8') + b"\n"
                                    client_sock.sendall(response_bytes)
                        except json.JSONDecodeError:
                            pass

                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break
        except Exception:
            pass
        finally:
            with self._lock:
                if client_sock in self._clients:
                    self._clients.remove(client_sock)
            try:
                client_sock.close()
            except Exception:
                pass
            self._log(f"Client disconnected from {addr} (total: {len(self._clients)})")

    def send_reading(self, data):
        """Broadcast a reading message to all connected clients."""
        self._last_reading = data  # store for on-demand queries
        self._broadcast({"type": "reading", "data": data})

    def send_validation(self, data):
        """Broadcast a validation message to all connected clients."""
        self._last_validation = data  # store for on-demand queries
        self._broadcast({"type": "validation", "data": data})

    def send_alert(self, data):
        """Broadcast an alert message to all connected clients."""
        self._broadcast({"type": "alert", "data": data})

    def send_health(self, data):
        """Broadcast a health status message to all connected clients."""
        self._broadcast({"type": "health", "data": data})

    def set_health(self, **kwargs):
        """Update health state. Called by app.py to share system status.
        
        kwargs: meter_connected, meter_type, last_reading_age_ms,
                push_enabled, last_push_success, last_push_time,
                pending_push_count, cpu_temp, memory_percent
        """
        self._health_data.update(kwargs)

    def _broadcast(self, message):
        """Send a JSON message to all connected clients (thread-safe)."""
        try:
            raw = json.dumps(message, default=str) + "\n"
            raw_bytes = raw.encode('utf-8')
        except Exception as e:
            self._log(f"Broadcast encode error: {e}")
            return

        dead_clients = []
        with self._lock:
            for client in self._clients:
                try:
                    client.sendall(raw_bytes)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    dead_clients.append(client)
                except Exception:
                    dead_clients.append(client)

            for client in dead_clients:
                try:
                    self._clients.remove(client)
                    client.close()
                except Exception:
                    pass

    def client_count(self):
        """Return number of connected clients."""
        with self._lock:
            return len(self._clients)

    def _handle_command(self, msg):
        """Handle incoming commands from hub-agent (config read/write/reload).
        
        Expected format:
        {"type": "command", "id": 123, "action": "config_read|config_write|reload|status"}
        """
        cmd_id = msg.get("id", 0)
        action = msg.get("action", "")
        params = msg.get("params", msg.get("data", {}))  # meterClient sends 'data', hub-agent sends 'params'

        self._log(f"Command received: {action} (id={cmd_id})")

        try:
            if action == "status":
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok", "data": self._health_data}

            elif action == "last_reading":
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok", "data": {
                    "reading": self._last_reading,
                    "validation": self._last_validation,
                }}
            elif action == "ct_read":
                # Read CT values from all meters
                ct_data = {}
                if self._ct_read_callback:
                    ct_data = self._ct_read_callback()
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok", "data": ct_data}

            elif action == "ct_write":
                # Write CT values: params = {"meter_id": "1", "channel": 1, "value": 200}
                success = False
                if self._ct_write_callback:
                    success = self._ct_write_callback(params)
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok" if success else "error"}

            elif action == "ct_read_all":
                # Read all CT values for all meters
                ct_data = {}
                if self._ct_read_callback:
                    ct_data = self._ct_read_callback()
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok", "data": ct_data}
            elif action == "config_read":
                config_data = {}
                if self._config_read_callback:
                    config_data = self._config_read_callback()
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok", "data": config_data}

            elif action == "config_write":
                success = False
                if self._config_write_callback:
                    success = self._config_write_callback(params)
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok" if success else "error"}

            elif action == "reload":
                success = False
                if self._reload_callback:
                    success = self._reload_callback()
                return {"type": "response", "action": action, "id": cmd_id, "status": "ok" if success else "error"}

            else:
                return {"type": "response", "action": action, "id": cmd_id, "status": "error", "message": f"Unknown action: {action}"}

        except Exception as ex:
            self._log(f"Command error: {ex}")
            return {"type": "response", "action": action if 'action' in dir() else "unknown", "id": cmd_id, "status": "error", "message": str(ex)}

    def set_command_callbacks(self, config_read=None, config_write=None, reload=None):
        """Register callbacks for handling commands from hub-agent.
        
        config_read: callable() -> dict
        config_write: callable(params) -> bool
        reload: callable() -> bool
        """
        self._config_read_callback = config_read
        self._config_write_callback = config_write
        self._reload_callback = reload

    def _log(self, msg):
        if self.logger:
            self.logger.insert_Info_APP_log(f"[Socket] {msg}")
