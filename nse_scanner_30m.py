from pathlib import Path

import nse_scanner as scanner


# Keep every 30-minute setting local to this process so the 4-hour NSE scanner
# and its alert state remain independent.
scanner.TIMEFRAME = "30m"
scanner.SOURCE_INTERVAL = "30m"
scanner.SOURCE_PERIOD = "60d"
scanner.STATE_FILE = Path(__file__).with_name("nse_alert_state_30m.json")
scanner.MAX_DISTANCE_PCT = 0.5
scanner.ALERT_COOLDOWN_SECONDS = 30 * 60
scanner.SIGNAL_ALERT_COOLDOWN_SECONDS = 30 * 60


if __name__ == "__main__":
    scanner.main()
