const port = Number(process.argv[2]);
const path = process.argv[3];
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const page = list.find((t) => t.type === "page" && (t.url || "").startsWith("chrome://extensions")) || list.find((t) => t.type === "page");
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
if (!String(page.url || "").startsWith("chrome://extensions")) {
  await call("Page.enable");
  await call("Page.navigate", { url: "chrome://extensions" });
  await new Promise((r) => setTimeout(r, 1200));
}
const result = await call("Runtime.evaluate", {
  awaitPromise: true,
  returnByValue: true,
  expression: `new Promise((resolve) => {
    try {
      chrome.developerPrivate.loadUnpacked({ path: ${JSON.stringify(path)}, failOnManifestError: true }, (info) => {
        const err = chrome.runtime && chrome.runtime.lastError;
        resolve({ info: info || null, error: err ? err.message : "" });
      });
    } catch (e) { resolve({ error: String(e) }); }
  })`,
});
console.log(JSON.stringify(result.result ? result.result.value : result));
ws.close();
