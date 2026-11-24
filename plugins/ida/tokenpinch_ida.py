import os
import sys
import tempfile
import subprocess
import idaapi
import idc
import ida_funcs
import ida_hexrays

class TokenPinchSqueezeHandler(idaapi.action_handler_t):
    def __init__(self):
        idaapi.action_handler_t.__init__(self)

    def activate(self, ctx):
        ea = idc.get_screen_ea()
        func = ida_funcs.get_func(ea)
        if not func:
            print("TokenPinch: Please place cursor inside a function.")
            return 1
            
        depth = 2
        budget = 8000
        
        cfunc = ida_hexrays.decompile(func)
        if not cfunc:
            print("TokenPinch: Failed to decompile current function.")
            return 1
            
        decompiled_chunks = [str(cfunc)]
        visited = {func.start_ea}
        
        callees = []
        for line in str(cfunc).splitlines():
            import re
            for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", line):
                name = m.group(1)
                callee_ea = idc.get_name_ea_simple(name)
                if callee_ea != idc.BADADDR and callee_ea not in visited:
                    visited.add(callee_ea)
                    callee_func = ida_funcs.get_func(callee_ea)
                    if callee_func:
                        callees.append(callee_func)
                        
        for f in callees[:10]:
            try:
                cf = ida_hexrays.decompile(f)
                if cf:
                    decompiled_chunks.append(str(cf))
            except Exception:
                pass
                
        combined_code = "\n\n".join(decompiled_chunks)
        
        temp_fd, temp_path = tempfile.mkstemp(suffix=".c")
        try:
            with os.fdopen(temp_fd, "w") as f:
                f.write(combined_code)
                
            binary_path = "tokenpinch"
            for path in ["/usr/local/bin/tokenpinch", "/Applications/TokenPinch.app/Contents/MacOS/tokenpinch_bin"]:
                if os.path.exists(path):
                    binary_path = path
                    break
                    
            cmd = [binary_path, "squeeze", temp_path, "--budget", str(budget)]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            
            print("--- TokenPinch Squeeze Result ---")
            print(stdout.decode("utf-8", errors="ignore"))
            if stderr:
                print("Errors:", stderr.decode("utf-8", errors="ignore"))
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return 1

    def update(self, ctx):
        return idaapi.AST_ENABLE_ALWAYS

ACTION_NAME = "tokenpinch:squeeze"
ACTION_LABEL = "TokenPinch Squeeze to clipboard"
HOTKEY = "Ctrl-Shift-T"

class TokenPinchPlugin(idaapi.plugin_t):
    flags = idaapi.PLUGIN_UNL
    comment = "TokenPinch IDA Plugin"
    help = "TokenPinch Squeeze Integration"
    wanted_name = "TokenPinch"
    wanted_hotkey = ""

    def init(self):
        if not ida_hexrays.init_hexrays_plugin():
            return idaapi.PLUGIN_SKIP
            
        action_desc = idaapi.action_desc_t(
            ACTION_NAME,
            ACTION_LABEL,
            TokenPinchSqueezeHandler(),
            HOTKEY
        )
        idaapi.register_action(action_desc)
        idaapi.attach_action_to_menu("Tools/TokenPinch", ACTION_NAME, idaapi.SETMENU_APP)
        print("TokenPinch: Plugin loaded (Ctrl-Shift-T)")
        return idaapi.PLUGIN_KEEP

    def run(self, arg):
        pass

    def term(self):
        idaapi.unregister_action(ACTION_NAME)

def PLUGIN_ENTRY():
    return TokenPinchPlugin()
