const port = Number(process.argv[2]);
const want = process.argv[3] || "extensions";
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
const page = list.find((t) => (t.url || "").includes(want) && t.type === "page") || list.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
function call(method, params) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => pending.set(id, resolve));
}
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg.result || msg);
    pending.delete(msg.id);
  }
});
await new Promise((resolve) => ws.addEventListener("open", resolve));
const result = await call("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => {
    function textOf(node, depth) {
      if (!node || depth > 6) return "";
      let out = "";
      const nodes = node.shadowRoot ? [node.shadowRoot, ...node.children] : [...(node.childNodes || [])];
      if (node.shadowRoot) out += textOf(node.shadowRoot, depth + 1);
      for (const child of node.children || []) out += textOf(child, depth + 1);
      if (node.id || node.tagName) {
        const t = (node.innerText || "").trim();
        if (t && t.length < 400 && (node.tagName === "EXTENSIONS-ITEM" || node.id === "name" || node.id === "devMode")) out += "\\n[" + (node.id || node.tagName) + "] " + t;
      }
      return out;
    }
    const body = document.body ? document.body.innerText.slice(0, 1500) : "";
    const mgr = document.querySelector("extensions-manager");
    return { url: location.href, body, hasManager: !!mgr, extra: mgr ? textOf(mgr, 0).slice(0, 1500) : "" };
  })()`,
});
console.log(JSON.stringify(result.result ? result.result.value : result, null, 2));
ws.close();
