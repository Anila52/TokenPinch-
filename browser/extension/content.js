(function () {
  const policy = self.TokenPinchPolicy;
  const adapters = self.TokenPinchAdapters;
  const host = location.hostname.replace(/^www\./, "");
  const adapter = adapters.forHost(host);
  const state = { mode: "preview", connected: false, inFlight: false, bypass: false, held: false };
  let badge;

  function draftOf(el) {
    if (!el) return "";
    if ("value" in el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT")) return el.value;
    return (el.innerText || "").replace(/\u00a0/g, " ");
  }

  function pageQuill(op, text) {
    const el = composer();
    if (!el) return Promise.resolve({ ok: false, result: "" });
    el.setAttribute("data-tokenpinch-target", "1");
    return new Promise(function (resolve) {
      try {
        chrome.runtime.sendMessage({ type: "quill", op: op, text: text || "" }, function (resp) {
          el.removeAttribute("data-tokenpinch-target");
          if (chrome.runtime.lastError || !resp) resolve({ ok: false, result: "" });
          else resolve({ ok: !!resp.ok, result: typeof resp.result === "string" ? resp.result : "" });
        });
      } catch (e) {
        el.removeAttribute("data-tokenpinch-target");
        resolve({ ok: false, result: "" });
      }
    });
  }

  function writeDraft(el, text) {
    el.focus();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value") || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
      proto.set.call(el, text);
      el.dispatchEvent(new InputEvent("input", { bubbles: true }));
      return el.value === text;
    }
    if (!el.isContentEditable) return false;
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
    const ok = document.execCommand("insertText", false, text);
    return ok && draftOf(el) === text;
  }

  function ensureBadge() {
    if (badge) return badge;
    badge = document.createElement("div");
    badge.setAttribute("data-tokenpinch", "badge");
    badge.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483646;background:#0b1632;color:#fff;font:12px/1.4 -apple-system,sans-serif;padding:8px 10px;border-radius:8px;max-width:240px;box-shadow:0 4px 16px rgba(0,0,0,.3)";
    badge.addEventListener("mousedown", function (e) { e.stopPropagation(); });
    document.documentElement.appendChild(badge);
    return badge;
  }

  function render(extra) {
    const el = ensureBadge();
    const modeBtn = adapter.autoSend ? "<button data-act='mode' style='margin-right:6px'>" + (state.mode === "automatic" ? "Automatic" : "Preview") + "</button>" : "";
    const held = state.held ? "<button data-act='unchanged'>Send unchanged</button>" : "";
    const pick = adapter.id === "generic" ? "<button data-act='pick'>Select chat input</button>" : "";
    el.innerHTML = "<div>" + (state.connected ? "TokenPinch connected" : "TokenPinch unavailable") + "</div>" +
      "<div data-savings style='color:#f2a81c'>" + (extra || "") + "</div>" +
      "<div style='margin-top:6px'>" + modeBtn + " <button data-act='optimise'>Optimise draft</button> " + held + " " + pick + "</div>";
  }

  function ask(type, text) {
    return new Promise(function (resolve) {
      try {
        chrome.runtime.sendMessage({ type: type, text: text, id: String(Date.now()) }, function (resp) {
          if (chrome.runtime.lastError || !resp) resolve({ ok: false, error: "bridge" });
          else resolve(resp);
        });
      } catch (e) {
        resolve({ ok: false, error: "bridge" });
      }
    });
  }

  function composer() {
    try { return adapter.findComposer(); } catch (e) { return null; }
  }

  async function optimise(sendAfter) {
    const el = composer();
    if (!el) return;
    const model = await pageQuill("read", "");
    const snapshot = model.ok ? model.result : draftOf(el);
    if (!snapshot.trim()) return;
    if (adapter.hasAttachment && adapter.hasAttachment()) return;
    state.inFlight = true;
    const resp = await ask("compress", snapshot);
    const again = await pageQuill("read", "");
    const current = again.ok ? again.result : draftOf(el);
    const plan = policy.planCompressResult({
      snapshot: snapshot,
      current: current,
      compressed: resp && resp.ok ? resp.text : undefined,
      error: resp && resp.ok ? "" : ((resp && resp.error) || "bridge")
    });
    state.inFlight = false;
    if (plan.action !== "replace-and-send-once") {
      state.held = true;
      render(plan.reason === "edited" ? "Draft changed. Nothing was overwritten." : "Kept your draft.");
      return;
    }
    if (model.ok) {
      const wrote = await pageQuill("write", plan.text);
      if (!wrote.ok) {
        await pageQuill("write", snapshot);
        state.held = true;
        render("Editor could not be updated. Draft kept.");
        return;
      }
    } else if (!writeDraft(el, plan.text)) {
      writeDraft(el, snapshot);
      state.held = true;
      render("Editor could not be updated. Draft kept.");
      return;
    }
    const savings = resp.tokens_before + " → " + resp.tokens_after + " tokens";
    if (!sendAfter) {
      render(savings);
      return;
    }
    const button = adapter.findSend && adapter.findSend();
    if (!button || button.disabled) {
      state.held = true;
      render("Send control was not verified. Draft updated, not sent.");
      return;
    }
    button.click();
    render(savings);
  }

  document.addEventListener("keydown", function (event) {
    const el = composer();
    if (!el || (event.target !== el && !el.contains(event.target))) return;
    const plan = policy.planKeydown({
      mode: state.mode,
      autoSend: !!adapter.autoSend,
      connected: state.connected,
      inFlight: state.inFlight,
      unsupported: !el,
      hasAttachment: !!(adapter.hasAttachment && adapter.hasAttachment()),
      empty: !draftOf(el).trim(),
      composing: event.isComposing
    }, { key: event.key, shiftKey: event.shiftKey, isComposing: event.isComposing, keyCode: event.keyCode });
    if (plan.action === "ignore" || plan.action === "bypass") return;
    if (state.bypass) { state.bypass = false; return; }
    event.preventDefault();
    event.stopPropagation();
    if (plan.action === "compress") optimise(true);
  }, true);

  document.addEventListener("click", function (event) {
    const act = event.target && event.target.getAttribute && event.target.getAttribute("data-act");
    if (!act) return;
    event.preventDefault();
    event.stopPropagation();
    if (act === "mode" && adapter.autoSend) {
      state.mode = state.mode === "automatic" ? "preview" : "automatic";
      chrome.storage.local.set({ ["tp-mode-" + host]: state.mode });
      render();
    } else if (act === "optimise") {
      optimise(false);
    } else if (act === "unchanged") {
      state.held = false;
      state.bypass = true;
      const button = adapter.findSend && adapter.findSend();
      if (button) button.click();
      render("Sending the draft unchanged.");
    } else if (act === "pick") {
      render("Click the chat input.");
      document.addEventListener("click", function pick(ev) {
        document.removeEventListener("click", pick, true);
        const node = ev.target && ev.target.closest && ev.target.closest("textarea, [contenteditable='true']");
        if (node) self.__tokenpinchSelected = node;
        render(node ? "Input selected. Automatic send stays off." : "No input selected.");
      }, true);
    }
  }, true);

  chrome.storage.local.get("tp-mode-" + host, function (saved) {
    if (saved && saved["tp-mode-" + host] === "automatic" && adapter.autoSend) state.mode = "automatic";
    ask("ping").then(function (resp) {
      state.connected = !!(resp && resp.ok && resp.connected);
      render(composer() ? "" : "Chat input not found.");
    });
  });
})();
