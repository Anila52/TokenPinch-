# 🤏 TokenPinch — Cut input tokens by up to 91% on large code files

**TokenPinch** runs on a Mac, a Windows PC, and Android. It turns a large code file into a compact skeleton before you paste it into Claude, ChatGPT or Cursor. In tests, a large file went from about 4,000 input tokens to about 350. That is an input-token cut on that file, not a cut of the whole API bill.

---

## 🚀 Key Features

* **🌳 AST Recursive Slicing:** Dynamically parses Python and TypeScript files to extract only the target class or function along with all its local dependents and referenced imports, cutting out massive source-file bloat.
* **🧠 LRU-Evicting SQLite Prompt Cache:** A lightweight, high-performance SQLite cache capped at `1,000` entries (under `<10MB` database footprint) with exact and fuzzy matching.
* **⚖️ Sliding Window Budgeting:** Automatically compresses lower-relevance code blocks into skeleton signatures and structures when context bounds exceed your customized budget.
* **🌐 Claude-3.5 Failover Proxy Routing:** Local gateway automatically catches OpenAI upstream rate-limits (`429`) or server errors (`5xx`), translates the payloads on-the-fly, and failovers to Anthropic's Claude 3.5 with full streaming/SSE support.
* **🖥️ Beautiful TUI Dashboard:** Run `tokenpinch status` for an interactive, colorized ANSI terminal dashboard showing total cash saved, active proxy runs, and an ASCII runway bar meter.
* **🔌 Integration Guides:** Built-in templates for instant setup with VS Code, Cursor IDE, Python scripts, and Node.js (`tokenpinch client <client>`).
* **🛡️ On your machine:** Your code stays on the Mac, Windows PC, or Android phone. TokenPinch goes online only to check the licence.

---

## 📦 What's Included in the Box

1. **`TokenPinch.dmg`:** the Apple Silicon app. It is not notarised yet. The `tokenpinch` command is this same app.
2. **IDA Pro and Ghidra plugins:** in that disk image.
3. **Windows and Android:** not in the download.

---

## Install

Open `TokenPinch.dmg`, drag TokenPinch into Applications, and open it. The first open asks for the licence key in Terminal. That same open starts the menu bar, and the menu bar starts the gateway. After that, `tokenpinch shrink yourfile.py`.

---

## 🔒 Security & Code Integrity

Files are processed on this Mac. The only network call is the licence check.

---

## 🛒 Purchase & Support

TokenPinch is available for purchase on [Gumroad](https://gumroad.com/l/cyroew). Keep your AI budgets lightweight and secure today!
