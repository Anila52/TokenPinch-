#!/usr/bin/env python3
import sys
import os
import re
import ast
import json
import csv
import subprocess
import webbrowser
import sqlite3
from datetime import datetime

try:
    import rumps
except ImportError:
    rumps = None

# Setup paths
INSTALL_DIR = os.path.expanduser("~/.tokenpinch")
CSV_PATH = os.path.join(INSTALL_DIR, "spend_audit.csv")
HTML_PATH = os.path.join(INSTALL_DIR, "dashboard.html")

os.makedirs(INSTALL_DIR, exist_ok=True)

CACHE_DB_PATH = os.path.join(INSTALL_DIR, "tokenpinch_cache.db")

def init_cache_db():
    try:
        conn = sqlite3.connect(CACHE_DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompt_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_hash TEXT UNIQUE,
                original_prompt TEXT,
                normalized_words TEXT,
                response_json TEXT,
                is_stream INTEGER,
                created_at REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                tool TEXT,
                target TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                status TEXT,
                counter_used TEXT,
                system_tokens INTEGER DEFAULT 0,
                code_tokens INTEGER DEFAULT 0,
                prose_tokens INTEGER DEFAULT 0
            )
        """)
        try:
            cursor.execute("ALTER TABLE audit_logs ADD COLUMN system_tokens INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE audit_logs ADD COLUMN code_tokens INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE audit_logs ADD COLUMN prose_tokens INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception:
        pass

def load_env_file():
    """Locates and loads keys from local .env or .env.local files into os.environ."""
    paths = [
        os.path.join(INSTALL_DIR, ".env"),
        os.path.join(INSTALL_DIR, ".env.local"),
        ".env",
        ".env.local"
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            parts = line.split("=", 1)
                            key = parts[0].strip()
                            val = parts[1].strip().strip("'\"")
                            if key and val and key not in os.environ:
                                os.environ[key] = val
            except Exception:
                pass

# Load environmental configurations immediately
load_env_file()

# Initialize cache and logs DB immediately
init_cache_db()

def normalize_and_tokenize(text):
    text = text.lower()
    text = re.sub(r'[-_]', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    words = set(text.split())
    stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were', 'to', 'of', 'in', 'on', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'from', 'up', 'down', 'shrunk', 'slice', 'squeeze'}
    return words - stopwords

def fuzzy_match_similarity(words1, words2):
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)

def calculate_tfidf_similarity(prompt1, prompt2_list):
    import math
    if not prompt2_list:
        return []
    all_prompts = [prompt1] + prompt2_list
    tokenized = []
    for p in all_prompts:
        words = re.sub(r'[^\w\s]', ' ', p.lower()).split()
        tokenized.append(words)
    vocab = set()
    for words in tokenized:
        vocab.update(words)
    vocab = list(vocab)
    vocab_map = {word: idx for idx, word in enumerate(vocab)}
    if not vocab:
        return [(i, 0.0) for i in range(len(prompt2_list))]
    tfs = []
    for words in tokenized:
        doc_tf = {}
        for w in words:
            doc_tf[w] = doc_tf.get(w, 0) + 1
        total_words = len(words) or 1
        for w in doc_tf:
            doc_tf[w] = doc_tf[w] / total_words
        tfs.append(doc_tf)
    idf = {}
    total_docs = len(all_prompts)
    for word in vocab:
        doc_count = sum(1 for words in tokenized if word in words)
        idf[word] = math.log((1 + total_docs) / (1 + doc_count)) + 1
    vectors = []
    for doc_tf in tfs:
        vec = [0.0] * len(vocab)
        for word, tf_val in doc_tf.items():
            vec[vocab_map[word]] = tf_val * idf[word]
        vectors.append(vec)
    vec1 = vectors[0]
    mag1 = math.sqrt(sum(x*x for x in vec1))
    results = []
    for idx, vec2 in enumerate(vectors[1:]):
        mag2 = math.sqrt(sum(x*x for x in vec2))
        if mag1 == 0 or mag2 == 0:
            results.append((idx, 0.0))
            continue
        dot_product = sum(x*y for x, y in zip(vec1, vec2))
        similarity = dot_product / (mag1 * mag2)
        results.append((idx, similarity))
    return results

def lookup_prompt_cache(prompt_text):
    try:
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        conn = sqlite3.connect(CACHE_DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT response_json, is_stream FROM prompt_cache WHERE prompt_hash = ?", (prompt_hash,))
        row = cursor.fetchone()
        if row:
            conn.close()
            return json.loads(row[0]), bool(row[1]), "Exact Cache Hit"
            
        words = normalize_and_tokenize(prompt_text)
        if len(words) >= 5:
            cursor.execute("SELECT prompt_hash, normalized_words, original_prompt, response_json, is_stream FROM prompt_cache")
            rows = cursor.fetchall()
            
            # 1. Try Jaccard (very fast)
            for r_hash, r_norm, r_orig, r_json, r_stream in rows:
                if not r_norm: continue
                cached_words = set(r_norm.split(","))
                sim = fuzzy_match_similarity(words, cached_words)
                if sim >= 0.92:
                    conn.close()
                    return json.loads(r_json), bool(r_stream), f"Fuzzy Cache Hit ({sim*100:.1f}%)"
                    
            # 2. Try Advanced Semantic TF-IDF Cosine Similarity
            if rows:
                candidate_prompts = [r[2] for r in rows if r[2]]
                if candidate_prompts:
                    sim_scores = calculate_tfidf_similarity(prompt_text, candidate_prompts)
                    best_idx, best_score = max(sim_scores, key=lambda x: x[1]) if sim_scores else (-1, 0.0)
                    if best_score >= 0.85:
                        r_hash, r_norm, r_orig, r_json, r_stream = rows[best_idx]
                        conn.close()
                        return json.loads(r_json), bool(r_stream), f"Semantic TF-IDF Cache Hit ({best_score*100:.1f}%)"
        conn.close()
    except Exception:
        pass
    return None

def save_prompt_cache(prompt_text, response_json, is_stream):
    try:
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        words = normalize_and_tokenize(prompt_text)
        normalized_words_str = ",".join(sorted(list(words)))
        conn = sqlite3.connect(CACHE_DB_PATH, timeout=5)
        cursor = conn.cursor()
        
        # Enforce LRU cache limit of 1,000 entries
        cursor.execute("SELECT COUNT(*) FROM prompt_cache")
        count = cursor.fetchone()[0]
        if count >= 1000:
            cursor.execute("""
                DELETE FROM prompt_cache 
                WHERE id IN (SELECT id FROM prompt_cache ORDER BY created_at ASC LIMIT ?)
            """, (count - 999,))
            
        cursor.execute("""
            INSERT OR REPLACE INTO prompt_cache (prompt_hash, original_prompt, normalized_words, response_json, is_stream, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (prompt_hash, prompt_text, normalized_words_str, json.dumps(response_json), 1 if is_stream else 0, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass

def ast_recursive_slice(content, target_name):
    try:
        tree = ast.parse(content)
    except Exception:
        return ""
    lines = content.splitlines()
    defs = {}
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported_names = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.append(alias.asname or alias.name)
            else:
                for alias in node.names:
                    imported_names.append(alias.asname or alias.name)
            imports.append((node, node.lineno - 1, getattr(node, 'end_lineno', node.lineno), imported_names))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            deps = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    deps.add(child.id)
            start = node.lineno - 1
            if node.decorator_list:
                start = min(node.decorator_list[0].lineno - 1, start)
            end = getattr(node, 'end_lineno', len(lines))
            defs[node.name] = (node, start, end, deps)
        elif isinstance(node, ast.Assign):
            target_names = []
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_names.append(target.id)
            if target_names:
                deps = set()
                for child in ast.walk(node.value):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        deps.add(child.id)
                start = node.lineno - 1
                end = getattr(node, 'end_lineno', node.lineno)
                for tname in target_names:
                    defs[tname] = (node, start, end, deps)
    if target_name not in defs:
        return ""
    required_defs = set()
    queue = [target_name]
    visited = {target_name}
    while queue:
        curr = queue.pop(0)
        required_defs.add(curr)
        _, _, _, deps = defs[curr]
        for dep in deps:
            if dep in defs and dep not in visited:
                visited.add(dep)
                queue.append(dep)
    all_used_names = set()
    for name in required_defs:
        _, _, _, deps = defs[name]
        all_used_names.update(deps)
    all_used_names.update(required_defs)
    needed_imports_indices = set()
    for idx, (node, start, end, imported_names) in enumerate(imports):
        if any(name in all_used_names for name in imported_names):
            needed_imports_indices.add(idx)
    pieces = []
    for idx, (node, start, end, _) in enumerate(imports):
        if idx in needed_imports_indices:
            pieces.append(("\n".join(lines[start:end]), start))
    seen_nodes = set()
    for name in required_defs:
        node, start, end, _ = defs[name]
        node_id = id(node)
        if node_id not in seen_nodes:
            seen_nodes.add(node_id)
            pieces.append(("\n".join(lines[start:end]), start))
    pieces.sort(key=lambda x: x[1])
    return "\n\n".join(p[0] for p in pieces)

def auto_slice_prompt(messages, max_budget):
    full_text = ""
    for msg in messages:
        if isinstance(msg, dict) and "content" in msg:
            content = msg["content"]
            if isinstance(content, str):
                full_text += "\n" + content
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        full_text += "\n" + item.get("text", "")
    current_tokens, _ = count_tokens(full_text)
    if current_tokens <= max_budget:
        return messages, False
    user_words = set()
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "user" and "content" in msg:
            content = msg["content"]
            if isinstance(content, str):
                prose = re.sub(r"```[\s\S]*?```", "", content)
                user_words.update(normalize_and_tokenize(prose))
    blocks = []
    code_block_pat = r"```([a-zA-Z0-9+#_.-]*)\n([\s\S]*?)```"
    for m_idx, msg in enumerate(messages):
        if not isinstance(msg, dict) or "content" not in msg:
            continue
        content = msg["content"]
        if isinstance(content, str):
            matches = list(re.finditer(code_block_pat, content))
            for match in matches:
                lang = match.group(1).lower()
                code = match.group(2)
                code_words = set(re.sub(r'[^\w\s]', '', code.lower()).split())
                score = len(user_words.intersection(code_words))
                block_tokens, _ = count_tokens(match.group(0))
                blocks.append({
                    "msg_idx": m_idx,
                    "item_idx": None,
                    "span": match.span(),
                    "lang": lang,
                    "code": code,
                    "score": score,
                    "tokens": block_tokens,
                    "original": match.group(0)
                })
        elif isinstance(content, list):
            for i_idx, item in enumerate(content):
                if isinstance(item, dict) and item.get("type") == "text":
                    text_val = item.get("text", "")
                    matches = list(re.finditer(code_block_pat, text_val))
                    for match in matches:
                        lang = match.group(1).lower()
                        code = match.group(2)
                        code_words = set(re.sub(r'[^\w\s]', '', code.lower()).split())
                        score = len(user_words.intersection(code_words))
                        block_tokens, _ = count_tokens(match.group(0))
                        blocks.append({
                            "msg_idx": m_idx,
                            "item_idx": i_idx,
                            "span": match.span(),
                            "lang": lang,
                            "code": code,
                            "score": score,
                            "tokens": block_tokens,
                            "original": match.group(0)
                        })
    if not blocks:
        while current_tokens > max_budget and len(messages) > 2:
            removed = False
            for idx in range(len(messages)):
                if messages[idx].get("role") != "system":
                    messages.pop(idx)
                    removed = True
                    break
            if not removed:
                break
            full_text = ""
            for msg in messages:
                if isinstance(msg, dict) and "content" in msg:
                    content = msg["content"]
                    if isinstance(content, str):
                        full_text += "\n" + content
            current_tokens, _ = count_tokens(full_text)
        return messages, True
    blocks.sort(key=lambda x: (x["score"], -x["tokens"]))
    for block in blocks:
        if current_tokens <= max_budget:
            break
        lang = block["lang"]
        code = block["code"]
        shrunk_code = ""
        if lang in ["py", "python"]:
            shrunk_lines = []
            in_multiline = False
            for line in code.splitlines():
                stripped = line.strip()
                if in_multiline:
                    if '"""' in stripped or "'''" in stripped:
                        in_multiline = False
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    if len(stripped) >= 6 and (stripped.endswith('"""') or stripped.endswith("'''")):
                        continue
                    in_multiline = True
                    continue
                if stripped.startswith('#') or not stripped:
                    continue
                if (stripped.startswith('def ') or stripped.startswith('class ') or 
                    stripped.startswith('import ') or stripped.startswith('from ') or 
                    stripped.startswith('@') or line.startswith('    def ') or line.startswith('    class ')):
                    if stripped.endswith(':'):
                        indent = len(line) - len(line.lstrip())
                        shrunk_lines.append(line)
                        shrunk_lines.append(" " * (indent + 4) + "...")
                    else:
                        shrunk_lines.append(line)
            shrunk_code = "\n".join(shrunk_lines)
        elif lang in ["js", "ts", "jsx", "tsx", "javascript", "typescript"]:
            shrunk_lines = []
            in_block = False
            for line in code.splitlines():
                stripped = line.strip()
                if in_block:
                    if '*/' in stripped:
                        in_block = False
                    continue
                if stripped.startswith('/*'):
                    if '*/' not in stripped:
                        in_block = True
                    continue
                if stripped.startswith('//') or not stripped:
                    continue
                if (stripped.startswith('import ') or stripped.startswith('export ') or 
                    'class ' in stripped or 'interface ' in stripped or 'type ' in stripped or 
                    'function ' in stripped or (stripped.startswith('const ') and '=>' in stripped)):
                    if '{' in stripped and not stripped.endswith('}'):
                        shrunk_lines.append(line.split('{')[0] + '{ ... }')
                    else:
                        shrunk_lines.append(line)
            shrunk_code = "\n".join(shrunk_lines)
        if not shrunk_code:
            lines = code.splitlines()
            if len(lines) > 40:
                shrunk_code = "\n".join(lines[:30]) + "\n... [TRUNCATED to save token budget] ...\n" + "\n".join(lines[-10:])
            else:
                shrunk_code = code
        shrunk_block_str = f"```{lang}\n{shrunk_code}\n```"
        shrunk_tokens, _ = count_tokens(shrunk_block_str)
        msg_idx = block["msg_idx"]
        item_idx = block["item_idx"]
        if item_idx is None:
            orig_msg = messages[msg_idx]["content"]
            start, end = block["span"]
            new_msg = orig_msg[:start] + shrunk_block_str + orig_msg[end:]
            messages[msg_idx]["content"] = new_msg
            offset = len(shrunk_block_str) - (end - start)
            for b in blocks:
                if b["msg_idx"] == msg_idx and b["item_idx"] is None and b["span"][0] > start:
                    b["span"] = (b["span"][0] + offset, b["span"][1] + offset)
        else:
            orig_text = messages[msg_idx]["content"][item_idx]["text"]
            start, end = block["span"]
            new_text = orig_text[:start] + shrunk_block_str + orig_text[end:]
            messages[msg_idx]["content"][item_idx]["text"] = new_text
            offset = len(shrunk_block_str) - (end - start)
            for b in blocks:
                if b["msg_idx"] == msg_idx and b["item_idx"] == item_idx and b["span"][0] > start:
                    b["span"] = (b["span"][0] + offset, b["span"][1] + offset)
        diff = block["tokens"] - shrunk_tokens
        current_tokens -= diff
    return messages, True

def get_hardware_uuid():
    """Gets the unique stable hardware UUID across macOS, Windows, and Android/Linux."""
    import sys
    import subprocess
    
    # macOS
    if sys.platform == 'darwin':
        try:
            cmd = "ioreg -rd1 -c IOPlatformExpertDevice | awk -F'\"' '/IOPlatformUUID/{print $(NF-1)}'"
            uuid = subprocess.check_output(cmd, shell=True).decode().strip()
            if uuid:
                return uuid
        except Exception:
            pass

    # Windows
    elif sys.platform == 'win32':
        try:
            cmd = "powershell -Command \"(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID\""
            uuid = subprocess.check_output(cmd, shell=True).decode().strip()
            if uuid:
                return uuid
        except Exception:
            pass
        try:
            cmd = "wmic csproduct get uuid"
            output = subprocess.check_output(cmd, shell=True).decode()
            uuid = output.split('\n')[1].strip()
            if uuid:
                return uuid
        except Exception:
            pass

    # Android / Linux / Termux
    else:
        try:
            # Android getprop serial number
            cmd = "getprop ro.serialno"
            serial = subprocess.check_output(cmd, shell=True).decode().strip()
            if serial:
                return f"ANDROID-{serial}"
        except Exception:
            pass
        try:
            with open("/sys/class/dmi/id/product_uuid", "r") as f:
                uuid = f.read().strip()
                if uuid:
                    return uuid
        except Exception:
            pass

# Fallback to hashed MAC address (extremely stable cross-platform fallback)
    try:
        import uuid
        mac_node = uuid.getnode()
        import hashlib
        hashed = hashlib.sha256(str(mac_node).encode()).hexdigest()
        formatted = f"{hashed[:8]}-{hashed[8:12]}-{hashed[12:16]}-{hashed[16:20]}-{hashed[20:32]}".upper()
        return formatted
    except Exception:
        return "GENERIC_HOST_ID"

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

# Ensure CSV exists
if not os.path.exists(CSV_PATH):
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Tool", "Target", "Input_Tokens", "Output_Tokens", "Cost_USD", "Status", "Counter_Used"])

def log_audit(tool, target, in_tokens, out_tokens, cost, status="Success", counter_used="tiktoken", system_tokens=0, code_tokens=0, prose_tokens=0):
    """Appends an execution record to the local audit log."""
    try:
        conn = sqlite3.connect(CACHE_DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (timestamp, tool, target, input_tokens, output_tokens, cost_usd, status, counter_used, system_tokens, code_tokens, prose_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tool,
            target,
            int(in_tokens),
            int(out_tokens),
            float(cost),
            status,
            counter_used,
            int(system_tokens),
            int(code_tokens),
            int(prose_tokens)
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass
    try:
        with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                tool,
                target,
                int(in_tokens),
                int(out_tokens),
                f"{cost:.5f}",
                status,
                counter_used
            ])
    except Exception:
        pass

def print_savings_summary(orig_tokens, new_tokens, counter_used, filepath, tool_name, extra_desc="", scrub_summary=""):
    """Logs and prints a detailed and visual Token Savings Summary with Runway Meter."""
    saved_tokens = max(0, orig_tokens - new_tokens)
    percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
    
    prices = load_prices()
    input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
    savings_usd = saved_tokens * input_price
    
    # Log local run
    log_audit(tool_name, extra_desc or os.path.basename(filepath), orig_tokens, new_tokens, savings_usd, f"Saved ${savings_usd:.4f}", counter_used)
    
    # Print outputs
    if scrub_summary:
        print(scrub_summary)
        
    print(f"📊 Token Savings Summary (using {counter_used}):")
    print(f"  - Original Tokens: {orig_tokens}")
    print(f"  - New Tokens:      {new_tokens}")
    print(f"  - Tokens Saved:    {saved_tokens} ({percent_saved:.1f}%)")
    print(f"  - Estimated Saved: ${savings_usd:.4f}")
    
    # Visual LLM Runway Meter
    if orig_tokens > 0 and percent_saved > 0:
        multiplier = (orig_tokens / new_tokens) if new_tokens > 0 else 100.0
        bar_len = 20
        filled_len = int(round(bar_len * (percent_saved / 100.0)))
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        runway_percent = int((multiplier - 1.0) * 100)
        
        print("\n🔋 \033[1;32mLLM API RUNWAY EXTENSION:\033[0m")
        print(f"  [{bar}] +{runway_percent}% Runway Added!")
        
        if multiplier >= 1.1:
            days_before = 5
            days_after = int(days_before * multiplier)
            print(f"  Your LLM budget is lasting \033[1;36m{multiplier:.1f}x longer\033[0m than baseline.")
            print(f"  (e.g. $100 API deposit lasts \033[31m{days_before} Days\033[0m → \033[32m{days_after} Days\033[0m under this usage rate.)\n")

def check_and_warn_large_file(filepath, limit=50000):
    """Warns the user if they are about to perform an operation on a very large file."""
    if not os.path.exists(filepath) or os.path.isdir(filepath):
        return
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        tokens, _ = count_tokens(content)
        if tokens > limit:
            print(f"\n⚠️  \033[1;33mCOST ALERT:\033[0m This operation is about to process a massive file ({tokens:,} tokens).")
            print(f"  Sending this raw to an LLM will consume a significant portion of your budget.")
            print(f"  It is highly recommended to run \033[1;36m'tokenpinch shrink'\033[0m first to compress it.\n")
    except Exception:
        pass

def copy_to_clipboard(text):
    """Cross-platform native clipboard copy (macOS, Windows, Android/Linux)."""
    import sys
    import subprocess
    try:
        # macOS
        if sys.platform == 'darwin':
            process = subprocess.Popen('pbcopy', env={'LANG': 'en_US.UTF-8'}, stdin=stdin) if 'stdin' in locals() else subprocess.Popen('pbcopy', env={'LANG': 'en_US.UTF-8'}, stdin=subprocess.PIPE)
            process.communicate(text.encode('utf-8'))
            return True
        # Windows
        elif sys.platform == 'win32':
            process = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
            process.communicate(text.encode('utf-8'))
            return True
        # Android (Termux) / Linux
        else:
            try:
                process = subprocess.Popen('termux-clipboard-set', stdin=subprocess.PIPE)
                process.communicate(text.encode('utf-8'))
                return True
            except FileNotFoundError:
                pass
            for cmd in ['xclip -selection clipboard', 'xsel -b']:
                try:
                    process = subprocess.Popen(cmd.split(), stdin=subprocess.PIPE)
                    process.communicate(text.encode('utf-8'))
                    return True
                except FileNotFoundError:
                    continue
    except Exception:
        pass
    return False

def read_from_clipboard():
    """Reads text from the native macOS, Windows, or Termux clipboard."""
    import sys
    import subprocess
    try:
        if sys.platform == 'darwin':
            return subprocess.check_output('pbpaste', env={'LANG': 'en_US.UTF-8'}).decode('utf-8')
        elif sys.platform == 'win32':
            return subprocess.check_output('powershell -Command "Get-Clipboard"', shell=True).decode('utf-8').strip()
        else:
            try:
                return subprocess.check_output('termux-clipboard-get').decode('utf-8')
            except FileNotFoundError:
                pass
            for cmd in ['xclip -selection clipboard -o', 'xsel -b -o']:
                try:
                    return subprocess.check_output(cmd.split()).decode('utf-8')
                except FileNotFoundError:
                    continue
    except Exception:
        pass
    return ""

# ==================== FEATURE A & B HELPERS ====================

PRICES_PATH = os.path.join(INSTALL_DIR, "prices.json")

def load_prices():
    """Loads per-token input and output prices from prices.json."""
    if not os.path.exists(PRICES_PATH):
        defaults = {
            "set_date": datetime.now().strftime("%Y-%m-%d"),
            "input_price_per_million": 3.0,
            "output_price_per_million": 15.0,
            "max_context_budget": 15000
        }
        try:
            with open(PRICES_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=2)
        except Exception:
            pass
        return defaults
    try:
        with open(PRICES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "set_date": "2026-11-24",
            "input_price_per_million": 3.0,
            "output_price_per_million": 15.0,
            "max_context_budget": 15000
        }

def count_tokens(text, exact=False):
    """Counts tokens using tiktoken (offline) or optionally Claude API (online)."""
    # Initialize cache dir
    cache_dir = os.path.join(sys._MEIPASS, "tiktoken_cache") if getattr(sys, 'frozen', False) else os.path.join(INSTALL_DIR, "tiktoken_cache")
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["TIKTOKEN_CACHE_DIR"] = cache_dir
    
    # Try Claude exact count if exact is True and ANTHROPIC_API_KEY is set
    if exact and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import urllib.request
            import urllib.parse
            import json
            url = "https://api.anthropic.com/v1/messages/count_tokens"
            headers = {
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": "claude-3-5-sonnet-20241022",
                "messages": [{"role": "user", "content": text}]
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10, context=_ssl_context()) as r:
                res = json.loads(r.read().decode("utf-8"))
                return res.get("input_tokens", 0), "claude-exact"
        except Exception:
            pass # Fall back silently to tiktoken
            
    # Offline fallback using tiktoken
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text)), "tiktoken"
    except Exception:
        # Final fallback if tiktoken isn't available
        return int(len(text.split()) * 1.33), "estimate-fallback"

