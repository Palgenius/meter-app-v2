from src.app import App
from sys import platform
import sys
import time
import threading
from signal import signal, SIGINT
from src import VERSION

# ── Handle --detect flag ───────────────────────────────────────
if "--detect" in sys.argv:
    from detect_meters import main as detect_main
    detect_main()
    sys.exit(0)

# ── Signal handling ──────────────────────────────────────────────
exiting = False

def handler(signal_received, frame):
    global exiting
    print('SIGINT, SIGQUIT or SIGTSTP detected. Exiting gracefully')
    exiting = True
    app.is_closing()

signal(SIGINT, handler)
if platform != "win32":
    from signal import SIGTSTP, SIGQUIT
    signal(SIGQUIT, handler)
    signal(SIGTSTP, handler)

# ── Main ─────────────────────────────────────────────────────────
print(f"[main] meter-app-v2 v{VERSION} starting")

MAX_RESTARTS = 5
restart_count = 0
CYCLE_WATCHDOG_TIMEOUT = 300  # 5 min — if a single read_data() cycle takes longer, something is stuck

while not exiting and restart_count < MAX_RESTARTS:
    try:
        app = App()

        timer = 0
        redetect_timer = 0
        REDETECT_INTERVAL = 30  # seconds between scan attempts when no meters

        while not exiting:
            if time.time() - timer > app.get_request_time():
                timer = time.time()
                if app.has_meters():
                    # Run read_data in a thread with watchdog timeout
                    # This prevents the main loop from hanging indefinitely
                    # if modbus/rescan blocks.
                    result = [None]
                    def _cycle():
                        try:
                            app.read_data()
                            result[0] = True
                        except Exception as ex:
                            result[0] = ex
                    cycle_thread = threading.Thread(target=_cycle, daemon=True)
                    cycle_thread.start()
                    cycle_thread.join(timeout=CYCLE_WATCHDOG_TIMEOUT)
                    if cycle_thread.is_alive():
                        # Cycle is stuck — log and continue to next cycle
                        print(f"[main] WATCHDOG: read_data() stuck for {CYCLE_WATCHDOG_TIMEOUT}s, "
                              f"skipping to next cycle (thread will die in background)")
                        # Don't reset timer — let next iteration try again immediately
                        timer = 0
                    elif result[0] is not None and result[0] is not True:
                        # Cycle threw an exception
                        print(f"[main] read_data() error: {result[0]}")
                else:
                    # No meters — try to detect periodically
                    if time.time() - redetect_timer > REDETECT_INTERVAL:
                        redetect_timer = time.time()
                        app.try_redetect()
            time.sleep(0.5)

        print("[main] Program exiting by user")
        app.close()
        break

    except Exception as ex:
        restart_count += 1
        print(f"[main] CRASH #{restart_count}: {ex}")
        try:
            app.close()
        except Exception:
            pass
        if restart_count < MAX_RESTARTS:
            delay = min(10 * restart_count, 60)
            print(f"[main] Restarting in {delay}s...")
            time.sleep(delay)
        else:
            print(f"[main] Too many crashes ({MAX_RESTARTS}), giving up")

exit(0)
