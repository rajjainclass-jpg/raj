"""RAJ Enterprise Windows Device Agent — Phase 2 metadata-only prototype.

This program never downloads customer documents or sends print commands.
It demonstrates enrollment, device authentication, license checks and queue visibility.
Use in an approved staging environment only.
"""
import argparse
import getpass
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit


def normalize_base(value):
    base = value.strip().rstrip("/")
    parsed = urlsplit(base)
    local = parsed.hostname in ("127.0.0.1", "localhost")
    if not parsed.netloc or not (parsed.scheme == "https" or (local and parsed.scheme == "http")):
        raise ValueError("Only HTTPS servers (or localhost for development) are allowed")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError("Invalid server URL")
    return base


def request_json(base, path, *, method="GET", token=None, payload=None):
    url = base + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        # Avoid logging credentials, token or raw server payload.
        raise RuntimeError("Server rejected request (HTTP " + str(err.code) + ")") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Could not connect to the server securely") from None


def enroll(base, label):
    invitation = getpass.getpass("One-time device enrollment code: ").strip()
    if not invitation:
        raise ValueError("Enrollment code required")
    response = request_json(base, "/api/v2/devices/enroll", method="POST",
                            payload={"invitation": invitation, "display_name": label})
    print("Device registered:", response["device_id"])
    print("Store your token securely. It will not be saved on this computer by this prototype.")
    print("Device token (visible once):", response["device_token"])


def poll(base, interval):
    token = getpass.getpass("Registered device token: ").strip()
    if not token:
        raise ValueError("Device token required")
    identity = request_json(base, "/api/v2/devices/me", token=token)
    print("Authorized device:", identity["display_name"], "| Shop ID:", identity["shop_id"])
    print("Monitoring queue metadata only; no documents will be downloaded and no printing will occur.")
    print("Press Ctrl+C to stop.")
    while True:
        try:
            data = request_json(base, "/api/v2/devices/queue", token=token)
            print("Jobs currently marked printing:", len(data["jobs"]))
            for job in data["jobs"]:
                print("  -", job["order_id"], "|", job["pages"], "pages ×", job["copies"],
                      "|", job["color_mode"], "| file available:", job["document_available"])
        except RuntimeError as err:
            print("Queue check failed:", err)
            print("If device was revoked or subscription expired, reauthorization is required.")
            break
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="RAJ Enterprise pilot Windows Agent — metadata only")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="HTTPS staging base URL")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--enroll", metavar="PRINTER_NAME", help="Enroll using one-time code")
    modes.add_argument("--poll", action="store_true", help="Read private device queue metadata")
    parser.add_argument("--interval", type=int, default=20, help="Queue check interval, minimum 10 s")
    args = parser.parse_args()
    try:
        base = normalize_base(args.server)
        if args.enroll:
            enroll(base, args.enroll)
        else:
            poll(base, max(args.interval, 10))
    except KeyboardInterrupt:
        print("\nStopped")
    except (RuntimeError, ValueError) as exc:
        print("Error:", exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
