"""Seat watcher for UVA Hoos' List (run-once version for GitHub Actions).

Each run checks every section below once and sends you an ntfy alert when a
section has a seat. It remembers in seat_state.json whether it already told you,
so you get one alert per opening instead of one per run.

The enrollment endpoint returns a list of {"enrolled", "waitlist", "t"} records,
one per change. We use the newest one.

The ntfy topic is read from the NTFY_TOPIC environment variable (a GitHub secret),
so it never appears in this file.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---- CONFIG: edit these ----
TERM_CODE = "1272"  # Spring 2027, as seen in the Hoos' List request URL
SECTIONS = {
    # label you'll recognize: class number, and capacity as shown on Hoos' List.
    # The endpoint doesn't return capacity, so update it here if seats are added.
    "ECE 2300-001 Applied Circuits": {"number": "15841", "capacity": 60},
}
# ----------------------------

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
STATE_FILE = Path("seat_state.json")
HEADERS = {"User-Agent": "personal-seat-watcher (student project)"}
API_URL = "https://hooslist.virginia.edu/ClassSchedule/_GetLatestClassEnrollments"


def latest_enrollment(records):
    """Return (enrolled, waitlist, timestamp) for the newest record, or None.

    Records that share a timestamp aren't reliably ordered (the real data has
    cases like 8 then 7 at the same second), so among the newest ones we take
    the lowest enrolled count. That errs toward alerting you.
    """
    if not records:
        return None
    newest = max(r["t"] for r in records)  # ISO timestamps sort as strings
    tied = [r for r in records if r["t"] == newest]
    best = min(tied, key=lambda r: r["enrolled"])
    return best["enrolled"], best["waitlist"], newest


def fetch_records(class_number: str):
    resp = requests.get(API_URL, headers=HEADERS, timeout=30,
                        params={"termCode": TERM_CODE, "classNumber": class_number})
    resp.raise_for_status()
    return resp.json()


def notify(message: str) -> None:
    resp = requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"),
                         headers={"Title": "Seat opened", "Priority": "high"}, timeout=30)
    resp.raise_for_status()


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def run() -> int:
    """Check every section once. Returns 0 if all went fine, 1 if anything failed."""
    if not NTFY_TOPIC:
        print("NTFY_TOPIC is not set. Add it as a repository secret named NTFY_TOPIC.")
        return 1

    state = load_state()  # label -> was it open last time we looked
    failed = False
    for i, (label, cfg) in enumerate(SECTIONS.items()):
        number, cap = cfg["number"], cfg["capacity"]
        if i:
            time.sleep(2)  # be gentle with the site
        try:
            result = latest_enrollment(fetch_records(number))
            if result is None:
                print(f"{label}: no enrollment records returned "
                      "(wrong class number or term code, or the site changed?)")
                failed = True
                continue

            enrolled, waitlist, as_of = result
            now_open = enrolled < cap
            if now_open and not state.get(label, False):
                notify(f"{label} ({number}): {enrolled}/{cap} as of {as_of}. Go to SIS now.")
            state[label] = now_open  # only updated after a successful alert
            print(f"{label}: {enrolled}/{cap} (waitlist {waitlist}, data as of {as_of}) "
                  f"{'OPEN' if now_open else 'full'}")
        except Exception as e:  # a failed check is retried on the next run
            print(f"{label}: check failed ({e})")
            failed = True

    STATE_FILE.write_text(json.dumps(state))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
