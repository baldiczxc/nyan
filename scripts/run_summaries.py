import os
import argparse
import datetime
import subprocess
import time

def run_once(args, duration):
    print(f"[{datetime.datetime.now()}] Running summaries for {duration} hours...")
    try:
        subprocess.run([
            "python", "-m", "nyan.topics",
            "--mongo-config-path", args.mongo_config_path,
            "--client-config-path", args.client_config_path,
            "--duration-hours", str(duration),
            "--max-news-count", "20",
            "--min-news-count", "3",
            "--auto"
        ], check=True)
    except Exception as e:
        print(f"Error running summary: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-config-path", type=str, required=True)
    parser.add_argument("--client-config-path", type=str, required=True)
    args = parser.parse_args()

    last_8h = time.time()
    last_24h = time.time()
    
    # Run once at startup
    run_once(args, 8)
    run_once(args, 24)

    print("Summaries scheduler started.")
    while True:
        time.sleep(60)
        now = time.time()
        
        if now - last_8h >= 8 * 3600:
            run_once(args, 8)
            last_8h = now
            
        if now - last_24h >= 24 * 3600:
            run_once(args, 24)
            last_24h = now

if __name__ == '__main__':
    main()
