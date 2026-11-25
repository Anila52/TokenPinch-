#!/usr/bin/env python3
import json
import struct
import sys

MAX_BYTES = 200_000

def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    size = struct.unpack("<I", raw)[0]
    if size <= 0 or size > MAX_BYTES:
        return {"action": "reject"}
    body = sys.stdin.buffer.read(size)
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {"action": "reject"}

def write_message(payload):
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(body)))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()

def handle(msg, compress, licence_ok):
    if not isinstance(msg, dict):
        return {"ok": False, "error": "bad_request"}
    action = msg.get("action")
    if action == "ping":
        return {"ok": True, "connected": True}
    if action != "compress":
        return {"ok": False, "error": "bad_request", "id": msg.get("id")}
    if not licence_ok():
        return {"ok": False, "error": "licence", "id": msg.get("id")}
    text = msg.get("text")
    if not isinstance(text, str):
        return {"ok": False, "error": "bad_request", "id": msg.get("id")}
    try:
        result = compress(text)
    except Exception:
        return {"ok": False, "error": "compress", "id": msg.get("id")}
    result["ok"] = True
    result["id"] = msg.get("id")
    return result

def product_root():
    here = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
    marker = __import__("os").path.join(here, "product_root.txt")
    if __import__("os").path.exists(marker):
        return open(marker, encoding="utf-8").read().strip()
    return __import__("os").path.dirname(__import__("os").path.dirname(here))

def main():
    sys.path.insert(0, product_root())
    import tokenpinch
    while True:
        msg = read_message()
        if msg is None:
            break
        write_message(handle(msg, tokenpinch.compress_draft, tokenpinch.browser_licence_ok))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
