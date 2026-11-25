const port = Number(process.argv[2]);
const ver = await fetch(`http://127.0.0.1:${port}/json/version`).then((r) => r.json());
const browser = new WebSocket(ver.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
function send(method, params, sessionId) {
  const id = ++seq;
  const msg = { id, method, params };
  if (sessionId) msg.sessionId = sessionId;
  browser.send(JSON.stringify(msg));
  return new Promise((resolve) => pending.set(id, resolve));
}
browser.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise((r) => browser.addEventListener("open", r));
await send("Target.setDiscoverTargets", { discover: true });

async function ensure(url) {
  const list = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
  const host = new URL(url).host;
  let page = list.find((t) => t.type === "page" && (t.url || "").includes(host));
  if (!page) {
    const created = await send("Target.createTarget", { url });
    const id = created.result && created.result.targetId;
    await new Promise((r) => setTimeout(r, 2500));
    const again = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
    page = again.find((t) => t.id === id) || again.find((t) => t.type === "page" && (t.url || "").includes(host));
  }
  return page;
}

async function evalPage(page, expression, awaitPromise) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let n = 0;
  const wait = new Map();
  function call(method, params) {
    const id = ++n;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve) => wait.set(id, resolve));
  }
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && wait.has(msg.id)) {
      wait.get(msg.id)(msg);
      wait.delete(msg.id);
    }
  });
  await new Promise((r) => ws.addEventListener("open", r));
  const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: !!awaitPromise });
  ws.close();
  return result.result && result.result.result ? result.result.result.value : result.result;
}

const sites = ["https://chatgpt.com/", "https://claude.ai/new", "https://gemini.google.com/app"];
const out = [];
for (const url of sites) {
  const page = await ensure(url);
  if (!page) {
    out.push({ url, error: "no page" });
    continue;
  }
  await evalPage(page, "location.href", false);
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let n = 0;
  const wait = new Map();
  function call(method, params) {
    const id = ++n;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve) => wait.set(id, resolve));
  }
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && wait.has(msg.id)) {
      wait.get(msg.id)(msg);
      wait.delete(msg.id);
    }
  });
  await new Promise((r) => ws.addEventListener("open", r));
  await call("Page.enable");
  await call("Page.reload", { ignoreCache: true });
  await new Promise((r) => setTimeout(r, 4500));
  const info = await call("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const badge = document.querySelector("[data-tokenpinch]");
      const composer = document.querySelector("textarea#prompt-textarea, textarea#mobile-composer-prompt, div.ProseMirror[contenteditable='true'], div.ql-editor, rich-textarea .ql-editor");
      const send = [...document.querySelectorAll("button")].filter(b => /send/i.test(b.getAttribute("aria-label") || "")).map(b => {
        const r = b.getBoundingClientRect();
        return (b.getAttribute("aria-label") || "") + " " + Math.round(r.width) + "x" + Math.round(r.height);
      });
      return {
        href: location.href.split("?")[0],
        badge: badge ? badge.innerText.replace(/\\s+/g, " ").trim() : "NO_BADGE",
        composer: composer ? composer.id || composer.getAttribute("aria-label") || composer.className.slice(0, 40) : "",
        send
      };
    })()`,
  });
  out.push(info.result && info.result.result ? info.result.result.value : info);
  ws.close();
}
console.log(JSON.stringify(out, null, 2));
browser.close();
