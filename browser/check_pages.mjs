const port = Number(process.argv[2]);
const ext = "okinokbmeonplpacjnkiejnpnkkpalnd";
const list = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const pages = list.filter((t) => t.type === "page" && /^https:/.test(t.url || ""));
const out = [];
for (const page of pages) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const text = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve("timeout"), 4000);
    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: "document.querySelector('[data-tokenpinch]') ? document.querySelector('[data-tokenpinch]').innerText : 'NO_BADGE'", returnByValue: true } }));
    });
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id === 1) {
        clearTimeout(timer);
        resolve(msg.result && msg.result.result ? msg.result.result.value : "NO_RESULT");
        ws.close();
      }
    });
  });
  out.push({ url: page.url.split("?")[0], badge: text });
}
const workers = list.filter((t) => String(t.url || "").includes(ext)).map((t) => t.url);
console.log(JSON.stringify({ port, workers, pages: out }, null, 2));
