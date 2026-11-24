# ======================= LICENCE (Gumroad) =======================
import hashlib
import ssl
import time
import urllib.request
import urllib.parse
import urllib.error

GUMROAD_PRODUCT_ID = "PASTE_YOUR_GUMROAD_PRODUCT_ID_HERE"
GUMROAD_VERIFY_URL = "https://api.gumroad.com/v2/licenses/verify"
SUPPORT_EMAIL = "PASTE_YOUR_SUPPORT_EMAIL_HERE"
LICENSE_FILE = os.path.join(INSTALL_DIR, "license.json")
RECHECK_DAYS = 30          # quietly re-check with Gumroad this often (when online)
OFFLINE_GRACE_DAYS = 90    # keep working offline this long without a re-check


def device_fingerprint():
    """One-way SHA-256 of this machine's hardware ID (the raw ID is never stored)."""
    return hashlib.sha256(get_hardware_uuid().encode("utf-8")).hexdigest()


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def gumroad_verify(license_key, count_use):
    """Asks Gumroad about a key. Raises an exception if there is no internet."""
    data = urllib.parse.urlencode({
        "product_id": GUMROAD_PRODUCT_ID,
        "license_key": license_key,
        "increment_uses_count": "true" if count_use else "false",
    }).encode("utf-8")
    req = urllib.request.Request(GUMROAD_VERIFY_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"success": False, "message": f"HTTP {e.code}"}


def device_limit_for(purchase):
    """Reads the device limit from the Gumroad version name, e.g. 'Professional - 3 devices'."""
    text = f"{purchase.get('variants', '')} {purchase.get('product_name', '')}"
    m = re.search(r"(\d+)\s*device", text, re.IGNORECASE)
    return int(m.group(1)) if m else 1


def purchase_is_active(purchase):
    return not (purchase.get("refunded") or purchase.get("chargebacked") or purchase.get("disputed"))


def _load_license():
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_license(lic):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(lic, f)
    try:
        os.chmod(LICENSE_FILE, 0o600)
    except Exception:
        pass


def _forget_license():
    try:
        os.remove(LICENSE_FILE)
    except Exception:
        pass


def activate_interactively():
    print("==================================================")
    print("🔒 TokenPinch Licence Activation")
    print("==================================================")
    print("Paste the licence key from your Gumroad receipt.")
    print("Activation needs the internet once; after that TokenPinch works offline.")
    print("==================================================")
    try:
        if not sys.stdin.isatty():
            print("Error: run TokenPinch in Terminal once to activate your licence.")
            sys.exit(1)
        key = input("> ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nActivation cancelled.")
        sys.exit(1)
    if not key:
        print("\nNo key entered. Activation cancelled.")
        sys.exit(1)

    try:
        # 1. Look first without using up a device slot.
        check = gumroad_verify(key, count_use=False)
    except Exception:
        print("\n❌ Couldn't reach the licence server. Check your internet connection and try again.")
        sys.exit(1)
    if not check.get("success"):
        print("\n❌ That licence key wasn't recognised. Check it matches your receipt exactly.")
        sys.exit(1)
    purchase = check.get("purchase", {})
    if not purchase_is_active(purchase):
        print("\n❌ This licence has been refunded or disabled.")
        sys.exit(1)
    limit = device_limit_for(purchase)
    if int(check.get("uses", 0)) >= limit:
        plural = "device" if limit == 1 else "devices"
        print(f"\n❌ This licence is already active on {limit} {plural}, the most your plan allows.")
        print(f"To move it to this Mac, email {SUPPORT_EMAIL} with your order number.")
        sys.exit(1)

    try:
        # 2. Claim one device slot.
        result = gumroad_verify(key, count_use=True)
    except Exception:
        print("\n❌ Lost the internet connection during activation. Please try again.")
        sys.exit(1)
    if not result.get("success"):
        print("\n❌ Activation failed. Please try again or contact support.")
        sys.exit(1)

    now = time.time()
    _save_license({"key": key, "device": device_fingerprint(), "limit": limit,
                   "activated_at": now, "checked_at": now})
    print(f"\n✅ Success! TokenPinch is activated on this device ({limit}-device licence).")
    return True


def verify_license():
    """Checks the saved licence; asks for a key if there isn't a valid one."""
    lic = _load_license()
    if lic and lic.get("key") and lic.get("device") == device_fingerprint():
        now = time.time()
        age_days = (now - float(lic.get("checked_at", 0))) / 86400
        if age_days < RECHECK_DAYS:
            return True
        try:
            result = gumroad_verify(lic["key"], count_use=False)
        except Exception:
            if age_days < OFFLINE_GRACE_DAYS:
                return True
            print("TokenPinch needs to connect to the internet once to re-check your licence.")
            sys.exit(1)
        if result.get("success") and purchase_is_active(result.get("purchase", {})):
            lic["checked_at"] = now
            _save_license(lic)
            return True
        _forget_license()
        print(f"❌ This licence is no longer valid (refunded or disabled). Contact {SUPPORT_EMAIL}.")
        sys.exit(1)
    return activate_interactively()
# ===================== END LICENCE (Gumroad) =====================
