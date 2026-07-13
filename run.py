from src.app import App
from sys import platform
import sys
import time
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
                    app.read_data()
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
