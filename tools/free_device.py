#!/usr/bin/env python3
"""Free one Gumroad device slot. The token is read from the environment only."""
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tokenpinch


def main():
    token = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
    if not token or len(sys.argv) != 2:
        print("Set GUMROAD_ACCESS_TOKEN and pass the licence key.")
        return 1
    data = urllib.parse.urlencode({
        "access_token": token,
        "product_id": tokenpinch.GUMROAD_PRODUCT_ID,
        "license_key": sys.argv[1],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.gumroad.com/v2/licenses/decrement_uses_count", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15, context=tokenpinch._ssl_context()) as response:
        body = response.read().decode("utf-8")
    if token in body:
        print("Gumroad returned the token. Nothing was printed.")
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
