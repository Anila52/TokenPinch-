#!/usr/bin/env python3
import json
import os
import stat
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_ID = "okinokbmeonplpacjnkiejnpnkkpalnd"
FIREFOX_ID = "tokenpinch@clausetenconsulting.com"
HOME = os.path.expanduser("~")

WINDOWS_KEYS = (
    r"Software\Google\Chrome\NativeMessagingHosts\com.tokenpinch.browser",
    r"Software\Microsoft\Edge\NativeMessagingHosts\com.tokenpinch.browser",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.tokenpinch.browser",
    r"Software\Chromium\NativeMessagingHosts\com.tokenpinch.browser",
)


def current_platform():
    prefix = os.environ.get("PREFIX", "")
    if os.environ.get("ANDROID_ROOT") or "/com.termux" in prefix:
        return "android"
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


def host_dir():
    if current_platform() == "windows":
        base = os.environ.get("LOCALAPPDATA") or HOME
        return os.path.join(base, "TokenPinch")
    return os.path.join(HOME, "Library/Application Support/TokenPinch")


def chrome_manifest(host_path):
    return {
        "name": "com.tokenpinch.browser",
        "description": "TokenPinch draft compression",
        "path": host_path,
        "type": "stdio",
        "allowed_origins": ["chrome-extension://%s/" % EXT_ID],
    }


def firefox_manifest(host_path):
    return {
        "name": "com.tokenpinch.browser",
        "description": "TokenPinch draft compression",
        "path": host_path,
        "type": "stdio",
        "allowed_extensions": [FIREFOX_ID],
    }


def write_host(install_dir):
    os.makedirs(install_dir, exist_ok=True)
    src = os.path.join(ROOT, "browser", "host", "host.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    body = body.replace("#!/usr/bin/env python3", "#!%s" % sys.executable, 1)
    host_py = os.path.join(install_dir, "host.py")
    with open(host_py, "w", encoding="utf-8") as fh:
        fh.write(body)
    with open(os.path.join(install_dir, "product_root.txt"), "w", encoding="utf-8") as fh:
        fh.write(ROOT + "\n")
    if current_platform() == "windows":
        launcher = os.path.join(install_dir, "tokenpinch-host.cmd")
        with open(launcher, "w", encoding="utf-8", newline="") as fh:
            fh.write("@echo off\r\n\"%s\" -u \"%s\"\r\n" % (sys.executable, host_py))
        return launcher
    launcher = os.path.join(install_dir, "tokenpinch-host")
    with open(launcher, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IEXEC)
    return launcher


def install():
    if current_platform() == "android":
        print("Android Chrome cannot load a native-messaging companion.")
        print("Use tokenpinch autostart so the gateway starts at Termux boot.")
        return 0
    install_dir = host_dir()
    host_path = write_host(install_dir)
    manifest = chrome_manifest(host_path)
    written = []
    if current_platform() == "windows":
        manifest_path = os.path.join(install_dir, "com.tokenpinch.browser.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        import winreg
        for key in WINDOWS_KEYS:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
                winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, manifest_path)
            written.append(key)
        appdata = os.environ.get("APPDATA") or HOME
        fox = os.path.join(appdata, "Mozilla", "NativeMessagingHosts")
        os.makedirs(fox, exist_ok=True)
        fox_path = os.path.join(fox, "com.tokenpinch.browser.json")
        with open(fox_path, "w", encoding="utf-8") as fh:
            json.dump(firefox_manifest(host_path), fh, indent=2)
        written.append(fox_path)
    else:
        folders = {
            "Google Chrome": os.path.join(HOME, "Library/Application Support/Google/Chrome/NativeMessagingHosts"),
            "Microsoft Edge": os.path.join(HOME, "Library/Application Support/Microsoft Edge/NativeMessagingHosts"),
            "Brave": os.path.join(HOME, "Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"),
            "Chromium": os.path.join(HOME, "Library/Application Support/Chromium/NativeMessagingHosts"),
        }
        for name, folder in folders.items():
            try:
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, "com.tokenpinch.browser.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, indent=2)
                written.append(path)
            except OSError as exc:
                print("%s: %s" % (name, exc))
        fox = os.path.join(HOME, ".mozilla/native-messaging-hosts")
        try:
            os.makedirs(fox, exist_ok=True)
            path = os.path.join(fox, "com.tokenpinch.browser.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(firefox_manifest(host_path), fh, indent=2)
            written.append(path)
        except OSError as exc:
            print("Firefox: %s" % exc)
    print("Extension: %s" % os.path.join(ROOT, "browser", "extension"))
    print("Extension id: %s" % EXT_ID)
    print("Load that folder once in each browser: Developer mode, Load unpacked.")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(install())
