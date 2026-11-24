You are working on TokenPinch, a closed-source Python CLI (single file tokenpinch.py, built into a macOS binary by build_tokenpinch.sh with PyInstaller). Build version 1.2.0. The owner has no coding experience: explain what you did in plain English at the end.

## Ground rules
- First, confirm the licence fix from CURSOR_BRIEF_licence_fix.md is already in place (no `gen-key`, no `SECRET_SALT`, a Gumroad `verify_license()` block). If it isn't, stop and tell me.
- Work on the source file build_tokenpinch.sh actually compiles. If there are two copies (~/.tokenpinch/tokenpinch.py and the Desktop one), tell me which is newer and use that one.
- Don't touch the licence block (between "LICENCE (Gumroad)" and "END LICENCE").
- Keep every existing command working exactly as now: shrink, slice, squeeze, auto-heal, dashboard. Add to the code; don't restructure or rename it.
- Don't delete files. Never put API keys, tokens or passwords in code. Only read ANTHROPIC_API_KEY from the environment and never save it.
- Network use: only the existing Gumroad licence check, plus the optional Anthropic token count in Feature A. Everything else must work fully offline.
- You may split new code into modules in a `tokenpinch_lib/` package next to tokenpinch.py if that's cleaner. Update the PyInstaller command so they're bundled.

## Feature A: real token counts (make the savings provable)
1. Replace every rough token estimate (e.g. len/4) with a real count using `tiktoken` (`o200k_base` encoding), offline.
   - tiktoken normally downloads its encoding file on first use. Bundle the encoding file inside the app: set TIKTOKEN_CACHE_DIR to a bundled folder (use sys._MEIPASS when frozen) and add it to PyInstaller with --add-data, so counting works with no internet.
2. Optional exact Claude count: if the environment variable ANTHROPIC_API_KEY is set and the user passes `--exact`, call Anthropic's token counting endpoint (POST https://api.anthropic.com/v1/messages/count_tokens) for both the original and the shrunk text. Fall back to tiktoken silently if it fails.
3. Prices: move the per-token prices into ~/.tokenpinch/prices.json. Create it with sensible defaults on first run, labelled with the date they were set, so the user can update them without a rebuild.
4. Every command prints: original tokens, new tokens, % saved, estimated $ saved, and which counter was used (tiktoken or claude-exact). Log the counter used in spend_audit.csv as a new column at the END. Existing CSV files must still load.
5. Dashboard: show the counting method, total tokens saved, total $ saved, and a per-command breakdown.

## Feature B: secret scrubbing (on by default)
1. Add a scrubber that runs on ALL output before it's printed or copied to the clipboard (shrink, slice, squeeze, auto-heal).
2. Detect and replace with `[REDACTED:<TYPE>]`:
   - AWS access keys
   - GitHub tokens (ghp_, gho_, github_pat_)
   - OpenAI and Anthropic keys (sk-..., sk-ant-...)
   - Slack tokens (xox...)
   - Stripe keys (sk_live_, rk_live_)
   - Google API keys (AIza...)
   - private key blocks (-----BEGIN ... PRIVATE KEY-----)
   - JWTs
   - connection strings with passwords (scheme://user:pass@host)
   - assignments like password/secret/token/api_key = "..."
   - email addresses
   - private IP addresses (10.x, 172.16–31.x, 192.168.x)
3. After each run, print a one-line summary, e.g. "Scrubbed 3 secrets (2 API keys, 1 email)". Never print the secret itself.
4. Add a `--no-scrub` flag to turn it off.
5. Add a standalone command: `tokenpinch scrub <file>`, which writes the scrubbed text to the clipboard.

## Feature C: reverse-engineering power tools (the niche)
1. Extend `squeeze`:
   - `tokenpinch squeeze <file> --budget 8000` keeps the most important functions until the token budget is reached. Order: the target function first, then functions it calls (breadth-first by call depth), then the rest. Say what was dropped.
   - `tokenpinch squeeze <folder>` squeezes every .c / .txt pseudocode file in a folder into one combined, budget-limited prompt.
2. Ghidra plugin: plugins/ghidra/TokenPinchSqueeze.py (Ghidra script, works with Ghidra's Python/PyGhidra).
   - Decompile the current function, plus its callees to a depth set in a dialog (default 2).
   - Write the output to a temp file and run `tokenpinch squeeze <tempfile> --budget <N>` (find the tokenpinch binary on PATH or at /Applications/TokenPinch.app/Contents/MacOS/tokenpinch_bin).
   - Show the result summary in Ghidra's console.
   - Menu path: Tools > TokenPinch > Squeeze to clipboard.
3. IDA plugin: plugins/ida/tokenpinch_ida.py (IDAPython, IDA 9.x, needs Hex-Rays).
   - Same behaviour as the Ghidra plugin, hotkey Ctrl-Shift-T.
4. plugins/README.md: plain-English install steps for each plugin, plus a note that the plugins need an activated TokenPinch licence.
5. Plugins must not contain any licence logic. They only call the tokenpinch binary, which checks the licence itself.

## Housekeeping
- Version 1.2.0 in the banner and in Info.plist (build script).
- Update the help text for the new command and flags.
- build_tokenpinch.sh: pip3 install tiktoken certifi; add the hidden imports, the --add-data for the tiktoken encoding file, and the tokenpinch_lib package. Copy the plugins folder into the DMG next to the app.
- Keep the build Apple Silicon (arm64) for now.

## Tests (required before you say it's done)
Create tests/ with pytest and sample fixtures. Cover:
- shrink, slice and squeeze give the same output as v1.1 on the sample files, apart from the new token lines.
- the scrubber catches every secret type above and leaves normal code alone (include a false-positive test with ordinary variable names).
- `--no-scrub` turns it off.
- the `--budget` limit is respected and the dropped-functions note is correct.
- token counting works with the network switched off (mock or block sockets).
- the old spend_audit.csv format still loads in the dashboard.
- the licence block is unchanged (compare it byte-for-byte with LICENCE_FIX_tested_code.py, apart from the two filled-in placeholders).
Run the tests, run build_tokenpinch.sh, then run the built binary on a sample file. Show me the results.

## Report back in plain English
- what changed
- what you tested and the results
- anything you couldn't test (e.g. the Ghidra or IDA plugins without those apps installed)
- anything I need to do next
