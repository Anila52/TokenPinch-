const test = require("node:test");
const assert = require("node:assert/strict");
const { planKeydown, planCompressResult } = require("./extension/policy.js");

const auto = { mode: "automatic", autoSend: true, connected: true, inFlight: false, unsupported: false, hasAttachment: false, empty: false, composing: false };
const enter = { key: "Enter", shiftKey: false, isComposing: false, keyCode: 13 };

test("shift enter and ime are left alone", function () {
  assert.equal(planKeydown(auto, { key: "Enter", shiftKey: true }).action, "ignore");
  assert.equal(planKeydown(auto, { key: "Enter", isComposing: true, keyCode: 229 }).action, "ignore");
});

test("duplicate send is blocked once", function () {
  assert.equal(planKeydown(Object.assign({}, auto, { inFlight: true }), enter).action, "block-duplicate");
});

test("bridge failure does not compress", function () {
  assert.equal(planKeydown(Object.assign({}, auto, { connected: false }), enter).action, "bypass");
  assert.equal(planCompressResult({ snapshot: "a", current: "a", error: "bridge" }).action, "keep");
  assert.equal(planCompressResult({ snapshot: "a", current: "a", error: "timeout" }).reason, "timeout");
});

test("an edit during compression keeps the newer draft", function () {
  const plan = planCompressResult({ snapshot: "hello", current: "hello!", compressed: "hello", error: "" });
  assert.equal(plan.action, "keep");
  assert.equal(plan.reason, "edited");
});

test("unsupported editor, attachment, and empty draft are skipped", function () {
  assert.equal(planKeydown(Object.assign({}, auto, { unsupported: true }), enter).action, "ignore");
  assert.equal(planKeydown(Object.assign({}, auto, { hasAttachment: true }), enter).action, "ignore");
  assert.equal(planKeydown(Object.assign({}, auto, { empty: true }), enter).action, "ignore");
});

test("a clean result sends once", function () {
  const plan = planCompressResult({ snapshot: "hello  there", current: "hello  there", compressed: "hello there", error: "" });
  assert.equal(plan.action, "replace-and-send-once");
  assert.equal(plan.text, "hello there");
});

test("preview and unverified sites do not take over enter", function () {
  assert.equal(planKeydown(Object.assign({}, auto, { mode: "preview" }), enter).action, "ignore");
  assert.equal(planKeydown(Object.assign({}, auto, { autoSend: false }), enter).action, "ignore");
});
