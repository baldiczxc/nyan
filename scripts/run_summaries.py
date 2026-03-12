import argparse
import datetime
import subprocess
import time
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

PYTHON_BIN = "/home/vlad/nyan/venv/bin/python"

def run_once(args, duration):
    print(f"[{datetime.datetime.now(MSK)}] Running summaries for {duration} hours...")
    try:
        subprocess.run([
            PYTHON_BIN,
            "-m", "nyan.topics",
            "--mongo-config-path", args.mongo_config_path,
            "--client-config-path", args.client_config_path,
            "--duration-hours", str(duration),
            "--max-news-count", "20",
            "--min-news-count", "3",
            "--auto"
        ], check=True)
    except Exception as e:
        print(f"Error running summary: {e}")

def get_next_run():
    now = datetime.datetime.now(MSK)

    today_times = [
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        now.replace(hour=8, minute=0, second=0, microsecond=0),
        now.replace(hour=16, minute=0, second=0, microsecond=0),
    ]

    future_times = [t for t in today_times if t > now]

    if future_times:
        return min(future_times)
    else:
        tomorrow = now + datetime.timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-config-path", type=str, required=True)
    parser.add_argument("--client-config-path", type=str, required=True)
    args = parser.parse_args()

    print("Scheduler started (MSK fixed schedule)")

    while True:
        next_run = get_next_run()
        sleep_seconds = (next_run - datetime.datetime.now(MSK)).total_seconds()

        print(f"Next run at {next_run}")
        time.sleep(max(0, sleep_seconds))

        # 00:00 → 8 часов
        # 08:00 → 8 часов
        # 16:00 → 8 часов + 24 часа
        if next_run.hour in (0, 8):
            run_once(args, 8)

        elif next_run.hour == 16:
            run_once(args, 8)
            run_once(args, 24)

if __name__ == '__main__':
    main()