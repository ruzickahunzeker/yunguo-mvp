import argparse
import time
from app.core.config import get_settings
from app.services.monitoring import run_once

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    while True:
        run_once()
        if args.once:
            return
        time.sleep(get_settings().monitor_interval_seconds)

if __name__ == '__main__':
    main()
