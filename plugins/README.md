# TokenPinch Decompiler Squeeze Plugins

Integrate TokenPinch directly into Ghidra or IDA Pro to instantly optimize decompiled function context for LLMs with your offline node-locked token savings engine!

> ⚠️ **Prerequisite:** The plugins require a locally installed and activated TokenPinch license. The plugins themselves contain no license validation code; they call the `tokenpinch` binary, which validates the license itself.

---

## 🐉 Ghidra Plugin Installation
1. Open Ghidra.
2. Open the **Script Manager** (`Window > Script Manager`).
3. Click the **Script Directories** icon in the toolbar (top-right).
4. Add the `plugins/ghidra/` folder from this distribution.
5. Search for `TokenPinchSqueeze.py` in the script list.
6. Check the box to add it to the **Tools > TokenPinch > Squeeze to clipboard** menu.
7. Use the assigned hotkey `Ctrl-Shift-T` or select it from the menu inside any function definition to automatically decompile, squeeze to a custom token budget, and copy it directly to your clipboard!

---

## 🔍 IDA Pro Plugin Installation (IDA 9.x / Hex-Rays)
1. Locate your IDA Pro installation plugins folder (usually `C:\Program Files\IDA Pro 9.0\plugins\` on Windows or `/Applications/IDA Pro 9.0/plugins/` on macOS).
2. Copy `plugins/ida/tokenpinch_ida.py` directly into that folder.
3. Restart IDA Pro.
4. When inside any Hex-Rays pseudocode view, simply hit **`Ctrl-Shift-T`** to squeeze the function and its callees recursively into a budget-limited, optimized prompt ready for copying.
