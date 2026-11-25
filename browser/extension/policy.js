(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TokenPinchPolicy = factory();
})(typeof self !== "undefined" ? self : this, function () {
  function planKeydown(ctx, event) {
    if (!event || event.key !== "Enter") return { action: "ignore" };
    if (event.shiftKey || event.isComposing || event.keyCode === 229 || ctx.composing) return { action: "ignore" };
    if (ctx.mode !== "automatic" || !ctx.autoSend) return { action: "ignore" };
    if (ctx.unsupported || ctx.hasAttachment || ctx.empty) return { action: "ignore" };
    if (!ctx.connected) return { action: "bypass", reason: "bridge" };
    if (ctx.inFlight) return { action: "block-duplicate" };
    return { action: "compress" };
  }

  function planCompressResult(ctx) {
    if (!ctx || ctx.error) return { action: "keep", reason: (ctx && ctx.error) || "bridge" };
    if (ctx.current !== ctx.snapshot) return { action: "keep", reason: "edited" };
    if (typeof ctx.compressed !== "string") return { action: "keep", reason: "bridge" };
    return { action: "replace-and-send-once", text: ctx.compressed };
  }

  return { planKeydown: planKeydown, planCompressResult: planCompressResult };
});
