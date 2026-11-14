// يرسل الروابط إلى برنامج FreeDM المحلي.
const DEFAULTS = { enabled: true, port: 8765, token: "" };

async function sendToApp(url, referer, cookiesUrl) {
  const cfg = await chrome.storage.local.get(DEFAULTS);
  if (!cfg.token) return { ok: false, reason: "no-token" };

  // نرسل كوكيز الموقع حتى تعمل التحميلات التي تحتاج تسجيل دخول
  let cookies = "";
  try {
    const list = await chrome.cookies.getAll({ url: cookiesUrl || url });
    cookies = list.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (_) {}

  try {
    const res = await fetch(`http://127.0.0.1:${cfg.port}/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-FreeDM-Token": cfg.token },
      body: JSON.stringify({ url, referer: referer || "", cookies }),
    });
    return { ok: res.ok };
  } catch (_) {
    return { ok: false, reason: "app-offline" };
  }
}

// التقاط التحميلات من Chrome تلقائياً
chrome.downloads.onCreated.addListener(async (item) => {
  const url = item.finalUrl || item.url;
  if (!/^https?:\/\//i.test(url)) return;
  const cfg = await chrome.storage.local.get(DEFAULTS);
  if (!cfg.enabled) return;

  const res = await sendToApp(url, item.referrer);
  if (!res.ok) return; // لم يستلم البرنامج الطلب: يكمل المتصفح التحميل
  try {
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
  } catch (_) {}
});

// رسائل من زر الفيديو في الصفحات
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "send-to-freedm" && /^https?:\/\//i.test(msg.url || "")) {
    sendToApp(msg.url, msg.referer).then(sendResponse);
    return true; // رد غير متزامن
  }
  return false;
});
