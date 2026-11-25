import importlib.util
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("tokenpinch", os.path.join(ROOT, "tokenpinch.py"))
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)
host_spec = importlib.util.spec_from_file_location("tp_host", os.path.join(ROOT, "browser", "host", "host.py"))
host = importlib.util.module_from_spec(host_spec)
host_spec.loader.exec_module(host)


def test_compress_preserves_meaning_and_counts_tokens():
    draft = "Do not  delete this.\n\n\n> quoted  line\n\nhello    there\n```python\ndef target(n):\n    return n\n```\n"
    out = tp.compress_draft(draft)
    assert "Do not  delete this." in out["text"]
    assert "> quoted  line" in out["text"]
    assert "def target(n):\n    return n" in out["text"]
    assert "hello there" in out["text"]
    assert out["tokens_before"] == tp.count_tokens(draft)[0]
    assert out["tokens_after"] == tp.count_tokens(out["text"])[0]
    assert out["tokens_after"] < out["tokens_before"]
    assert out["counter"] == "tiktoken"
    assert "hello    there" not in out["text"]


def test_compress_does_not_touch_clipboard(monkeypatch):
    def fail(_text):
        raise AssertionError("clipboard")
    monkeypatch.setattr(tp, "copy_to_clipboard", fail)
    assert tp.compress_draft("hello    there")["text"] == "hello there"


def test_host_hides_draft_when_licence_is_missing():
    secret = "draft text that must not be echoed"
    resp = host.handle({"action": "compress", "text": secret, "id": "1"}, tp.compress_draft, lambda: False)
    assert resp["ok"] is False
    assert resp["error"] == "licence"
    assert secret not in json.dumps(resp)


def test_host_roundtrip_returns_counts_only_in_the_reply():
    resp = host.handle({"action": "compress", "text": "hello    there", "id": "9"}, tp.compress_draft, lambda: True)
    assert resp["ok"] is True
    assert resp["text"] == "hello there"
    assert resp["tokens_after"] < resp["tokens_before"]
    packed = struct.pack("<I", 4) + b"nope"
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "browser", "host", "host.py")], input=packed, capture_output=True)
    assert proc.returncode == 0
    size = struct.unpack("<I", proc.stdout[:4])[0]
    body = json.loads(proc.stdout[4:4 + size])
    assert body["ok"] is False
