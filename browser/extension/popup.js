const status = document.getElementById("status");
chrome.runtime.sendMessage({ type: "ping" }, function (resp) {
  if (chrome.runtime.lastError || !resp || !resp.ok) status.textContent = "TokenPinch unavailable";
  else status.textContent = "TokenPinch connected";
});

document.getElementById("enable").addEventListener("click", async function () {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) return;
  const origin = new URL(tab.url).origin + "/*";
  const ok = await chrome.permissions.request({ origins: [origin] });
  if (!ok) return;
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["policy.js", "adapters.js", "content.js"] });
  status.textContent = "Enabled on this site. Automatic send stays off until the site is verified.";
});
