"""
Runs alert_checker.check_and_send_alerts() automatically every few
hours, in a background daemon thread, so the Flask app doesn't have to
block a request to do it.

daemon=True means this thread dies automatically when the main Flask
process stops - no orphaned background process left running.
"""

import threading
import time

from alert_checker import check_and_send_alerts

# How often to re-check tracked products, in hours.
CHECK_INTERVAL_HOURS = 6

_scheduler_started = False


def _run_loop():
    while True:
        try:
            check_and_send_alerts()
        except Exception as e:
            # A bad run should never kill the background thread - just
            # log it and try again next cycle.
            print(f"[Scheduler] Unexpected error during check: {e}")

        time.sleep(CHECK_INTERVAL_HOURS * 60 * 60)


def start_scheduler():
    """
    Starts the background thread exactly once, even if this gets
    imported/called more than once (Flask's reloader can otherwise
    trigger this twice in debug mode).
    """
    global _scheduler_started

    if _scheduler_started:
        return

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    _scheduler_started = True

    print(
        f"[Scheduler] Started - checking pending alerts every "
        f"{CHECK_INTERVAL_HOURS} hour(s)."
    )
