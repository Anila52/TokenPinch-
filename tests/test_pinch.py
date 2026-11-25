import importlib.util
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")

spec = importlib.util.spec_from_file_location("tokenpinch", os.path.join(ROOT, "tokenpinch.py"))
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_licence_uses_the_live_product_and_version_names():
    assert tp.GUMROAD_PRODUCT_ID == "cyroew"
    assert tp.SUPPORT_EMAIL == "contact@clausetenconsulting.com"
    assert "PASTE_YOUR" not in tp.GUMROAD_PRODUCT_ID
    assert tp.device_limit_for({"variants": "Personal — 1 device"}) == 1
    assert tp.device_limit_for({"variants": "Professional — 3 devices"}) == 3
    assert tp.device_limit_for({"product_name": "Studio — 10 devices"}) == 10
    assert tp.device_limit_for({}) == 1


def test_autostart_files_cover_each_platform():
    mac = tp.autostart_files("macos", "/Users/me", "/opt/tokenpinch", "/usr/bin/python3")
    assert any(path.endswith("com.tokenpinch.gateway.plist") for path in mac)
    assert any("gateway --port 8799" in text and "install_host.py" in text for text in mac.values())
    win = tp.autostart_files("windows", r"C:\Users\me", r"C:\TokenPinch", r"C:\Python\python.exe")
    assert any(path.endswith("TokenPinch.cmd") for path in win)
    assert any("gateway --port 8799" in text for text in win.values())
    android = tp.autostart_files("android", "/data/data/com.termux/files/home", "/data/tokenpinch", "python3")
    assert any(path.endswith(".termux/boot/tokenpinch.sh") or path.endswith(".termux\\boot\\tokenpinch.sh") or "/.termux/boot/tokenpinch.sh" in path for path in android)
    assert any("Android Chrome cannot load" in text and "gateway --port 8799" in text for text in android.values())
    assert tp.autostart_files("linux", "/home/me", "/opt/tokenpinch", "python3") == {}


def test_host_platform_windows_and_android(monkeypatch):
    monkeypatch.setattr(tp.sys, "platform", "win32", raising=False)
    monkeypatch.delenv("ANDROID_ROOT", raising=False)
    monkeypatch.setenv("PREFIX", "")
    assert tp.host_platform() == "windows"
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    assert tp.host_platform() == "android"


def test_slice_keeps_target_and_helper():
    src = _read("sample.py")
    sliced = tp.ast_recursive_slice(src, "target")
    scores = tp.pinch_scores(src, sliced)
    assert "def target" in sliced and "def helper" in sliced
    assert "return helper(n) * 2" in sliced
    assert "return x + 1" not in sliced
    assert "unused" not in sliced
    assert scores["counter"] == "tiktoken"
    assert scores["tokens_after"] < scores["tokens_before"]
    assert scores["bodies_kept"] is False


def test_slice_finds_method_inside_class():
    src = _read("sample.py")
    sliced = tp.ast_recursive_slice(src, "method")
    assert "def method" in sliced
    assert "return helper(n)" in sliced
    assert "def helper" in sliced
    assert "return x + 1" not in sliced
    assert "def unused" not in sliced
    assert tp.ast_recursive_slice(src, "Box.method") == sliced


def test_shrink_saves_tokens_and_drops_the_answer():
    src = _read("sample.py")
    shrunk = tp.shrink_source(src, ".py")
    scores = tp.pinch_scores(src, shrunk)
    assert scores["tokens_after"] < scores["tokens_before"]
    assert scores["bodies_kept"] is False
    assert "..." in shrunk


def test_typescript_slice_keeps_callee():
    src = _read("sample.ts")
    sliced = tp.ts_recursive_slice(src, "target")
    assert "function target" in sliced
    assert "return helper(n) * 2" in sliced
    assert "function helper" in sliced
    assert "return x + 1" not in sliced
    assert "function unused" not in sliced
    method = tp.ts_recursive_slice(src, "method")
    assert "method" in method and "function helper" in method
    assert "return helper(n)" in method
    assert "return x + 1" not in method
    assert "function unused" not in method


