# Squeeze the current function and its callees to clipboard.
# @category TokenPinch
# @menupath Tools.TokenPinch.Squeeze to clipboard
# @keybinding Ctrl-Shift-T

import os
import sys
import tempfile
import subprocess
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

def get_callees_recursive(func, depth, visited=None):
    if visited is None:
        visited = set()
    if depth == 0 or func is None or func.getName() in visited:
        return []
    visited.add(func.getName())
    callees = []
    # Get all functions called by this function
    for called_func in func.getCalledFunctions(monitor):
        if called_func.getName() not in visited:
            callees.append(called_func)
            callees.extend(get_callees_recursive(called_func, depth - 1, visited))
    return callees

def decompile_func(decompiler, func):
    results = decompiler.decompileFunction(func, 30, ConsoleTaskMonitor())
    if results and results.decompileCompleted():
        return results.getDecompiledFunction().getC()
    return ""

# Get the current active function containing currentAddress
func = getFunctionContaining(currentAddress)
if not func:
    popup("Please place your cursor inside a function to squeeze.")
else:
    # Query depth and budget using simple input dialogs
    depth_str = askString("TokenPinch Squeeze", "Decompilation Callee Depth:", "2")
    budget_str = askString("TokenPinch Squeeze", "Token Budget:", "8000")
    
    depth = int(depth_str) if depth_str and depth_str.isdigit() else 2
    budget = int(budget_str) if budget_str and budget_str.isdigit() else 8000
    
    # Initialize decompiler
    decompiler = DecompInterface()
    decompiler.initialize(currentProgram)
    
    # Get all target functions (first is active, then callees)
    callees = get_callees_recursive(func, depth)
    all_funcs = [func] + callees
    
    # Decompile all
    decompiled_chunks = []
    for f in all_funcs:
        code = decompile_func(decompiler, f)
        if code:
            decompiled_chunks.append(code)
            
    combined_code = "\n\n".join(decompiled_chunks)
    
    # Write to temp file
    temp_fd, temp_path = tempfile.mkstemp(suffix=".c")
    try:
        with os.fdopen(temp_fd, "w") as f:
            f.write(combined_code)
            
        # Locate tokenpinch binary
        binary_path = "tokenpinch" # assume on PATH
        for path in ["/usr/local/bin/tokenpinch", "/Applications/TokenPinch.app/Contents/MacOS/tokenpinch_bin"]:
            if os.path.exists(path):
                binary_path = path
                break
                
        # Run command
        cmd = [binary_path, "squeeze", temp_path, "--budget", str(budget)]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        # Display output in console
        print("--- TokenPinch Squeeze Result ---")
        print(stdout.decode("utf-8", errors="ignore"))
        if stderr:
            print("Errors:", stderr.decode("utf-8", errors="ignore"))
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass
