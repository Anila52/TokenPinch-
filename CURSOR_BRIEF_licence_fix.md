# Cursor brief: TokenPinch licence fix (v1.0.0 → v1.1.0)

Paste this whole file into Cursor. The replacement licence code is in
`LICENCE_FIX_tested_code.py` (same folder). It has been tested against 10 scenarios
(new key, wrong key, device limits 1 and 3, copied licence file, 40 and 100 days offline,
refund, no internet at activation). All passed.

## Why
1. The shipped app contains a `gen-key` command, so anyone can make their own keys.
2. The key secret (`SECRET_SALT`) is readable inside the binary.
3. Keys are machine-based, but Gumroad sends a random key per sale, so Gumroad keys never work.

## Step 0: check which copy is newest (do this first)
`build_tokenpinch.sh` compiles **`~/.tokenpinch/tokenpinch.py`**, NOT
`~/Desktop/TokenPinch_Product_Files/tokenpinch.py`. Compare the two and work on the newest.
Then change the PyInstaller line in the build script to point at the copy you edited.
Don't keep two diverging copies.

## Changes to tokenpinch.py
1. Delete these two constants near the top:
   - `LICENSE_FILE = os.path.join(INSTALL_DIR, "license.key")`
   - `SECRET_SALT = "TokenPinchCommercialShieldV1_SecureHashKey"`
2. Keep `get_hardware_uuid()` exactly as it is.
3. Delete the old `generate_local_license_key()` and `verify_license()` functions.
   In their place, paste the whole block from `LICENCE_FIX_tested_code.py`
   (the block must sit AFTER `get_hardware_uuid()` and BEFORE `# Ensure CSV exists`).
4. In that block, fill in:
   - `GUMROAD_PRODUCT_ID` = the product ID from Gumroad (product settings → License key section).
   - `SUPPORT_EMAIL` = the support email address.
5. In `main()`:
   - remove the two help lines for `get-id` and `gen-key`
   - remove the whole `# Bypass verification for local license administrative commands`
     section (the `get-id` and `gen-key` branches).
   - Leave `verify_license()` where it is, before the commands run.
6. Change the version text `v1.0.0` to `v1.1.0` (banner) and `CFBundleShortVersionString` in the build script.

## Changes to build_tokenpinch.sh
- Before the PyInstaller step add: `pip3 install certifi`
  (secure connection certificates for the Gumroad check). Add `--hidden-import certifi` to the PyInstaller command.
- Point PyInstaller at the right source file (see Step 0).

## Gumroad setup this depends on
Version names must contain the device count, e.g. `Personal — 1 device`,
`Professional — 3 devices`, `Studio — 10 devices`. The app reads the number from the name.

## Test after building (on the Mac)
1. Delete `~/.tokenpinch/license.json` if it exists, then run `./tokenpinch shrink somefile.py`. It should ask for a key.
2. Enter a wrong key → "wasn't recognised".
3. Make a 100%-off Gumroad test purchase of Personal, enter that key → "activated (1-device licence)".
4. Run again → no prompt.
5. `./tokenpinch gen-key x` → must say "Unknown subcommand".
6. Run `strings tokenpinch | grep -i SecureHashKey` → must print nothing.

## Do NOT upload to Gumroad
`license.key`, `license.json`, `spend_audit.csv`, `dashboard.html`, `tokenpinch.py`, the build script or these brief files.
Upload only `TokenPinch.dmg` and the zipped `tokenpinch` file.

## Known limits (be honest in support)
- No licence check inside a downloadable app is uncrackable. This stops free key-making and casual sharing.
- Moving a licence to a new Mac: lower the key's use count by one in Gumroad (needs your private
  Gumroad token; never put it in the app, GitHub or the website), then the customer activates again.