def test_gateway_budget_records_both_scores():
    messages = json.loads(_read("gateway_messages.json"))
    full = "\n".join(m["content"] for m in messages)
    kept, changed = tp.auto_slice_prompt(json.loads(_read("gateway_messages.json")), max_budget=10_000)
    assert changed is False
    kept_text = "\n".join(m["content"] for m in kept if isinstance(m.get("content"), str))
    assert tp.pinch_scores(full, kept_text)["bodies_kept"] is True
    pinched, changed = tp.auto_slice_prompt(json.loads(_read("gateway_messages.json")), max_budget=1)
    assert changed is True
    pinched_text = "\n".join(m["content"] for m in pinched if isinstance(m.get("content"), str))
    scores = tp.pinch_scores(full, pinched_text)
    assert scores["tokens_after"] < scores["tokens_before"]
    assert scores["bodies_kept"] is False


def test_scrub_fixture():
    text = _read("secrets.txt")
    out, summary = tp.scrub_text(text)
    assert "ada@example.com" not in out
    assert "10.1.2.3" not in out
    assert "sk-proj-abcdefghijklmnopqrst" not in out
    assert "REDACTED" in out
    assert summary


def test_exact_cache_ignores_near_match(tmp_path, monkeypatch):
    db = str(tmp_path / "cache.sqlite")
    monkeypatch.setattr(tp, "CACHE_DB_PATH", db)
    tp.init_cache_db()
    shared = " ".join(f"w{i}" for i in range(24))
    tp.save_prompt_cache(shared + " apple", {"answer": "stored"}, False)
    assert tp.lookup_prompt_cache(shared + " banana") is None
    stamped = "fix the bug\nrequest_id: abc-123\n2026-11-25T11:00:00Z"
    other = "fix the bug\nrequest_id: xyz-999\n2026-11-25T12:00:00Z\n"
    tp.save_prompt_cache(stamped, {"answer": "same"}, False)
    hit = tp.lookup_prompt_cache(other)
    assert hit is not None
    assert hit[2] == "Exact Cache Hit"
    assert hit[0]["answer"] == "same"
    assert tp.failover_decision(429, 0) == "retry"
    assert tp.failover_decision(429, 1) == "forward_error"
    assert tp.failover_decision(503, 0) == "failover"


def test_ceiling_fixture(tmp_path, monkeypatch):
    raw = json.loads(_read("ceiling_request.json"))
    system = raw["messages"][0]["content"]
    body, before, after, *_rest = tp.optimize_payload("/v1/chat/completions", json.dumps(raw).encode(), scrub_active=False)
    data = json.loads(body)
    assert data["messages"][0]["content"] == system
    assert data["max_tokens"] == 1024
    assert [t["function"]["name"] for t in data["tools"]] == ["read_file"]
    assert sum(1 for m in data["messages"] if m.get("role") == "tool") == 1
    text = ""
    images = 0
    for msg in data["messages"]:
        content = msg.get("content")
        if isinstance(content, list):
            images += sum(1 for item in content if isinstance(item, dict) and item.get("type") == "image_url")
        text += "\n" + tp._text_of(content)
    assert images == 0
    assert "return helper(n) * 2" in text
    assert "return x + 1" not in text
    assert "def unused" not in text
    assert after < before
    db = str(tmp_path / "cache.sqlite")
    monkeypatch.setattr(tp, "CACHE_DB_PATH", db)
    tp.init_cache_db()
    sent = tp.sent_prompt_text(body)
    tp.save_prompt_cache(sent, {"answer": "4"}, False)
    hit = tp.lookup_prompt_cache(sent)
    assert hit[2] == "Exact Cache Hit"
    anth = {"model": "claude", "max_tokens": 4096, "system": "STABLE SYSTEM " + ("rule " * 40), "messages": [{"role": "user", "content": "hi"}]}
    abody, abefore, aafter, *_a = tp.optimize_payload("/v1/messages", json.dumps(anth).encode(), scrub_active=False)
    assert json.loads(abody)["system"] == anth["system"]
    assert json.loads(abody)["max_tokens"] == 1024
    assert abefore > 10
    assert aafter == abefore
    small = {"model": "m", "max_tokens": 256, "messages": [{"role": "user", "content": "hi"}]}
    assert json.loads(tp.optimize_payload("/v1/chat/completions", json.dumps(small).encode(), scrub_active=False)[0])["max_tokens"] == 256
    usage = tp.read_usage('{"usage":{"prompt_tokens":100,"completion_tokens":800}}')
    assert usage == {"prompt_tokens": 100, "completion_tokens": 800}
    assert tp.bill_from_usage(usage) == (100 * 3 + 800 * 15) / 1000000.0
