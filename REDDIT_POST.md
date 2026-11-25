# 🤏 TokenPinch — Cut input tokens by up to 91% on large code files

Hey everyone,

If you are a developer using LLM APIs (OpenAI, Anthropic, etc.) daily, you've probably noticed how fast your monthly bills run up. A huge portion of that cost isn't even the core answer—it's the massive context bloat. Every time we paste a file, our prompts get loaded with boilerplate, unused functions, massive relative imports, and system messages.

I wanted to solve this permanently, so I built **TokenPinch**. It runs on a Mac, a Windows PC, and Android, and turns a large code file into a compact skeleton on the machine. In my tests a large file went from about 4,000 input tokens to about 350, which is up to a 91% cut of the input tokens on that file. The AI's reply is not reduced.

### 🎯 What it does under the hood:
1. **🌳 AST Recursive Slicing:** Instead of pasting an entire 2,000-line file, TokenPinch dynamically parses the AST, extracts *only* the specific class/function you are targeting, and recursively resolves and appends only its local dependents and referenced imports.
2. **🧠 SQLite Fuzzy Prompt Cache:** Exact and fuzzy semantic prompt caching capped at 1,000 entries using an LRU-eviction policy (keeps database size <10MB). 
3. **⚖️ Sliding Window Budgeting:** Automatically skeletonizes less relevant code blocks (leaving only method signatures) when context limits are reached.
4. **🌐 Claude-3.5 Failover Proxy Routing:** If OpenAI rate-limits you (429) or goes down (5xx), the proxy interceptor automatically translates the payload format, routes it to Anthropic Claude-3.5, and parses it back seamlessly (including emulated streaming SSE).
5. **🖥️ Terminal TUI Dashboard:** Run `tokenpinch status` in your shell for a gorgeous, colorized ANSI dashboard showing Total Cash Saved, Active Runs, and an ASCII runway meter.

### On your machine
Mac, Windows, and Android. Your files stay on the machine. TokenPinch goes online only to check the licence.

### 📦 What's included:
* Native macOS Status Tray Menu App (`TokenPinch.app`) with native system notification integration.
* Ultra-fast standalone CLI (`tokenpinch`) for scripting.
* Pre-built decompiler plugins for IDA Pro and Ghidra.
* Standard professional installer DMG (`TokenPinch.dmg`).

### 🛠️ Where to get it:
- **Product Page:** https://gumroad.com/l/cyroew

I'd love to hear your thoughts, feature requests, or feedback on how you manage your prompt context bloat!
