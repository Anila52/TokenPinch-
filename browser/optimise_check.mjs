const port = Number(process.argv[2]);
const host = process.argv[3];
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
const page = list.find((t) => t.type === "page" && (t.url || "").includes(host));
if (!page) {
  console.log(JSON.stringify({ host, error: "no page" }));
  process.exit(0);
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
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise((r) => ws.addEventListener("open", r));
await call("Page.enable");
await call("Page.reload", { ignoreCache: true });
await new Promise((r) => setTimeout(r, 4000));
const result = await call("Runtime.evaluate", {
  returnByValue: true,
  awaitPromise: true,
  expression: `new Promise((resolve) => {
    const started = location.href;
    const draft = "hello    there\\n\\n\\nDo not  delete this.\\n\`\`\`\\nprint(1)\\n\`\`\`";
    function composer() {
      return document.querySelector("textarea#prompt-textarea, textarea#mobile-composer-prompt, div.ProseMirror[contenteditable='true'], div.ql-editor[contenteditable='true'], div.ql-editor");
    }
    function write(el, text) {
      el.focus();
      if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
        const proto = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
        proto.set.call(el, text);
        el.dispatchEvent(new InputEvent("input", { bubbles: true }));
        return;
      }
      const quill = el.closest("rich-textarea") && el.closest("rich-textarea").__quill;
      if (quill && quill.setText) { quill.setText(text); return; }
      const sel = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand("insertText", false, text);
    }
    function read(el) {
      if (!el) return "";
      if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") return el.value;
      return el.innerText || "";
    }
    let tries = 0;
    const timer = setInterval(() => {
      const badge = document.querySelector("[data-tokenpinch]");
      const text = badge ? badge.innerText : "";
      tries += 1;
      if ((!text.includes("connected") && tries < 8) || !composer()) {
        if (tries < 8) return;
      }
      clearInterval(timer);
      const el = composer();
      if (!el || !badge) {
        resolve({ href: location.href.split("?")[0], badge: text || "NO_BADGE", skipped: "no composer" });
        return;
      }
      write(el, draft);
      const button = badge.querySelector("[data-act='optimise']");
      if (button) button.click();
      setTimeout(() => {
        const now = read(composer());
        const send = [...document.querySelectorAll("button")].filter((b) => /send/i.test(b.getAttribute("aria-label") || ""));
        const visible = send.filter((b) => { const r = b.getBoundingClientRect(); return r.width > 20 && r.height > 10; });
        resolve({
          href: location.href.split("?")[0],
          samePage: location.href === started || location.href.split("?")[0] === started.split("?")[0],
          badge: (document.querySelector("[data-tokenpinch]") || {}).innerText || "",
          keptInstruction: now.includes("Do not  delete this."),
          collapsedSpaces: now.includes("hello there") && !now.includes("hello    there"),
          keptFence: now.includes("print(1)"),
          sent: false,
          visibleSend: visible.length,
          signedOut: /log in|sign in/i.test(document.body.innerText.slice(0, 4000))
        });
      }, 1800);
    }, 400);
  })`,
});
console.log(JSON.stringify(result.result && result.result.result ? result.result.result.value : result, null, 2));
ws.close();
