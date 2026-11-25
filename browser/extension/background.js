function nativeCall(payload, timeoutMs) {
  return new Promise(function (resolve) {
    let port;
    let done = false;
    const timer = setTimeout(function () {
      if (done) return;
      done = true;
      try { port.disconnect(); } catch (e) {}
      resolve({ ok: false, error: "timeout" });
    }, timeoutMs || 1500);
    try {
      port = chrome.runtime.connectNative("com.tokenpinch.browser");
    } catch (e) {
      clearTimeout(timer);
      resolve({ ok: false, error: "bridge" });
      return;
    }
    port.onMessage.addListener(function (resp) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try { port.disconnect(); } catch (e) {}
      resolve(resp && typeof resp === "object" ? resp : { ok: false, error: "bridge" });
    });
    port.onDisconnect.addListener(function () {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve({ ok: false, error: "bridge" });
    });
    port.postMessage(payload);
  });
}

function quillInPage(op, text) {
  var el = document.querySelector("[data-tokenpinch-target]");
  var host = el && el.closest("rich-textarea");
  var q = host && host.__quill;
  if (!q || typeof q.getText !== "function") return { ok: false, result: "" };
  if (op === "write" && typeof q.setText === "function") q.setText(text || "");
  var result = String(q.getText()).replace(/\n$/, "");
  return { ok: op !== "write" || result === (text || ""), result: result };
}

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg && msg.type === "quill" && sender.tab && sender.tab.id) {
    chrome.scripting.executeScript({
      target: { tabId: sender.tab.id },
      world: "MAIN",
      func: quillInPage,
      args: [msg.op, msg.text || ""]
    }).then(function (rows) {
      sendResponse(rows && rows[0] && rows[0].result ? rows[0].result : { ok: false, result: "" });
    }).catch(function () {
      sendResponse({ ok: false, result: "" });
    });
    return true;
  }
  if (!msg || (msg.type !== "ping" && msg.type !== "compress")) return;
  const payload = msg.type === "ping" ? { action: "ping" } : { action: "compress", text: msg.text, id: msg.id };
  nativeCall(payload, 1500).then(sendResponse);
  return true;
});