def scrub_text(text, active=True):
    """Detects and redacts secrets, passwords, keys, IPs, and emails."""
    if not active:
        return text, ""
        
    scrub_counts = {
        "API Key": 0,
        "Private Key": 0,
        "JWT": 0,
        "Connection String": 0,
        "Secret Assignment": 0,
        "Email": 0,
        "IP Address": 0
    }
    
    # 1. Private Key Blocks (multi-line)
    def sub_private_key(match):
        scrub_counts["Private Key"] += 1
        return "[REDACTED:PRIVATE_KEY]"
    text, n1 = re.subn(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----", sub_private_key, text)
    
    # 2. Connection Strings with passwords
    def sub_conn_string(match):
        scrub_counts["Connection String"] += 1
        return f"{match.group(1)}://{match.group(2)}:[REDACTED:PASSWORD]@{match.group(4)}"
    text, n2 = re.subn(r"([a-zA-Z0-9+.-]+)://([a-zA-Z0-9_.-]+):([^@\s]+)@([a-zA-Z0-9_.-]+[^/\s]*)", sub_conn_string, text)
    
    # 3. Secret Assignments
    def sub_assignment(match):
        val = match.group(4)
        if val.startswith("[REDACTED:"):
            return match.group(0)
        scrub_counts["Secret Assignment"] += 1
        return f"{match.group(1)}{match.group(2)}{match.group(3)}[REDACTED:SECRET]{match.group(3)}"
    text, n3 = re.subn(r"\b(password|secret|token|api_key|passwd|pwd)(\s*=\s*)(['\"])(.*?)\3", sub_assignment, text, flags=re.IGNORECASE)
    
    # 4. Specific Key Patterns
    def sub_aws(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:AWS_KEY]"
    text, n4 = re.subn(r"\bAKIA[A-Z0-9]{16}\b", sub_aws, text)
    
    def sub_github(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:GITHUB_TOKEN]"
    text, n5 = re.subn(r"\b(ghp_|gho_|github_pat_)[a-zA-Z0-9_]{36,255}\b", sub_github, text)
    
    def sub_anthropic(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:ANTHROPIC_KEY]"
    text, n6 = re.subn(r"\bsk-ant-[a-zA-Z0-9_-]{20,}\b", sub_anthropic, text)
    
    def sub_openai(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:OPENAI_KEY]"
    text, n7 = re.subn(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}", sub_openai, text)
    
    def sub_slack(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:SLACK_TOKEN]"
    text, n8 = re.subn(r"\bxox[abposr]-[A-Za-z0-9-]{10,}", sub_slack, text)
    
    def sub_stripe(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:STRIPE_KEY]"
    text, n9 = re.subn(r"\b(sk_live_|rk_live_)[a-zA-Z0-9]{20,}\b", sub_stripe, text)
    
    def sub_google(match):
        scrub_counts["API Key"] += 1
        return "[REDACTED:GOOGLE_KEY]"
    text, n10 = re.subn(r"\bAIza[0-9A-Za-z\-_]{35}\b", sub_google, text)
    
    def sub_jwt(match):
        scrub_counts["JWT"] += 1
        return "[REDACTED:JWT]"
    text, n11 = re.subn(r"\bey[a-zA-Z0-9_-]+\.ey[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b", sub_jwt, text)
    
    def sub_email(match):
        scrub_counts["Email"] += 1
        return "[REDACTED:EMAIL]"
    text, n12 = re.subn(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", sub_email, text)
    
    def sub_ip(match):
        scrub_counts["IP Address"] += 1
        return "[REDACTED:IP_ADDRESS]"
    text, n13 = re.subn(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", sub_ip, text)
    text, n14 = re.subn(r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", sub_ip, text)
    text, n15 = re.subn(r"\b192\.168\.\d{1,3}\.\d{1,3}\b", sub_ip, text)
    
    total_scrubbed = sum(scrub_counts.values())
    summary = ""
    if total_scrubbed > 0:
        parts = []
        for k, v in scrub_counts.items():
            if v > 0:
                parts.append(f"{v} {k.lower() + ('s' if v > 1 else '')}")
        summary = f"Scrubbed {total_scrubbed} secret{'s' if total_scrubbed > 1 else ''} ({', '.join(parts)})"
        
    return text, summary

def apply_squeeze_filters(content):
    """Filters C pseudocode to strip canaries, casts, offsets, etc."""
    lines = content.splitlines()
    shrunk_lines = []
    canary_vars = set()
    skip_mode = False
    brace_depth = 0
    
    for line in lines:
        if '__stack_chk_fail' in line:
            for var in re.findall(r'\b(local_[a-fA-F0-9]+|lVar\d+)\b', line):
                canary_vars.add(var)
                
    for line in lines:
        stripped = line.strip()
        if not stripped: continue
        if '__stack_chk_fail' in line:
            skip_mode = True
            continue
        if skip_mode:
            brace_depth += line.count('{') - line.count('}')
            if brace_depth <= 0:
                skip_mode = False
                brace_depth = 0
            continue
        if any(var in line for var in canary_vars) and ('long' in line or 'GS_OFFSET' in line or 'Var' in line):
            if '=' in line or 'Var' in line: continue
        if 'in_GS_OFFSET' in line or 'in_FS_OFFSET' in line: continue
        
        line = re.sub(r'\*\((undefined\d+|long|int|char|short)\s*\*\)', '', line)
        line = re.sub(r'\((undefined\d+|long|int|char|short|void)\s*\*\)', '', line)
        line = re.sub(r'\((int|char|long|short)\)\s*', '', line)
        line = re.sub(r'\s+', ' ', line)
        shrunk_lines.append(line)
        
    result_code = "\n".join(shrunk_lines)
    result_code = re.sub(r'\{\s*\}', ';', result_code)
    return result_code

def parse_c_functions(content):
    """Parses functions from C pseudocode, returning a list of dicts with name, body, and calls."""
    functions = []
    lines = content.splitlines()
    header_pat_with_brace = r"^[A-Za-z0-9_*\s]+\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)\s*(?:const)?\s*\{"
    header_pat_no_brace = r"^[A-Za-z0-9_*\s]+\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)\s*(?:const)?\s*$"
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Check first for same-line brace
        match = re.match(header_pat_with_brace, stripped)
        if match:
            func_name = match.group(1)
            func_args = match.group(2)
            body_lines = [line]
            brace_count = line.count('{') - line.count('}')
            j = i + 1
            while j < len(lines) and (brace_count > 0 or not body_lines[-1].strip().endswith('}')):
                body_lines.append(lines[j])
                brace_count += lines[j].count('{') - lines[j].count('}')
                j += 1
            
            func_body = "\n".join(body_lines)
            calls = set(re.findall(r"\b([A-Za-z0-9_]+)\s*\(", func_body))
            if func_name in calls:
                calls.remove(func_name)
                
            functions.append({
                "name": func_name,
                "body": func_body,
                "calls": calls,
                "original_line_start": i,
                "original_line_end": j
            })
            i = j
            continue
            
        # Check for signature on this line, with brace on subsequent line
        match_no_brace = re.match(header_pat_no_brace, stripped)
        if match_no_brace:
            # Search ahead for '{'
            k = i + 1
            found_brace = False
            brace_line_idx = -1
            while k < len(lines):
                next_line = lines[k].strip()
                if not next_line:
                    k += 1
                    continue
                if next_line == '{' or next_line.startswith('{'):
                    found_brace = True
                    brace_line_idx = k
                break # Only check the first non-empty subsequent line
                
            if found_brace:
                func_name = match_no_brace.group(1)
                func_args = match_no_brace.group(2)
                body_lines = lines[i:brace_line_idx+1]
                brace_count = "".join(body_lines).count('{') - "".join(body_lines).count('}')
                j = brace_line_idx + 1
                while j < len(lines) and (brace_count > 0 or not body_lines[-1].strip().endswith('}')):
                    body_lines.append(lines[j])
                    brace_count += lines[j].count('{') - lines[j].count('}')
                    j += 1
                
                func_body = "\n".join(body_lines)
                calls = set(re.findall(r"\b([A-Za-z0-9_]+)\s*\(", func_body))
                if func_name in calls:
                    calls.remove(func_name)
                    
                functions.append({
                    "name": func_name,
                    "body": func_body,
                    "calls": calls,
                    "original_line_start": i,
                    "original_line_end": j
                })
                i = j
                continue
                
        i += 1
    return functions

def order_functions_bfs(functions):
    """Orders functions starting from the first (target) function using BFS of calls."""
    if not functions:
        return []
        
    func_map = {f["name"]: f for f in functions}
    target = functions[0]
    target_name = target["name"]
    
    ordered_names = []
    queue = [target_name]
    visited = {target_name}
    
    while queue:
        current_name = queue.pop(0)
        ordered_names.append(current_name)
        curr_func = func_map.get(current_name)
        if curr_func:
            for call in sorted(curr_func["calls"]):
                if call in func_map and call not in visited:
                    visited.add(call)
                    queue.append(call)
                    
    for f in functions:
        if f["name"] not in visited:
            ordered_names.append(f["name"])
            
    return [func_map[name] for name in ordered_names]

def squeeze_with_budget(filepath, budget=None, exact=False):
    """Squeezes C pseudocode file and respects token budget with BFS ordering."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    squeezed_content = apply_squeeze_filters(content)
    functions = parse_c_functions(squeezed_content)
    
    if budget is not None and not functions:
        print("Warning: No C functions detected in the decompiler output; budget limit cannot be applied.")
        
    if not functions or budget is None:
        return squeezed_content, []
        
    ordered_funcs = order_functions_bfs(functions)
    kept_funcs = []
    dropped_funcs = []
    
    base_prompt_tmpl = "Decompile/Analyze this squeezed C pseudocode:\n\n```c\n{}\n```\n\nPlease explain:\n1. What this function does in plain language.\n2. Any security vulnerabilities, logic bugs, or buffer overflows.\n3. Output a clean, high-level Python or pseudocode equivalent.\nAnswer in extremely short, active-voice bullet points. No prose."
    
    for idx, func in enumerate(ordered_funcs):
        test_body = "\n\n".join(kept_funcs + [func["body"]])
        test_prompt = base_prompt_tmpl.format(test_body)
        tokens, _ = count_tokens(test_prompt, exact=exact)
        
        if tokens <= budget:
            kept_funcs.append(func["body"])
        else:
            if idx == 0:
                kept_funcs.append(func["body"])
                print(f"Warning: First function '{func['name']}' alone exceeds the budget of {budget} tokens, but was kept to preserve context.")
            else:
                dropped_funcs.append(func["name"])
            
    final_code = "\n\n".join(kept_funcs)
    return final_code, dropped_funcs

# ==================== SUBCOMMANDS ====================

def run_shrink(filepath, exact=False, scrub=True):
    """Squeezes code file layout, stripping bodies and comments."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    _, ext = os.path.splitext(filepath.lower())
    shrunk = []
    
    if ext == '.py':
        in_multiline = False
        for line in content.splitlines():
            stripped = line.strip()
            if in_multiline:
                if '"""' in stripped or "'''" in stripped:
                    in_multiline = False
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if len(stripped) >= 6 and (stripped.endswith('"""') or stripped.endswith("'''")):
                    continue
                in_multiline = True
                continue
            if stripped.startswith('#') or not stripped:
                continue
            if (stripped.startswith('def ') or stripped.startswith('class ') or 
                stripped.startswith('import ') or stripped.startswith('from ') or 
                stripped.startswith('@') or line.startswith('    def ') or line.startswith('    class ')):
                if stripped.endswith(':'):
                    indent = len(line) - len(line.lstrip())
                    shrunk.append(line)
                    shrunk.append(" " * (indent + 4) + "...")
                else:
                    shrunk.append(line)
                    
    elif ext in ['.js', '.ts', '.jsx', '.tsx']:
        in_block = False
        for line in content.splitlines():
            stripped = line.strip()
            if in_block:
                if '*/' in stripped:
                    in_block = False
                continue
            if stripped.startswith('/*'):
                if '*/' not in stripped:
                    in_block = True
                continue
            if stripped.startswith('//') or not stripped:
                continue
            if (stripped.startswith('import ') or stripped.startswith('export ') or 
                'class ' in stripped or 'interface ' in stripped or 'type ' in stripped or 
                'function ' in stripped or (stripped.startswith('const ') and '=>' in stripped)):
                if '{' in stripped and not stripped.endswith('}'):
                    shrunk.append(line.split('{')[0] + '{ ... }')
                else:
                    shrunk.append(line)
    else:
        shrunk = content.splitlines()[:50] + ["... [truncated] ..."]
        
    result = "\n".join(shrunk)
    
    # 1. Secret scrubbing
    scrubbed_result, scrub_summary = scrub_text(result, active=scrub)
    
    # 2. Clipboard copy
    copy_to_clipboard(scrubbed_result)
    
    # 3. Token counting
    orig_tokens, orig_counter = count_tokens(content, exact=exact)
    new_tokens, new_counter = count_tokens(scrubbed_result, exact=exact)
    counter_used = orig_counter if orig_counter == new_counter else f"{orig_counter}/{new_counter}"
    
    # 4. Cost/savings calculations
    prices = load_prices()
    input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
    saved_tokens = max(0, orig_tokens - new_tokens)
    percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
    savings_usd = saved_tokens * input_price
    
    # Print outputs
    print("Copied shrunk skeleton to clipboard!")
    print_savings_summary(orig_tokens, new_tokens, counter_used, filepath, "Shrink", scrub_summary=scrub_summary)


def run_slice(filepath, target_name, exact=False, scrub=True):
    """Extracts a specific function or class by name."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)
        
    check_and_warn_large_file(filepath)
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    _, ext = os.path.splitext(filepath.lower())
    sliced_code = ""
    
    if ext == '.py':
        try:
            sliced_code = ast_recursive_slice(content, target_name)
        except Exception:
            pass

    if not sliced_code:
        # Fallback to text parsing
        lines = content.splitlines()
        found = False
        brace_count = 0
        shrunk = []
        pattern = rf"(class\s+{target_name}|interface\s+{target_name}|type\s+{target_name}|function\s+{target_name}\b|const\s+{target_name}\b|def\s+{target_name}\b)"
        for idx, line in enumerate(lines):
            if not found and re.search(pattern, line):
                found = True
                start_idx = idx
            if found:
                shrunk.append(line)
                brace_count += line.count('{') - line.count('}')
                if '{' in line and brace_count == 0: break
                if brace_count < 0: break
                if start_idx != idx and brace_count == 0 and line.strip() == '': break
        if found:
            sliced_code = "\n".join(shrunk)
            
    if not sliced_code:
        print(f"Symbol '{target_name}' not found in {os.path.basename(filepath)}")
        sys.exit(1)
        
    # 1. Secret scrubbing
    scrubbed_code, scrub_summary = scrub_text(sliced_code, active=scrub)
    
    # 2. Clipboard copy
    copy_to_clipboard(scrubbed_code)
    
    # 3. Token counting
    orig_tokens, orig_counter = count_tokens(content, exact=exact)
    new_tokens, new_counter = count_tokens(scrubbed_code, exact=exact)
    counter_used = orig_counter if orig_counter == new_counter else f"{orig_counter}/{new_counter}"
    
    # 4. Cost/savings calculations
    prices = load_prices()
    input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
    saved_tokens = max(0, orig_tokens - new_tokens)
    percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
    savings_usd = saved_tokens * input_price
    
    # Print outputs
    print(f"Copied code slice of '{target_name}' from '{os.path.basename(filepath)}' to clipboard!")
    print_savings_summary(orig_tokens, new_tokens, counter_used, filepath, "Slice", extra_desc=f"{os.path.basename(filepath)}:{target_name}", scrub_summary=scrub_summary)


def run_squeeze(filepath, budget=None, exact=False, scrub=True):
    """Removes assembly/canary guard overhead from decompiled C."""
    if not os.path.exists(filepath):
        print(f"Error: File or directory '{filepath}' not found.")
        sys.exit(1)
        
    check_and_warn_large_file(filepath)
        
    combined_original_content = ""
    dropped_funcs = []
    
    # 1. Folder Squeeze
    if os.path.isdir(filepath):
        # Gather all .c and .txt files
        files = []
        for root, _, filenames in os.walk(filepath):
            for f in sorted(filenames):
                if f.lower().endswith(('.c', '.txt')):
                    files.append(os.path.join(root, f))
                    
        if not files:
            print(f"Error: No .c or .txt files found in directory '{filepath}'.")
            sys.exit(1)
            
        print(f"📁 Processing folder '{filepath}' ({len(files)} files)...")
        
        all_squeezed_pieces = []
        for fpath in files:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            combined_original_content += "\n\n" + content
            squeezed_piece = apply_squeeze_filters(content)
            all_squeezed_pieces.append(squeezed_piece)
            
        combined_squeezed = "\n\n".join(all_squeezed_pieces)
        
        # Parse functions from combined squeezed
        functions = parse_c_functions(combined_squeezed)
        if functions and budget is not None:
            ordered_funcs = order_functions_bfs(functions)
            kept_bodies = []
            
            base_prompt_tmpl = "Decompile/Analyze this squeezed C pseudocode:\n\n```c\n{}\n```\n\nPlease explain:\n1. What this function does in plain language.\n2. Any security vulnerabilities, logic bugs, or buffer overflows.\n3. Output a clean, high-level Python or pseudocode equivalent.\nAnswer in extremely short, active-voice bullet points. No prose."
            
            for func in ordered_funcs:
                test_body = "\n\n".join(kept_bodies + [func["body"]])
                test_prompt = base_prompt_tmpl.format(test_body)
                tokens, _ = count_tokens(test_prompt, exact=exact)
                if tokens <= budget:
                    kept_bodies.append(func["body"])
                else:
                    dropped_funcs.append(func["name"])
            result_code = "\n\n".join(kept_bodies)
        else:
            result_code = combined_squeezed
            
    # 2. File Squeeze
    else:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            combined_original_content = f.read()
            
        result_code, dropped_funcs = squeeze_with_budget(filepath, budget=budget, exact=exact)
        
    prompt = f"""Decompile/Analyze this squeezed C pseudocode:

```c
{result_code}
```

Please explain:
1. What this function does in plain language.
2. Any security vulnerabilities, logic bugs, or buffer overflows.
3. Output a clean, high-level Python or pseudocode equivalent.
Answer in extremely short, active-voice bullet points. No prose."""

    # 3. Secret scrubbing
    scrubbed_prompt, scrub_summary = scrub_text(prompt, active=scrub)
    
    # 4. Clipboard copy
    copy_to_clipboard(scrubbed_prompt)
    
    # 5. Token counting
    orig_tokens, orig_counter = count_tokens(combined_original_content, exact=exact)
    new_tokens, new_counter = count_tokens(scrubbed_prompt, exact=exact)
    counter_used = orig_counter if orig_counter == new_counter else f"{orig_counter}/{new_counter}"
    
    # 6. Cost/savings calculations
    prices = load_prices()
    input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
    saved_tokens = max(0, orig_tokens - new_tokens)
    percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
    savings_usd = saved_tokens * input_price
    
    # Print outputs
    print("Copied squeezed REA prompt to clipboard!")
    if dropped_funcs:
        print(f"⚠️ Dropped functions due to budget limit ({budget} tokens): {', '.join(dropped_funcs)}")
    print_savings_summary(orig_tokens, new_tokens, counter_used, filepath, "Squeeze", scrub_summary=scrub_summary)


def run_auto_heal(command, exact=False, scrub=True):
    """Runs compiler or test commands and auto-extracts failure coordinates."""
    command_str = " ".join(command)
    print(f"🚀 Running tests/compilation: {command_str}...")
    
    result = subprocess.run(
        command_str,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    if result.returncode == 0:
        print("\n✅ SUCCESS: All tests/compilation passed! No healing needed.")
        log_audit("AutoHeal", command_str, 0, 0, 0, "Build Passed")
        sys.exit(0)
        
    print("\n❌ BUILD FAILED! Extracting coordinates...")
    output = result.stdout
    print(f"--- Captured Output ---\n{output[-600:]}\n----------------------")
    
    # Parse coordinates
    filepath, line_no, error_msg = None, None, None
    
    py_pattern = r'File "([^"]+)", line (\d+)'
    py_matches = list(re.finditer(py_pattern, output))
    if py_matches:
        last_match = py_matches[-1]
        filepath = last_match.group(1)
        line_no = int(last_match.group(2))
        start_idx = last_match.end()
        error_lines = [l.strip() for l in output[start_idx:start_idx+1000].splitlines() if l.strip()]
        error_msg = error_lines[-1] if error_lines else "Python Test Failure"
        
    if not filepath:
        js_pattern = r'at\s+.*?\s+\(?([^:\s]+):(\d+):(\d+)\)?'
        js_match = re.search(js_pattern, output)
        if js_match:
            filepath = js_match.group(1)
            line_no = int(js_match.group(2))
            error_msg = "JS/TS Execution Failure"
            
    if not filepath:
        comp_pattern = r'([^:\s]+):(\d+):\s*(.*)'
        comp_match = re.search(comp_pattern, output)
        if comp_match:
            filepath = comp_match.group(1)
            line_no = int(comp_match.group(2))
            error_msg = comp_match.group(3)
            
    if not filepath or not os.path.exists(filepath):
        # Fallback
        log_slice = "\n".join(output.splitlines()[-40:])
        prompt = f"The following build failed. Diagnose and provide a unified diff to fix it:\n\n[Terminal Log]\n{log_slice}"
        
        # Scrub fallback prompt
        scrubbed_prompt, scrub_summary = scrub_text(prompt, active=scrub)
        copy_to_clipboard(scrubbed_prompt)
        
        orig_tokens, orig_counter = count_tokens(prompt, exact=exact)
        new_tokens, new_counter = count_tokens(scrubbed_prompt, exact=exact)
        counter_used = orig_counter if orig_counter == new_counter else f"{orig_counter}/{new_counter}"
        
        prices = load_prices()
        input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
        saved_tokens = max(0, orig_tokens - new_tokens)
        percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
        savings_usd = saved_tokens * input_price
        
        log_audit("AutoHeal", command_str, orig_tokens, new_tokens, savings_usd, f"Saved ${savings_usd:.4f}", counter_used)
        
        print("\nCopied fallback log traceback to clipboard.")
        if scrub_summary:
            print(scrub_summary)
        sys.exit(1)
        
    # Slice file context
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.read().splitlines()
    
    idx = line_no - 1
    start = max(0, idx - 12)
    end = min(len(lines), idx + 13)
    
    shrunk = []
    for i in range(start, end):
        prefix = "-> " if i == idx else "   "
        shrunk.append(f"{prefix}{i+1:4d} | {lines[i]}")
        
    code_context = "\n".join(shrunk)
    
    prompt = f"""Fix this specific build/test failure in `{filepath}`:

[Compiler/Test Error]
{error_msg}

[Source Context (Line {line_no} failed)]
```
{code_context}
```

Return ONLY a unified diff (patch) to fix this line/error. Zero prose or conversational explanations."""

    # Scrub prompt
    scrubbed_prompt, scrub_summary = scrub_text(prompt, active=scrub)
    copy_to_clipboard(scrubbed_prompt)
    
    # Token counting
    original_code_context = "\n".join(lines)
    orig_tokens, orig_counter = count_tokens(original_code_context, exact=exact)
    new_tokens, new_counter = count_tokens(scrubbed_prompt, exact=exact)
    counter_used = orig_counter if orig_counter == new_counter else f"{orig_counter}/{new_counter}"
    
    prices = load_prices()
    input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
    saved_tokens = max(0, orig_tokens - new_tokens)
    percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
    savings_usd = saved_tokens * input_price
    
    print(f"\n🎯 Failure Isolated:")
    print(f"  - File:  {filepath}")
    print(f"  - Line:  {line_no}")
    print(f"  - Error: {error_msg}\n")
    print("✨ MICRO-PROMPT COPIED TO CLIPBOARD!")
    print_savings_summary(orig_tokens, new_tokens, counter_used, filepath, "AutoHeal", extra_desc=f"{os.path.basename(filepath)}:{line_no}", scrub_summary=scrub_summary)


def generate_dashboard():
    """Compiles local audit CSV data and generates a jaw-dropping HTML report."""
    rows = []
    total_savings = 0.0
    tool_counts = {}
    total_tokens_original = 0
    total_tokens_new = 0
    counters_distribution = {}
    total_system_tokens = 0
    total_code_tokens = 0
    total_prose_tokens = 0
    
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, tool, target, input_tokens, output_tokens, cost_usd, status, counter_used, system_tokens, code_tokens, prose_tokens
            FROM audit_logs
            ORDER BY id ASC
        """)
        db_rows = cursor.fetchall()
        conn.close()
        for r in db_rows:
            status_str = r[6] if r[6] else "Success"
            rows.append([r[0], r[1], r[2], str(r[3]), str(r[4]), f"{r[5]:.5f}", status_str, r[7]])
            
            if "Saved" in status_str:
                m = re.search(r'\$?([0-9.]+)', status_str)
                if m:
                    total_savings += float(m.group(1))
            elif r[5] > 0:
                total_savings += r[5]
                
            tool_counts[r[1]] = tool_counts.get(r[1], 0) + 1
            total_tokens_original += r[3]
            total_tokens_new += r[4]
            counters_distribution[r[7]] = counters_distribution.get(r[7], 0) + 1
            
            total_system_tokens += r[8] if r[8] else 0
            total_code_tokens += r[9] if r[9] else 0
            total_prose_tokens += r[10] if r[10] else 0
    except Exception:
        try:
            with open(CSV_PATH, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                for r in reader:
                    rows.append(r)
                    total_savings += float(re.search(r'\$?([0-9.]+)', r[6]).group(1)) if "Saved" in r[6] else 0.0
                    tool_counts[r[1]] = tool_counts.get(r[1], 0) + 1
                    try:
                        orig_tok = int(r[3])
                        new_tok = int(r[4])
                        total_tokens_original += orig_tok
                        total_tokens_new += new_tok
                    except Exception:
                        pass
                    c_used = r[7] if len(r) > 7 else "tiktoken"
                    counters_distribution[c_used] = counters_distribution.get(c_used, 0) + 1
        except Exception:
            pass
        
    total_tokens_saved = max(0, total_tokens_original - total_tokens_new)
    
    prices = load_prices()
    input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
    multiplier = (total_tokens_original / total_tokens_new) if total_tokens_new > 0 else 1.0
    avg_cost_original = (total_tokens_original * input_price) / len(rows) if len(rows) > 0 else 1.00
    avg_cost_new = (total_tokens_new * input_price) / len(rows) if len(rows) > 0 else 0.10
    
    # Table rows HTML
    table_rows = ""
    for r in reversed(rows[:100]): # Last 100 entries
        color = "success" if "Saved" in r[6] or "Passed" in r[6] else "danger"
        c_used = r[7] if len(r) > 7 else "tiktoken"
        table_rows += f"""
        <tr>
            <td>{r[0]}</td>
            <td><span class="badge bg-primary">{r[1]}</span></td>
            <td><code>{r[2]}</code></td>
            <td>{r[3]}</td>
            <td>{r[4]}</td>
            <td><span class="text-{color} font-monospace">{r[6]}</span></td>
            <td><span class="badge bg-secondary">{c_used}</span></td>
        </tr>"""
        
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>TokenPinch Spend Audit & Savings Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ background-color: #0f172a; color: #f1f5f9; font-family: sans-serif; }}
        .card {{ background-color: #1e293b; border: 1px solid #334155; color: #f1f5f9; }}
        .table {{ color: #e2e8f0; }}
        thead th {{ background-color: #334155 !important; color: #f1f5f9 !important; }}
        tbody td {{ background-color: #1e293b !important; color: #e2e8f0 !important; border-color: #334155 !important; }}
    </style>
</head>
<body class="container py-5">
    <div class="d-flex justify-content-between align-items-center mb-5 border-bottom pb-3">
        <h2>🤏 TokenPinch Dashboard</h2>
        <span class="text-secondary">Local Spend and Optimization Audit</span>
    </div>
    
    <div class="row g-4 mb-5">
        <div class="col-md-3">
            <div class="card p-4 text-center shadow">
                <h5 class="text-secondary">Total Cash Saved</h5>
                <h1 class="text-success display-6 fw-bold">${total_savings:.2f}</h1>
                <p class="small text-muted">Estimated against cloud model prices</p>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-4 text-center shadow">
                <h5 class="text-secondary">Total Tokens Saved</h5>
                <h1 class="text-info display-6 fw-bold">{total_tokens_saved:,}</h1>
                <p class="small text-muted">Total context eliminated offline</p>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-4 text-center shadow">
                <h5 class="text-secondary">Active Runs</h5>
                <h1 class="text-primary display-6 fw-bold">{len(rows)}</h1>
                <p class="small text-muted">Total local tasks completed</p>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-4 text-center shadow">
                <h5 class="text-secondary">Context Saved %</h5>
                <h1 class="text-warning display-6 fw-bold">
                    {((total_tokens_saved / total_tokens_original * 100) if total_tokens_original > 0 else 0.0):.1f}%
                </h1>
                <p class="small text-muted">Average input context reduction</p>
            </div>
        </div>
    </div>

    <div class="row g-4 mb-5">
        <div class="col-md-8">
            <div class="card p-4 shadow h-100">
                <h5>🔋 LLM Budget Depletion & Runway Comparison</h5>
                <p class="small text-muted">See how fast a $100 API deposit drains under your average usage rate</p>
                <div style="height: 250px;"><canvas id="runwayChart"></canvas></div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card p-4 shadow text-center h-100 d-flex flex-column justify-content-center">
                <h5 class="text-secondary">Runway Multiplier</h5>
                <h1 class="text-warning display-4 fw-bold">{multiplier:.1f}x</h1>
                <p class="small text-muted">Your LLM budget is lasting {multiplier:.1f} times longer than baseline.</p>
                <hr class="border-secondary my-3">
                <h6 class="text-success fw-bold">Runway Extender:</h6>
                <p class="mb-0">A $100 balance lasts <span class="text-danger fw-bold">5 Days</span> → <span class="text-success fw-bold">{int(5 * multiplier)} Days</span>!</p>
            </div>
        </div>
    </div>

    <div class="row g-4 mb-5">
        <div class="col-md-6 d-flex flex-column gap-4">
            <div class="card p-4 shadow flex-grow-1">
                <h5>Command Tool Breakdown</h5>
                <ul class="list-group list-group-flush bg-transparent mt-3">
                    {"".join(f'<li class="list-group-item bg-transparent text-light d-flex justify-content-between"><span>{k}</span><span class="badge bg-primary">{v} runs</span></li>' for k, v in sorted(tool_counts.items()))}
                </ul>
            </div>
            <div class="card p-4 shadow flex-grow-1">
                <h5>Counting Methods Used</h5>
                <ul class="list-group list-group-flush bg-transparent mt-3">
                    {"".join(f'<li class="list-group-item bg-transparent text-light d-flex justify-content-between"><span>{k}</span><span class="badge bg-secondary">{v} times</span></li>' for k, v in sorted(counters_distribution.items()))}
                </ul>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card p-4 shadow h-100">
                <h5>📊 Visual Context-Type Breakdown (Bloat Heatmap)</h5>
                <p class="small text-muted">A semantic analysis of your optimized prompt context distribution</p>
                <div style="height: 280px; position: relative;"><canvas id="contextTypeChart"></canvas></div>
            </div>
        </div>
    </div>

    <div class="card p-4 mb-5">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 class="mb-0">Recent Tool Actions & Audits</h4>
            <div class="w-50">
                <input type="text" id="searchInput" class="form-control bg-dark text-light border-secondary" placeholder="🔍 Search audits by tool, target, status..." onkeyup="filterTable()">
            </div>
        </div>
        <div class="table-responsive">
            <table class="table table-hover align-middle" id="auditsTable">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Tool</th>
                        <th>Target Coordinate</th>
                        <th>Original Tokens</th>
                        <th>New Tokens</th>
                        <th>Status / Outcome</th>
                        <th>Counter Used</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows if table_rows else "<tr><td colspan='7' class='text-center text-muted'>No optimization records yet! Try running 'shrink', 'slice', or 'auto_heal' first.</td></tr>"}
                </tbody>
            </table>
        </div>
    </div>
    <script>
    const ctx = document.getElementById('runwayChart').getContext('2d');
    const labels = [];
    const withoutPinch = [];
    const withPinch = [];
    let balWithout = 100.0;
    let balWith = 100.0;
    const costWithout = {avg_cost_original};
    const costWith = {avg_cost_new};
    for (let i = 0; i <= 10; i++) {{
        labels.push('Run ' + i);
        withoutPinch.push(Math.max(0, balWithout).toFixed(2));
        withPinch.push(Math.max(0, balWith).toFixed(2));
        balWithout -= costWithout;
        balWith -= costWith;
    }}
    new_Chart = new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: labels,
            datasets: [
                {{
                    label: 'Without TokenPinch (Fast Burn)',
                    data: withoutPinch,
                    borderColor: '#f43f5e',
                    backgroundColor: 'rgba(244, 63, 94, 0.1)',
                    fill: true,
                    tension: 0.2
                }},
                {{
                    label: 'With TokenPinch (Extended Runway)',
                    data: withPinch,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.2
                }}
            ]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            scales: {{
                y: {{
                    title: {{ display: true, text: 'Remaining Balance ($)', color: '#94a3b8' }},
                    grid: {{ color: '#334155' }},
                    ticks: {{ color: '#94a3b8' }}
                }},
                x: {{
                    grid: {{ color: '#334155' }},
                    ticks: {{ color: '#94a3b8' }}
                }}
            }},
            plugins: {{
                legend: {{ labels: {{ color: '#f1f5f9' }} }}
            }}
        }}
    }});

    const contextTypeCtx = document.getElementById('contextTypeChart').getContext('2d');
    const totalSys = {total_system_tokens};
    const totalCode = {total_code_tokens};
    const totalProse = {total_prose_tokens};
    const totalAll = totalSys + totalCode + totalProse;
    
    const contextData = totalAll > 0 
        ? [totalSys, totalCode, totalProse]
        : [30, 40, 30];
    
    new Chart(contextTypeCtx, {{
        type: 'doughnut',
        data: {{
            labels: ['System Instructions', 'Code Blocks', 'User Prose'],
            datasets: [{{
                data: contextData,
                backgroundColor: ['#f43f5e', '#2563eb', '#10b981'],
                borderColor: '#1e293b',
                borderWidth: 2
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{
                    position: 'bottom',
                    labels: {{ color: '#f1f5f9', boxWidth: 12 }}
                }},
                tooltip: {{
                    callbacks: {{
                        label: function(context) {{
                            if (totalAll === 0) {{
                                return context.label + ': No data yet (Example distribution)';
                            }}
                            const val = context.raw;
                            const pct = ((val / totalAll) * 100).toFixed(1);
                            return context.label + ': ' + val.toLocaleString() + ' tokens (' + pct + '%)';
                        }}
                    }}
                }}
            }},
            cutout: '70%'
        }}
    }});

    function filterTable() {{
        const input = document.getElementById('searchInput');
        const filter = input.value.toLowerCase();
        const table = document.getElementById('auditsTable');
        const tr = table.getElementsByTagName('tr');
        for (let i = 1; i < tr.length; i++) {{
            let match = false;
            const tdList = tr[i].getElementsByTagName('td');
            for (let j = 0; j < tdList.length; j++) {{
                if (tdList[j]) {{
                    const text = tdList[j].textContent || tdList[j].innerText;
                    if (text.toLowerCase().indexOf(filter) > -1) {{
                        match = true;
                        break;
                    }}
                }}
            }}
            tr[i].style.display = match ? "" : "none";
        }}
    }}
    </script>
</body>
</html>"""

    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print("📊 Generating beautiful spend dashboard...")
    webbrowser.open(f"file://{HTML_PATH}")


# ==================== GATEWAY / PROXY ====================

def resolve_and_squeeze_imports(code, lang):
    if lang not in ["py", "python"]:
        return code
    matches = re.findall(r"\bfrom\s+([a-zA-Z0-9_.-]+)\s+import\s+([a-zA-Z0-9_]+)", code)
    squeezed_context = []
    for mod_name, symbol in matches:
        mod_path = f"{mod_name}.py"
        search_paths = [mod_path]
        for root, dirs, files in os.walk("."):
            if f"{mod_name}.py" in files:
                search_paths.append(os.path.join(root, f"{mod_name}.py"))
                break
        resolved_path = None
        for p in search_paths:
            if os.path.exists(p):
                resolved_path = p
                break
        if resolved_path:
            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    mod_content = f.read()
                sliced_helper = ast_recursive_slice(mod_content, symbol)
                if sliced_helper:
                    squeezed_context.append(f"# --- Automatically Squeezed Inline Import Context for {mod_name}.{symbol} ---\n{sliced_helper}\n# --- End Context ---")
            except Exception:
                pass
    if squeezed_context:
        return code + "\n\n" + "\n\n".join(squeezed_context)
    return code

def optimize_text_content(text, scrub=True):
    """Interceptors to automatically scrub secrets and squeeze decompiled C pseudocode in chat inputs."""
    # 1. First run secret scrubbing
    text, scrub_summary = scrub_text(text, active=scrub)
    
    # 2. Look for triple backtick code blocks to see if we can squeeze them
    def squeeze_block(match):
        lang = (match.group(1) or "").lower()
        code = match.group(2)
        # Check if it looks like decompiled C code
        if "FUN_" in code or "in_GS_OFFSET" in code or "__stack_chk_fail" in code or "undefined" in code:
            squeezed = apply_squeeze_filters(code)
            return f"```{lang}\n{squeezed}\n```"
        # Check for python inline imports
        if lang in ["py", "python"]:
            squeezed = resolve_and_squeeze_imports(code, lang)
            return f"```{lang}\n{squeezed}\n```"
        return match.group(0)
    
    text = re.sub(r"```([a-zA-Z0-9+#_.-]*)\n([\s\S]*?)```", squeeze_block, text)
    
    return text, scrub_summary

def optimize_payload(path, body_bytes, scrub_active=True):
    """Parses JSON API payload and optimizes prompts inside user messages."""
    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return body_bytes, 0, 0, "Unknown", "Unknown", ""
        
    model_name = data.get("model", "Unknown")
    messages = data.get("messages", [])
    
    if not isinstance(messages, list):
        return body_bytes, 0, 0, model_name, "Unknown", ""
        
    # Apply sliding-window budgeting / auto-slicing
    prices = load_prices()
    max_budget = prices.get("max_context_budget", 15000)
    messages, sliced_any = auto_slice_prompt(messages, max_budget)
    if sliced_any:
        data["messages"] = messages
        
    original_text_parts = []
    total_scrub_summary = []
    
    def process_content_item(content_item):
        if isinstance(content_item, str):
            original_text_parts.append(content_item)
            optimized, summary = optimize_text_content(content_item, scrub=scrub_active)
            if summary:
                total_scrub_summary.append(summary)
            return optimized
        elif isinstance(content_item, list):
            new_list = []
            for item in content_item:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_val = item.get("text", "")
                    original_text_parts.append(text_val)
                    optimized, summary = optimize_text_content(text_val, scrub=scrub_active)
                    if summary:
                        total_scrub_summary.append(summary)
                    new_item = dict(item)
                    new_item["text"] = optimized
                    new_list.append(new_item)
                else:
                    new_list.append(item)
            return new_list
        return content_item

    for msg in messages:
        if isinstance(msg, dict) and "content" in msg:
            msg["content"] = process_content_item(msg["content"])
            
    modified_body_bytes = json.dumps(data).encode("utf-8")
    
    orig_tokens = 0
    new_tokens = 0
    counter_used = "tiktoken"
    system_tokens = 0
    code_tokens = 0
    prose_tokens = 0
    
    if original_text_parts:
        full_original_text = "\n".join(original_text_parts)
        optimized_text_parts = []
        for msg in messages:
            if isinstance(msg, dict) and "content" in msg:
                content = msg["content"]
                if isinstance(content, str):
                    optimized_text_parts.append(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            optimized_text_parts.append(item.get("text", ""))
        full_optimized_text = "\n".join(optimized_text_parts)
        
        orig_tokens, counter_used = count_tokens(full_original_text)
        new_tokens, _ = count_tokens(full_optimized_text)
        
        for msg in messages:
            if not isinstance(msg, dict): continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    toks, _ = count_tokens(content)
                    system_tokens += toks
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            toks, _ = count_tokens(item.get("text", ""))
                            system_tokens += toks
            else:
                text_val = ""
                if isinstance(content, str):
                    text_val = content
                elif isinstance(content, list):
                    text_val = "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
                if text_val:
                    code_blocks = re.findall(r"```[a-zA-Z0-9+#_.-]*\n([\s\S]*?)```", text_val)
                    prose = re.sub(r"```[\s\S]*?```", "", text_val)
                    prose_toks, _ = count_tokens(prose)
                    prose_tokens += prose_toks
                    for cb in code_blocks:
                        cb_toks, _ = count_tokens(cb)
                        code_tokens += cb_toks
        
    scrub_summary = "; ".join(total_scrub_summary) if total_scrub_summary else ""
    return modified_body_bytes, orig_tokens, new_tokens, model_name, counter_used, scrub_summary, system_tokens, code_tokens, prose_tokens

def failover_openai_to_anthropic(req_bytes, is_stream_req, orig_model):
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return None, "ANTHROPIC_API_KEY not found in environment."
        
    try:
        openai_data = json.loads(req_bytes.decode("utf-8"))
    except Exception as e:
        return None, f"Failed to parse original payload: {str(e)}"
        
    openai_messages = openai_data.get("messages", [])
    anthropic_messages = []
    system_parts = []
    
    for m in openai_messages:
        if not isinstance(m, dict): continue
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
        elif role in ["user", "assistant"]:
            anthropic_messages.append({"role": role, "content": content})
            
    system_prompt = "\n".join(system_parts) if system_parts else None
    failover_model = "claude-3-5-sonnet-20241022"
    
    anthropic_payload = {
        "model": failover_model,
        "messages": anthropic_messages,
        "max_tokens": openai_data.get("max_tokens", 2048),
    }
    if system_prompt:
        anthropic_payload["system"] = system_prompt
    if "temperature" in openai_data:
        anthropic_payload["temperature"] = openai_data["temperature"]
    if "top_p" in openai_data:
        anthropic_payload["top_p"] = openai_data["top_p"]
        
    import urllib.request
    req_headers = {
        "x-api-key": anthropic_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(anthropic_payload).encode("utf-8"),
        headers=req_headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
            if resp.status == 200:
                anthropic_res = json.loads(resp.read().decode("utf-8"))
                content_list = anthropic_res.get("content", [])
                assistant_text = ""
                for part in content_list:
                    if isinstance(part, dict) and part.get("type") == "text":
                        assistant_text += part.get("text", "")
                        
                usage = anthropic_res.get("usage", {})
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                
                if not is_stream_req:
                    openai_res = {
                        "id": f"chatcmpl-failover-{int(time.time())}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": failover_model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": assistant_text
                                },
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {
                            "prompt_tokens": in_tok,
                            "completion_tokens": out_tok,
                            "total_tokens": in_tok + out_tok
                        }
                    }
                    return json.dumps(openai_res), None
                else:
                    return assistant_text, None
    except Exception as e:
        return None, f"Anthropic API failover request failed: {str(e)}"
    
    return None, "Failover completed with no response."

def start_gateway_server(host, port, scrub=True):
    """Starts a multi-threaded HTTP server forwarding to OpenAI / Anthropic."""
    import http.server
    import socketserver
    
    class TokenPinchGatewayHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
            
        def do_GET(self):
            if self.path in ["/", "/v1", "/v1/models"]:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                status_data = {
                    "status": "running",
                    "product": "TokenPinch Gateway",
                    "version": "1.2.0",
                    "message": "Ready to intercept and secure your AI prompts."
                }
                self.wfile.write(json.dumps(status_data).encode("utf-8"))
            else:
                self.send_error(404, "Not Found")
                
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
            
            if self.path.startswith("/v1/chat/completions"):
                upstream_url = "https://api.openai.com/v1/chat/completions"
                is_interceptable = True
            elif self.path.startswith("/v1/messages"):
                upstream_url = "https://api.anthropic.com/v1/messages"
                is_interceptable = True
            elif self.path.startswith("/v1/"):
                upstream_url = f"https://api.openai.com{self.path}"
                is_interceptable = False
            else:
                self.send_error(404, "Unknown endpoint")
                return
                
            modified_bytes = body_bytes
            orig_tokens = 0
            new_tokens = 0
            model_name = "Unknown"
            counter_used = "tiktoken"
            scrub_summary = ""
            is_stream_req = False
            prompt_text = ""
            
            if is_interceptable and len(body_bytes) > 0:
                try:
                    req_data = json.loads(body_bytes.decode("utf-8"))
                    model_name = req_data.get("model", "Unknown")
                    is_stream_req = req_data.get("stream", False)
                    prompt_parts = []
                    for m in req_data.get("messages", []):
                        if isinstance(m, dict) and "content" in m:
                            cnt = m["content"]
                            if isinstance(cnt, str):
                                prompt_parts.append(cnt)
                            elif isinstance(cnt, list):
                                for item in cnt:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        prompt_parts.append(item.get("text", ""))
                    prompt_text = "\n".join(prompt_parts)
                except Exception:
                    pass
            
            if is_interceptable and prompt_text:
                cached_res = lookup_prompt_cache(prompt_text)
                if cached_res:
                    response_str, cached_was_stream, hit_type = cached_res
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    orig_tok, _ = count_tokens(prompt_text)
                    input_price = load_prices().get("input_price_per_million", 3.0) / 1000000.0
                    savings_usd = orig_tok * input_price
                    
                    log_audit("CacheHit", model_name, orig_tok, 0, savings_usd, f"Saved ${savings_usd:.5f} (100% Free)", "cache")
                    
                    print(f"[{timestamp}] 🧠 \033[1;35m{hit_type}\033[0m for \033[1;36m{model_name}\033[0m:")
                    print(f"  - Prompt Tokens:   {orig_tok:,}")
                    print(f"  - Cost:            \033[1;32m$0.00 (100% Free Tokens!)\033[0m")
                    print("-" * 50)
                    
                    self.send_response(200)
                    if is_stream_req:
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()
                        for line in response_str.splitlines():
                            self.wfile.write((line + "\n").encode("utf-8"))
                            self.wfile.flush()
                            time.sleep(0.005)
                    else:
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(response_str.encode("utf-8"))
                    return

            system_tokens = 0
            code_tokens = 0
            prose_tokens = 0
            if is_interceptable and len(body_bytes) > 0:
                modified_bytes, orig_tokens, new_tokens, model_name, counter_used, scrub_summary, system_tokens, code_tokens, prose_tokens = optimize_payload(
                    self.path, body_bytes, scrub_active=scrub
                )
                
            forward_headers = {}
            for key, val in self.headers.items():
                if key.lower() not in ["host", "content-length", "accept-encoding", "connection"]:
                    forward_headers[key] = val
                    
            req = urllib.request.Request(
                upstream_url,
                data=modified_bytes if len(modified_bytes) > 0 else None,
                headers=forward_headers,
                method="POST"
            )
            
            if is_interceptable and orig_tokens > 0:
                saved_tokens = max(0, orig_tokens - new_tokens)
                prices = load_prices()
                input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
                savings_usd = saved_tokens * input_price
                percent_saved = (saved_tokens / orig_tokens * 100) if orig_tokens > 0 else 0.0
                
                log_audit("Gateway", model_name, orig_tokens, new_tokens, savings_usd, f"Saved ${savings_usd:.5f}", counter_used, system_tokens, code_tokens, prose_tokens)
                
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp}] 🤏 Intercepted prompt for \033[1;36m{model_name}\033[0m:")
                print(f"  - Original Tokens: {orig_tokens:,}")
                print(f"  - Optimized Tokens: {new_tokens:,}")
                print(f"  - Tokens Saved:    \033[32m{saved_tokens:,} ({percent_saved:.1f}%)\033[0m")
                print(f"  - Estimated Saved: \033[1;32m${savings_usd:.5f}\033[0m")
                if scrub_summary:
                    print(f"  - Security Action: \033[1;33m{scrub_summary}\033[0m")
                print("-" * 50)
                
            try:
                with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
                    self.send_response(resp.status)
                    for header, val in resp.getheaders():
                        if header.lower() not in ["content-length", "connection"]:
                            self.send_header(header, val)
                    self.end_headers()
                    
                    captured_response_bytes = bytearray()
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        captured_response_bytes.extend(chunk)
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        
                    if resp.status == 200 and is_interceptable and prompt_text:
                        try:
                            response_str = captured_response_bytes.decode("utf-8", errors="ignore")
                            save_prompt_cache(prompt_text, response_str, is_stream_req)
                        except Exception:
                            pass
            except urllib.error.HTTPError as e:
                # Trigger failover routing on rate limits (429) or server outages (5xx)
                if e.code in [429, 500, 502, 503, 504] and is_interceptable and self.path.startswith("/v1/chat/completions"):
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{timestamp}] 🚨 \033[1;31mUpstream OpenAI Error {e.code} Intercepted!\033[0m")
                    print(f"👉 Activating Smart Model Failover Routing to Anthropic Claude-3.5...")
                    
                    failover_res, err = failover_openai_to_anthropic(modified_bytes, is_stream_req, model_name)
                    if failover_res:
                        print(f"[{timestamp}] 🌐 \033[1;32mFailover Successful!\033[0m Returned Claude response seamlessly to client.")
                        print("-" * 50)
                        
                        orig_tok, _ = count_tokens(prompt_text)
                        input_price = load_prices().get("input_price_per_million", 3.0) / 1000000.0
                        log_audit("FailoverRouting", f"failover:{model_name}->claude-3.5", orig_tok, 0, orig_tok * input_price, f"Failover OK ({e.code})", "tiktoken")
                        
                        self.send_response(200)
                        if not is_stream_req:
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(failover_res.encode("utf-8"))
                        else:
                            self.send_header("Content-Type", "text/event-stream")
                            self.send_header("Cache-Control", "no-cache")
                            self.send_header("Connection", "keep-alive")
                            self.end_headers()
                            
                            # Smooth streaming chunk simulation
                            words = failover_res.split(" ")
                            for idx, word in enumerate(words):
                                chunk_text = word if idx == 0 else " " + word
                                chunk_data = {
                                    "id": f"chatcmpl-failover-{int(time.time())}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": "claude-3-5-sonnet-20241022",
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {"content": chunk_text},
                                            "finish_reason": None
                                        }
                                    ]
                                }
                                self.wfile.write(f"data: {json.dumps(chunk_data)}\n\n".encode("utf-8"))
                                self.wfile.flush()
                                time.sleep(0.015)
                                
                            done_data = {
                                "id": f"chatcmpl-failover-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": "claude-3-5-sonnet-20241022",
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": "stop"
                                    }
                                ]
                            }
                            self.wfile.write(f"data: {json.dumps(done_data)}\n\n".encode("utf-8"))
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                        return
                    else:
                        print(f"[{timestamp}] ⚠️ \033[1;33mFailover Routing Attempted but Failed:\033[0m {err}")
                        print("-" * 50)
                        
                self.send_response(e.code)
                for header, val in e.headers.items():
                    if header.lower() not in ["content-length", "connection"]:
                        self.send_header(header, val)
                self.end_headers()
                self.wfile.write(e.read())
                self.wfile.flush()
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err_data = {"error": {"message": f"TokenPinch Gateway upstream connection error: {str(e)}"}}
                self.wfile.write(json.dumps(err_data).encode("utf-8"))
                
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        
    max_retries = 5
    current_port = port
    server = None
    
    for attempt in range(max_retries):
        try:
            server = ThreadedHTTPServer((host, current_port), TokenPinchGatewayHandler)
            break
        except Exception as e:
            if "Address already in use" in str(e) and attempt < max_retries - 1:
                print(f"⚠️ Port {current_port} is already in use. Retrying on next port...")
                current_port += 1
            else:
                print(f"\n❌ Error starting gateway server: {str(e)}")
                if "Address already in use" in str(e):
                    print(f"👉 Port {current_port} is already in use. Try running on a different port using:")
                    print(f"   \033[1;36mtokenpinch gateway --port {current_port+1}\033[0m\n")
                sys.exit(1)
                
    print(BANNER)
    print("🔒 \033[1;36mTokenPinch Secure LLM Proxy Gateway\033[0m")
    print("==================================================")
    print(f"  - Host:           http://{host}:{current_port}")
    print(f"  - OpenAI Base:    http://{host}:{current_port}/v1")
    print(f"  - Anthropic Base: http://{host}:{current_port}/v1")
    print(f"  - Security:       Secret scrubbing is {'\033[32mENABLED\033[0m' if scrub else '\033[31mDISABLED\033[0m'}")
    print("==================================================")
    print("\n👉 Configure your AI client (Cursor, VS Code, etc.) to use this base URL.")
    print("   All prompts will be automatically optimized and scrubbed in real-time!")
    print("   Press \033[31mCtrl+C\033[0m to stop the gateway.\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Gateway stopped gracefully. See you next time!")
        sys.exit(0)


PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/com.tokenpinch.app.plist")

def get_app_bundle_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if "Contents/MacOS" in exe_dir:
            return os.path.abspath(os.path.join(exe_dir, "..", ".."))
    return "/Users/Tariq/Desktop/TokenPinch.app"

def set_launch_at_login(enabled):
    if not enabled:
        try:
            if os.path.exists(PLIST_PATH):
                os.remove(PLIST_PATH)
            return True
        except Exception:
            return False
            
    app_path = get_app_bundle_path()
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tokenpinch.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-g</string>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    try:
        os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
        with open(PLIST_PATH, "w", encoding="utf-8") as f:
            f.write(plist_content)
        return True
    except Exception:
        return False

def is_launch_at_login_enabled():
    return os.path.exists(PLIST_PATH)


def run_tray_app():
    """Starts the native macOS Menu Bar Status/Tray App."""
    if not rumps:
        print("Error: 'rumps' library not found. Run 'pip3 install rumps' first.")
        sys.exit(1)
        
    class TokenPinchTrayApp(rumps.App):
        def __init__(self):
            super(TokenPinchTrayApp, self).__init__("🤏 $0.00")
            self.menu = [
                rumps.MenuItem("🤏 TokenPinch: $0.00 Saved", callback=None),
                rumps.MenuItem("🔄 Active Runs: 0", callback=None),
                None,
                rumps.MenuItem("📋 Squeeze Clipboard Code", callback=self.menu_squeeze_clipboard),
                rumps.MenuItem("🔒 Scrub Clipboard Secrets", callback=self.menu_scrub_clipboard),
                None,
                rumps.MenuItem("📊 Open Spend Dashboard...", callback=self.open_dashboard),
                rumps.MenuItem("⚡ Start Proxy Gateway", callback=self.toggle_gateway),
                rumps.MenuItem("⚙️ Update Pricing Rates...", callback=self.update_prices_dialog),
                rumps.MenuItem("Launch at Login", callback=self.toggle_login_startup),
                None,
            ]
            self.gateway_process = None
            self.menu["Launch at Login"].state = 1 if is_launch_at_login_enabled() else 0
            
            self.timer = rumps.Timer(self.update_stats, 5) # update stats every 5 seconds
            self.timer.start()
            self.update_stats(None)
            self.start_gateway()

        def start_gateway(self):
            try:
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                    self.gateway_process = subprocess.Popen([exe_path, "gateway"])
                else:
                    self.gateway_process = subprocess.Popen([sys.executable, __file__, "gateway"])
                self.menu["⚡ Start Proxy Gateway"].title = "🛑 Stop Proxy Gateway"
            except Exception as e:
                pass

        def update_stats(self, _):
            total_savings = 0.0
            active_runs = 0
            total_tokens_saved = 0
            try:
                if os.path.exists(CSV_PATH):
                    with open(CSV_PATH, 'r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        next(reader) # skip header
                        for r in reader:
                            active_runs += 1
                            total_savings += float(re.search(r'\$?([0-9.]+)', r[6]).group(1)) if "Saved" in r[6] else 0.0
                            try:
                                orig = int(r[3])
                                new = int(r[4])
                                total_tokens_saved += max(0, orig - new)
                            except Exception:
                                pass
            except Exception:
                pass
                
            if total_tokens_saved >= 1000000:
                tokens_str = f"{total_tokens_saved / 1000000.0:.1f}M"
            elif total_tokens_saved >= 1000:
                tokens_str = f"{total_tokens_saved / 1000.0:.1f}K"
            else:
                tokens_str = f"{total_tokens_saved}"
                
            if total_tokens_saved > 0:
                self.title = f"🤏 ${total_savings:.2f} Saved ({tokens_str} Tokens)"
            else:
                self.title = f"🤏 $0.00 Saved"
                
            self.menu["🤏 TokenPinch: $0.00 Saved"].title = f"🤏 TokenPinch: ${total_savings:.2f} Saved"
            self.menu["🔄 Active Runs: 0"].title = f"🔄 Active Runs: {active_runs}"

        def open_dashboard(self, _):
            generate_dashboard()

        def toggle_gateway(self, sender):
            if sender.title == "⚡ Start Proxy Gateway":
                self.start_gateway()
                rumps.notification("TokenPinch", "Gateway Started", "Secure proxy is now live on http://127.0.0.1:8799")
            else:
                if self.gateway_process:
                    self.gateway_process.terminate()
                    self.gateway_process = None
                sender.title = "⚡ Start Proxy Gateway"
                rumps.notification("TokenPinch", "Gateway Stopped", "Secure proxy gateway is offline.")

        def toggle_login_startup(self, sender):
            current_state = sender.state
            new_state = 0 if current_state == 1 else 1
            success = set_launch_at_login(new_state == 1)
            if success:
                sender.state = new_state
                status_msg = "enabled" if new_state == 1 else "disabled"
                rumps.notification("TokenPinch", "Startup Settings Updated", f"Launch at Login has been {status_msg}.")
            else:
                rumps.alert("Error", "Could not modify launch settings.")

        def update_prices_dialog(self, _):
            prices = load_prices()
            current_input = prices.get("input_price_per_million", 3.0)
            
            window = rumps.Window(
                message=f"Enter input price per million tokens (USD):\n(Current rate: ${current_input:.2f} / Million tokens)",
                title="⚙️ Recalibrate Model Pricing",
                default_text=f"{current_input:.2f}",
                ok="Save",
                cancel="Cancel"
            )
            response = window.run()
            if response.clicked == 1:
                try:
                    new_val = float(response.text.strip())
                    if new_val < 0: raise ValueError
                    prices["input_price_per_million"] = new_val
                    prices["set_date"] = datetime.now().strftime("%Y-%m-%d")
                    with open(PRICES_PATH, "w", encoding="utf-8") as f:
                        json.dump(prices, f, indent=2)
                    rumps.notification("TokenPinch", "Pricing Updated", f"New rate set to ${new_val:.2f} per million tokens.")
                except ValueError:
                    rumps.alert("Invalid Input", "Please enter a valid positive decimal number (e.g. 2.50).")

        def menu_squeeze_clipboard(self, _):
            text = read_from_clipboard()
            if not text.strip():
                rumps.notification("TokenPinch", "Clipboard Empty", "Please copy some code before squeezing.")
                return
            
            squeezed = apply_squeeze_filters(text)
            scrubbed, scrub_summary = scrub_text(squeezed, active=True)
            
            copy_to_clipboard(scrubbed)
            
            orig_tok, orig_counter = count_tokens(text)
            new_tok, _ = count_tokens(scrubbed)
            saved_tok = max(0, orig_tok - new_tok)
            
            prices = load_prices()
            input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
            savings_usd = saved_tok * input_price
            
            log_audit("SqueezeClipboard", "Clipboard_Text", orig_tok, new_tok, savings_usd, f"Saved ${savings_usd:.5f}", orig_counter)
            
            rumps.notification(
                "TokenPinch", 
                "Decompiler Squeezed!", 
                f"Squeezed {orig_tok:,} -> {new_tok:,} tokens (Saved {saved_tok:,} tokens / ${savings_usd:.5f})!"
            )

        def menu_scrub_clipboard(self, _):
            text = read_from_clipboard()
            if not text.strip():
                rumps.notification("TokenPinch", "Clipboard Empty", "Please copy some text before scrubbing.")
                return
                
            scrubbed, scrub_summary = scrub_text(text, active=True)
            if not scrub_summary:
                rumps.notification("TokenPinch", "No Secrets Found", "Your clipboard is already clean.")
                return
                
            copy_to_clipboard(scrubbed)
            
            orig_tok, orig_counter = count_tokens(text)
            new_tok, _ = count_tokens(scrubbed)
            saved_tok = max(0, orig_tok - new_tok)
            
            prices = load_prices()
            input_price = prices.get("input_price_per_million", 3.0) / 1000000.0
            savings_usd = saved_tok * input_price
            
            log_audit("ScrubClipboard", "Clipboard_Text", orig_tok, new_tok, savings_usd, f"Saved ${savings_usd:.5f}", orig_counter)
            
            rumps.notification(
                "TokenPinch", 
                "Secrets Scrubbed!", 
                f"Redacted secrets on your clipboard! ({scrub_summary})"
            )
                
        def on_quit(self):
            if self.gateway_process:
                self.gateway_process.terminate()
                
    try:
        app = TokenPinchTrayApp()
        app.run()
    except Exception as e:
        print(f"Error running tray app: {str(e)}")
        sys.exit(1)


# ==================== MAIN DISPATCHER ====================

BANNER = """\033[1;36m
 _____     _              ____  _             _     
|_   _/__ | | _____ _ __ |  _ \\(_)_ __   ___| |__  
  | |/ _ \\| |/ / _ \\ '_ \\| |_) | | '_ \\ / __| '_ \\ 
  | | (_) |   <  __/ | | |  __/| | | | | (__| | | |
  |_|\\___/|_|\\_\\___|_| |_|_|   |_|_| |_|\\___|_| |_|
\033[0m\033[1;30m                    v1.2.0 | Context Optimization Suite\033[0m
"""

def run_scrub_command(filepath):
    """Standalone command to scrub secrets from a file and write to clipboard."""
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)
        
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    scrubbed, summary = scrub_text(content, active=True)
    copy_to_clipboard(scrubbed)
    
    print("Copied scrubbed file contents to clipboard!")
    if summary:
        print(summary)
    else:
        print("No secrets detected or redacted.")

def run_status_command():
    """Prints a gorgeous Terminal UI (TUI) dashboard of savings and performance."""
    import sqlite3
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, tool, target, input_tokens, output_tokens, cost_usd, status, counter_used
            FROM audit_logs
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
    except Exception:
        print("\n❌ No local database audit logs found. Try running some files first!")
        return

    if not rows:
        print("\n🤏 \033[1;36mTokenPinch TUI Dashboard\033[0m")
        print("==================================================")
        print("  No optimization runs recorded yet. Try running 'shrink', 'slice', or starting the 'gateway' proxy!")
        return

    total_savings = 0.0
    total_tokens_orig = 0
    total_tokens_new = 0
    tool_counts = {}
    
    for r in rows:
        status_str = r[6] if r[6] else ""
        if "Saved" in status_str:
            m = re.search(r'\$?([0-9.]+)', status_str)
            if m:
                total_savings += float(m.group(1))
        elif r[5] > 0:
            total_savings += r[5]
            
        total_tokens_orig += r[3]
        total_tokens_new += r[4]
        tool_counts[r[1]] = tool_counts.get(r[1], 0) + 1

    total_saved_tok = max(0, total_tokens_orig - total_tokens_new)
    multiplier = (total_tokens_orig / total_tokens_new) if total_tokens_new > 0 else 1.0
    
    print("\n🤏 \033[1;36mTokenPinch TUI Dashboard & Optimization Status\033[0m")
    print("==================================================")
    print(f" 💵 \033[1;32mTotal Cash Saved:\033[0m      ${total_savings:.4f} USD")
    print(f" 🎯 \033[1;34mTotal Tokens Saved:\033[0m    {total_saved_tok:,} tokens")
    print(f" 🔌 \033[1;35mActive Tool Runs:\033[0m      {len(rows):,} runs")
    print(f" 🔋 \033[1;33mRunway Multiplier:\033[0m     {multiplier:.1f}x slower burn rate")
    print("==================================================")
    
    print("\n📊 \033[1mRecent Audits (Last 5):\033[0m")
    print("----------------------------------------------------------------------")
    print(f"{'Timestamp':<19} | {'Tool':<15} | {'Saved %':<8} | {'Runway Meter':<20}")
    print("----------------------------------------------------------------------")
    
    for r in rows[:5]:
        ts = r[0]
        tool = r[1]
        orig_tok = r[3]
        new_tok = r[4]
        
        saved_tok = max(0, orig_tok - new_tok)
        pct = (saved_tok / orig_tok * 100) if orig_tok > 0 else 0.0
        
        bar_len = 10
        filled = int((pct / 100) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        
        pct_color = "\033[32m" if pct > 50 else "\033[33m" if pct > 20 else "\033[31m"
        print(f"{ts} | {tool:<15} | {pct_color}{pct:>6.1f}%\033[0m | [{pct_color}{bar}\033[0m]")
    print("----------------------------------------------------------------------")
    print("👉 For the full interactive financial analytics report, run: \033[1;36mtokenpinch dashboard\033[0m\n")

def run_client_command(client_name):
    """Prints copy-pasteable instructions for configuring a specific client to use TokenPinch."""
    client_name = client_name.lower().strip()
    print("\n🔌 \033[1;36mTokenPinch Client Integration Guide\033[0m")
    print("==================================================")
    
    if client_name in ["cursor", "cursor-ide"]:
        print("\033[1;32m👉 How to integrate TokenPinch with Cursor IDE:\033[0m")
        print("\n1. Open Cursor and open \033[1mCursor Settings\033[0m (Gear icon in top right).")
        print("2. Navigate to \033[1mModels\033[0m on the left menu.")
        print("3. Expand the \033[1mOpenAI\033[0m model section.")
        print("4. Toggle ON \"\033[1mOverride OpenAI Base URL\033[0m\".")
        print("5. Paste the local TokenPinch Gateway URL:")
        print("   👉 \033[1;36mhttp://127.0.0.1:8799/v1\033[0m")
        print("6. Paste any dummy API key (e.g., `sk-dummy`) in the API Key input.")
        print("\n🎉 Done! All prompts sent via Cursor will now be secure and optimized in the background!")
        
    elif client_name in ["vscode", "vs-code", "copilot"]:
        print("\033[1;32m👉 How to integrate TokenPinch with VS Code (via extensions like Continue/Cline):\033[0m")
        print("\nIn your extension settings (`config.json`), update your model provider configuration:")
        print("""{
  "models": [
    {
      "title": "TokenPinch (GPT-4o)",
      "provider": "openai",
      "model": "gpt-4o",
      "apiBase": "http://127.0.0.1:8799/v1",
      "apiKey": "sk-dummy"
    }
  ]
}""")
        print("🎉 Done! Continue/Cline will route all queries through TokenPinch secure gateway.")
        
    elif client_name in ["python", "openai-python"]:
        print("\033[1;32m👉 How to integrate TokenPinch in your Python scripts:\033[0m")
        print("\nInitialize your standard OpenAI client with the TokenPinch base URL:")
        print("""import os
from openai import OpenAI

# Initialize standard OpenAI client pointed to local TokenPinch secure proxy
client = OpenAI(
    base_url="http://127.0.0.1:8799/v1",
    api_key=os.environ.get("OPENAI_API_KEY", "sk-dummy")
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Optimize my local workspace code..."}]
)
print(response.choices[0].message.content)""")
        
    elif client_name in ["node", "js", "typescript", "openai-node"]:
        print("\033[1;32m👉 How to integrate TokenPinch in your Node/TS scripts:\033[0m")
        print("\nInitialize your standard OpenAI NPM client pointed to local TokenPinch base URL:")
        print("""import OpenAI from "openai";

const openai = new OpenAI({
  baseURL: "http://127.0.0.1:8799/v1",
  apiKey: process.env.OPENAI_API_KEY || "sk-dummy"
});

async function main() {
  const completion = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [{ role: "user", content: "Optimize this payload" }],
  });
  console.log(completion.choices[0].message.content);
}
main();""")
        
    else:
        print(f"\033[1;33mUnknown client '{client_name}'. Showing general integrations:\033[0m")
        print("\nSimply configure any SDK, library, or tool targeted at OpenAI/Anthropic to override")
        print("their default API base URL with the secure local TokenPinch proxy base URL:")
        print("   👉 \033[1;36mhttp://127.0.0.1:8799/v1\033[0m")
        print("\nSupported explicit client guides:")
        print("   - \033[36mcursor\033[0m")
        print("   - \033[36mvscode\033[0m")
        print("   - \033[36mpython\033[0m")
        print("   - \033[36mnode\033[0m")
        
    print("==================================================\n")

def main():
    # Parse options
    scrub = False if "--no-scrub" in sys.argv else True
    exact = True if "--exact" in sys.argv else False
    budget = None
    if "--budget" in sys.argv:
        try:
            idx = sys.argv.index("--budget")
            if idx + 1 < len(sys.argv):
                budget = int(sys.argv[idx + 1])
        except ValueError:
            pass
            
    # Filter positional arguments
    args = [a for a in sys.argv if a not in ["--no-scrub", "--exact"]]
    if "--budget" in args:
        try:
            idx = args.index("--budget")
            if idx + 1 < len(args):
                args.pop(idx + 1)
            args.pop(idx)
        except ValueError:
            pass

    if len(args) < 2:
        print(BANNER)
        print("\033[1mUsage:\033[0m tokenpinch <subcommand> [args]\n")
        print("\033[1;32mCommands:\033[0m")
        print("  \033[36mshrink\033[0m      Strip bodies & comments from code files to create skeletal layouts.")
        print("  \033[36mslice\033[0m       Extract a single class or function AST slice directly.")
        print("  \033[36msqueeze\033[0m     Strip canaries and casting clutter from decompiled C (Ghidra/IDA).")
        print("  \033[36mauto-heal\033[0m   Run compiler or test commands and isolate failing code.")
        print("  \033[36mscrub\033[0m       Scrub secrets and private data from a file directly.")
        print("  \033[36mgateway\033[0m     Launch the local proxy gateway to automatically scrub & optimize prompts.")
        print("  \033[36mtray\033[0m        Launch the native macOS Menu Bar Status/Tray App in your task bar.")
        print("  \033[36mstatus\033[0m      Show a beautiful visual Terminal UI (TUI) dashboard of savings.")
        print("  \033[36mclient\033[0m      Spit out instant copy-paste integration guides (cursor, vscode, python, node).")
        print("  \033[36mdashboard\033[0m   Open the gorgeous HTML financial savings dashboard.\n")
        print("\033[1;32mOptions:\033[0m")
        print("  --no-scrub  Disable secret scrubbing filter.")
        print("  --exact     Query Anthropic API for exact Claude token count (needs ANTHROPIC_API_KEY).")
        print("  --budget N  Limit the token budget of the squeeze command prompt to N tokens.")
        sys.exit(1)
        
    subcmd = args[1].lower()
    
    # Standard license check for core operations
    verify_license()
    
    if subcmd == "shrink":
        if len(args) < 3:
            print("Usage: tokenpinch shrink <file> [--no-scrub] [--exact]")
            sys.exit(1)
        run_shrink(args[2], exact=exact, scrub=scrub)
        
    elif subcmd == "slice":
        if len(args) < 4:
            print("Usage: tokenpinch slice <file> <symbol> [--no-scrub] [--exact]")
            sys.exit(1)
        run_slice(args[2], args[3], exact=exact, scrub=scrub)
        
    elif subcmd == "squeeze":
        if len(args) < 3:
            print("Usage: tokenpinch squeeze <file_or_folder> [--budget N] [--no-scrub] [--exact]")
            sys.exit(1)
        run_squeeze(args[2], budget=budget, exact=exact, scrub=scrub)
        
    elif subcmd == "auto-heal":
        if len(args) < 3:
            print("Usage: tokenpinch auto-heal <command> [--no-scrub] [--exact]")
            sys.exit(1)
        cmd_args = sys.argv[sys.argv.index(args[1])+1:]
        cmd_args = [c for c in cmd_args if c not in ["--no-scrub", "--exact"]]
        if "--budget" in cmd_args:
            try:
                b_idx = cmd_args.index("--budget")
                if b_idx + 1 < len(cmd_args):
                    cmd_args.pop(b_idx + 1)
                cmd_args.pop(b_idx)
            except ValueError:
                pass
        run_auto_heal(cmd_args, exact=exact, scrub=scrub)
        
    elif subcmd == "scrub":
        if len(args) < 3:
            print("Usage: tokenpinch scrub <file>")
            sys.exit(1)
        run_scrub_command(args[2])
        
    elif subcmd == "gateway":
        port = 8799
        host = "127.0.0.1"
        if "--port" in sys.argv:
            try:
                idx = sys.argv.index("--port")
                if idx + 1 < len(sys.argv):
                    port = int(sys.argv[idx + 1])
            except ValueError:
                pass
        if "--host" in sys.argv:
            try:
                idx = sys.argv.index("--host")
                if idx + 1 < len(sys.argv):
                    host = sys.argv[idx + 1]
            except ValueError:
                pass
        start_gateway_server(host, port, scrub=scrub)
        
    elif subcmd == "tray":
        run_tray_app()
        
    elif subcmd in ["status", "list"]:
        run_status_command()
        
    elif subcmd == "client":
        client_name = args[2] if len(args) > 2 else "help"
        run_client_command(client_name)
        
    elif subcmd == "dashboard":
        generate_dashboard()
        
    else:
        print(f"Unknown subcommand '{subcmd}'. Commands: shrink, slice, squeeze, auto-heal, scrub, status, client, dashboard, gateway, tray")
        sys.exit(1)

if __name__ == '__main__':
    main()
