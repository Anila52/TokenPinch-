const port = Number(process.argv[2]);
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const pages = list.filter((t) => t.type === "page" && /^https:/.test(t.url || ""));
const out = [];
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
  await call("Page.enable");
  await call("Page.reload", { ignoreCache: true });
  await new Promise((r) => setTimeout(r, 3500));
  const badge = await call("Runtime.evaluate", {
    returnByValue: true,
    expression: "document.querySelector('[data-tokenpinch]') ? document.querySelector('[data-tokenpinch]').innerText : 'NO_BADGE'",
  });
  const composer = await call("Runtime.evaluate", {
    returnByValue: true,
    expression: "!!(document.querySelector('textarea#prompt-textarea, #prompt-textarea, div.ProseMirror[contenteditable=true], rich-textarea .ql-editor, div.ql-editor'))",
  });
  out.push({
    url: page.url.split("?")[0],
    badge: badge.result ? badge.result.value : badge,
    composer: composer.result ? composer.result.value : composer,
  });
  ws.close();
}
console.log(JSON.stringify(out, null, 2));
