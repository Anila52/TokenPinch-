const port = Number(process.argv[2]);
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const page = list.find((t) => t.type === "page");
if (!page) {
  console.log("no page");
  process.exit(1);
}
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
    const resolve = pending.get(msg.id);
    pending.delete(msg.id);
    resolve(msg.result || msg);
  }
});
await new Promise((resolve) => ws.addEventListener("open", resolve));
await call("Page.enable");
await call("Page.navigate", { url: "chrome://extensions" });
await new Promise((r) => setTimeout(r, 1500));
const clicked = await call("Runtime.evaluate", {
  expression: `(() => {
    const mgr = document.querySelector('extensions-manager');
    if (!mgr || !mgr.shadowRoot) return 'no-manager';
    const toolbar = mgr.shadowRoot.querySelector('extensions-toolbar');
    if (!toolbar || !toolbar.shadowRoot) return 'no-toolbar';
    const dev = toolbar.shadowRoot.querySelector('#devMode');
    if (dev && !dev.checked) dev.click();
    const load = toolbar.shadowRoot.querySelector('#loadUnpacked');
    if (!load) return 'no-load';
    load.click();
    return 'clicked';
  })()`,
  returnByValue: true,
});
console.log(JSON.stringify(clicked.result || clicked));
ws.close();
