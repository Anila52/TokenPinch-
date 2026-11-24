# 🤏 TokenPinch — Save Up to 90% of Your LLM Prompt Costs

**TokenPinch** is a high-performance, native developer utility for macOS, Windows, and Android designed to optimize, scrub, and compress LLM prompts. By intercepting, caching, and intelligently slicing your context locally, TokenPinch cuts your OpenAI & Anthropic API expenses by up to 90% while keeping your prompts lean and secure.

---

## 🚀 Key Features

* **🌳 AST Recursive Slicing:** Dynamically parses Python and TypeScript files to extract only the target class or function along with all its local dependents and referenced imports, cutting out massive source-file bloat.
* **🧠 LRU-Evicting SQLite Prompt Cache:** A lightweight, high-performance SQLite cache capped at `1,000` entries (under `<10MB` database footprint) with exact and fuzzy matching.
* **⚖️ Sliding Window Budgeting:** Automatically compresses lower-relevance code blocks into skeleton signatures and structures when context bounds exceed your customized budget.
* **🌐 Claude-3.5 Failover Proxy Routing:** Local gateway automatically catches OpenAI upstream rate-limits (`429`) or server errors (`5xx`), translates the payloads on-the-fly, and failovers to Anthropic's Claude 3.5 with full streaming/SSE support.
* **🖥️ Beautiful TUI Dashboard:** Run `tokenpinch status` for an interactive, colorized ANSI terminal dashboard showing total cash saved, active proxy runs, and an ASCII runway bar meter.
* **🔌 Integration Guides:** Built-in templates for instant setup with VS Code, Cursor IDE, Python scripts, and Node.js (`tokenpinch client <client>`).
* **🛡️ 100% Encrypted & Secure Native Binary:** The core engine is fully compiled to native machine/assembly code, protecting intellectual property and preventing decompiling across macOS, Windows, and Android.

---

## 📦 What's Included in the Box

1. **Standalone CLI Binary (`tokenpinch`):** Blazing fast native binary for terminal execution and scripting.
2. **macOS Status Tray Menu App (`TokenPinch.app`):** Elegant background execution with live toggles and beautiful native desktop notifications.
3. **Windows & Android Clients:** Lightweight, native clients for seamless cross-platform support.
4. **Professional Installer (`TokenPinch.dmg`):** A standard, signed macOS Disk Image for seamless installation.
5. **Decompiler Plugins:** Pre-bundled optimization scripts for IDA Pro and Ghidra.

---

## 🛠️ Quick Start

### 1. Installation
Install the appropriate package for your platform (e.g. run the `.dmg` on Mac, `.msi` on Windows, or install the `.apk` on Android).

### 2. Configure Your Gateway
Launch the Tray Menu App or start the daemon:
```bash
tokenpinch gateway --port 8799
```

### 3. Native Status Checking
Run the TUI dashboard to view live analytics:
```bash
tokenpinch status
```

---

## 🔒 Security & Code Integrity

TokenPinch is built with absolute security in mind. The core engine is fully compiled to native machine assembly using **Cython** (for Mac/Linux) and optimized compilation tools for other platforms so your intellectual property remains private and secure from code-copying or standard byte-decompilation.

---

## 🛒 Purchase & Support

TokenPinch is available for purchase on [Gumroad](https://gumroad.com/l/cyroew). Keep your AI budgets lightweight and secure today!
