const port = Number(process.argv[2] || 9335);
const folder = process.argv[3];
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
const page = list.find((t) => t.type === "page" && (t.url || "").includes("extensions"));
const ws = new WebSocket(page.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
const events = [];
function call(method, params) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => pending.set(id, resolve));
}
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.method) events.push(msg.method);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise((resolve) => ws.addEventListener("open", resolve));
await call("Page.enable");
const intercept = await call("Page.setInterceptFileChooserDialog", { enabled: true });
const openedPromise = new Promise((resolve) => {
  const timer = setTimeout(() => resolve(null), 5000);
  const onMsg = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === "Page.fileChooserOpened") {
      clearTimeout(timer);
      ws.removeEventListener("message", onMsg);
      resolve(msg.params);
    }
  };
  ws.addEventListener("message", onMsg);
});
const clicked = await call("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => {
    const mgr = document.querySelector("extensions-manager");
    const bar = mgr && mgr.shadowRoot.querySelector("extensions-toolbar");
    const dev = bar && bar.shadowRoot.querySelector("#devMode");
    const load = bar && bar.shadowRoot.querySelector("#loadUnpacked");
    const box = (el) => el ? el.getBoundingClientRect().toJSON() : null;
    return { devChecked: dev ? dev.checked : null, dev: box(dev), load: box(load) };
  })()`,
});
const boxes = clicked.result && clicked.result.result && clicked.result.result.value;
async function clickBox(box) {
  if (!box || box.width < 2) return false;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await call("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await call("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  return true;
}
if (boxes && boxes.dev && !boxes.devChecked) {
  await clickBox(boxes.dev);
  await new Promise((r) => setTimeout(r, 300));
}
await clickBox(boxes && boxes.load);
const opened = await openedPromise;
let handled = null;
if (opened) {
  handled = await call("Page.handleFileChooser", { action: "accept", files: [folder] });
  await new Promise((r) => setTimeout(r, 1500));
}
const names = await call("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => {
    const mgr = document.querySelector("extensions-manager");
    return [...mgr.shadowRoot.querySelectorAll("extensions-item")].map((item) => (item.shadowRoot.querySelector("#name") || {}).textContent || "");
  })()`,
});
console.log(JSON.stringify({
  interceptError: intercept.error || null,
  clicked: clicked.result && clicked.result.result && clicked.result.result.value,
  opened: opened || null,
  handledError: handled && handled.error || null,
  names: names.result && names.result.result && names.result.result.value,
  events: [...new Set(events)],
}, null, 2));
ws.close();
