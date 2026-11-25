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
      document.querySelectorAll('textarea, [contenteditable="true"], button').forEach((el) => {
        const box = el.getBoundingClientRect();
        if (box.width < 8 || box.height < 8) return;
        rows.push([el.tagName, el.id, el.getAttribute('aria-label') || '', el.getAttribute('data-testid') || '', el.getAttribute('placeholder') || '', el.className && String(el.className).slice(0, 60)].join('|'));
      });
      return rows.slice(0, 25);
    })()`,
  });
  console.log("\\n" + page.url.split("?")[0]);
  const rows = result.result ? result.result.value : result;
  if (Array.isArray(rows)) rows.forEach((row) => console.log(row));
  else console.log(JSON.stringify(rows));
  ws.close();
}
