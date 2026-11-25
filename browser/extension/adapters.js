(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TokenPinchAdapters = factory();
})(typeof self !== "undefined" ? self : this, function () {
  function visible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const box = el.getBoundingClientRect();
    return box.width > 20 && box.height > 10;
  }

  function first(selectors) {
    for (let i = 0; i < selectors.length; i++) {
      const nodes = document.querySelectorAll(selectors[i]);
      for (let j = 0; j < nodes.length; j++) if (visible(nodes[j])) return nodes[j];
    }
    return null;
  }

  function fileAttached() {
    const inputs = document.querySelectorAll("input[type='file']");
    for (let i = 0; i < inputs.length; i++) if (inputs[i].files && inputs[i].files.length) return true;
    return false;
  }

  const sites = [
    {
      id: "chatgpt",
      hosts: ["chatgpt.com", "chat.openai.com"],
      autoSend: true,
      findComposer: function () {
        return first(["textarea#prompt-textarea", "textarea#mobile-composer-prompt", "#prompt-textarea[contenteditable='true']", "div.ProseMirror#prompt-textarea"]);
      },
      findSend: function () {
        return first(["button[data-testid='send-button']", "button[aria-label='Send prompt']", "button[aria-label='Send message']"]);
      },
      hasAttachment: function () {
        return fileAttached() || !!document.querySelector("[data-testid='file-thumbnail'], [class*='attachment']");
      }
    },
    {
      id: "claude",
      hosts: ["claude.ai"],
      autoSend: true,
      findComposer: function () {
        return first(["div.ProseMirror[contenteditable='true']", "fieldset div[contenteditable='true']"]);
      },
      findSend: function () {
        return first(["button[aria-label='Send message']", "button[aria-label='Send Message']"]);
      },
      hasAttachment: function () {
        return fileAttached() || !!document.querySelector("[data-testid='file-thumbnail']");
      }
    },
    {
      id: "gemini",
      hosts: ["gemini.google.com"],
      autoSend: true,
      findComposer: function () {
        return first(["rich-textarea .ql-editor", "div.ql-editor[contenteditable='true']", "div[contenteditable='true'][aria-label*='prompt' i]"]);
      },
      findSend: function () {
        return first(["button[aria-label='Send message']", "button[aria-label='Send']"]);
      },
      hasAttachment: function () {
        return fileAttached() || !!document.querySelector(".uploader-file-preview, [data-test-id='file-preview']");
      }
    }
  ];

  function generic() {
    return {
      id: "generic",
      autoSend: false,
      findComposer: function () {
        if (root.__tokenpinchSelected && document.contains(root.__tokenpinchSelected)) return root.__tokenpinchSelected;
        const nodes = [];
        document.querySelectorAll("textarea, [contenteditable='true']").forEach(function (el) { if (visible(el)) nodes.push(el); });
        return nodes.length === 1 ? nodes[0] : null;
      },
      findSend: function () { return null; },
      hasAttachment: fileAttached,
      ambiguous: function () { return !this.findComposer(); }
    };
  }

  function forHost(host) {
    host = String(host || "").toLowerCase();
    for (let i = 0; i < sites.length; i++) {
      if (sites[i].hosts.indexOf(host) !== -1) return sites[i];
    }
    return generic();
  }

  return { forHost: forHost, sites: sites };
});
