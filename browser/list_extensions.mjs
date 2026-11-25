const port = Number(process.argv[2]);
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const page = list.find((t) => t.type === "page");
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
await call("Page.enable");
await call("Page.navigate", { url: "chrome://extensions" });
await new Promise((r) => setTimeout(r, 1500));
const result = await call("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => {
    const mgr = document.querySelector('extensions-manager');
    if (!mgr || !mgr.shadowRoot) return 'no-manager';
    const items = mgr.shadowRoot.querySelectorAll('extensions-item');
    const rows = [];
    items.forEach((item) => {
      const name = item.shadowRoot && item.shadowRoot.querySelector('#name');
      rows.push((name && name.textContent || '').trim());
    });
    const dev = mgr.shadowRoot.querySelector('extensions-toolbar');
    const checked = dev && dev.shadowRoot && dev.shadowRoot.querySelector('#devMode') ? dev.shadowRoot.querySelector('#devMode').checked : null;
    return { count: rows.length, names: rows, devMode: checked };
  })()`,
});
console.log(JSON.stringify(result.result ? result.result.value : result, null, 2));
ws.close();
