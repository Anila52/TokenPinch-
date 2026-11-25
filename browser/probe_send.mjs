const port = Number(process.argv[2]);
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const pages = list.filter((t) => t.type === "page" && /^https:/.test(t.url || ""));
for (const page of pages) {
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
      const rows = [];
      document.querySelectorAll('button, [role="button"]').forEach((el) => {
        const label = (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-testid') || '');
        if (!/send|submit|prompt/i.test(label) && !/send/i.test(el.innerText || '')) return;
        const box = el.getBoundingClientRect();
        rows.push([Math.round(box.width), Math.round(box.height), label.trim(), (el.innerText || '').trim().slice(0, 40)].join('|'));
      });
      return rows.slice(0, 20);
    })()`,
  });
  console.log(page.url.split("?")[0]);
  const rows = result.result ? result.result.value : [];
  if (!rows.length) console.log("  no send-labeled control");
  rows.forEach((row) => console.log("  " + row));
  ws.close();
}
