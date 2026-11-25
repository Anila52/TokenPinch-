const port = Number(process.argv[2]);
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const page = list.find((t) => t.type === "page" && (t.url || "").includes("gemini.google.com"));
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
    const el = document.querySelector('div.ql-editor');
    if (!el) return ['no editor'];
    el.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, 'Say hi');
    const rows = [];
    document.querySelectorAll('button').forEach((btn) => {
      const box = btn.getBoundingClientRect();
      if (box.width < 8) return;
      const icon = btn.querySelector('mat-icon, svg');
      rows.push([Math.round(box.x), Math.round(box.y), btn.getAttribute('aria-label') || '', (btn.innerText || '').trim().slice(0, 20), icon ? icon.getAttribute('fonticon') || icon.getAttribute('data-mat-icon-name') || 'icon' : ''].join('|'));
    });
    return rows.slice(-12);
  })()`,
});
console.log(JSON.stringify(result.result ? result.result.value : result, null, 2));
ws.close();
