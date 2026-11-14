// يضيف زر "إرسال إلى FreeDM" فوق عناصر <video> ذات روابط ملفات مباشرة.
// لا يعمل على يوتيوب أو على الفيديوهات المشفّرة (blob / MSE).
(() => {
  const host = location.hostname;
  if (/(^|\.)youtube\.com$|^youtu\.be$|googlevideo\.com$/i.test(host)) return;

  const DIRECT = /^https?:\/\//i;
  const buttons = new Map(); // video element -> button

  function directSource(video) {
    const src = video.currentSrc || video.src || video.querySelector("source")?.src || "";
    return DIRECT.test(src) ? src : "";
  }

  function makeButton(video) {
    const btn = document.createElement("button");
    btn.textContent = "⬇ FreeDM";
    btn.title = "إرسال هذا الفيديو إلى FreeDM";
    Object.assign(btn.style, {
      position: "absolute", zIndex: "2147483647", padding: "4px 8px",
      font: "12px Segoe UI, Tahoma, sans-serif", color: "#fff",
      background: "rgba(0,0,0,.75)", border: "1px solid #fff",
      borderRadius: "4px", cursor: "pointer", display: "none",
    });
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const url = directSource(video);
      if (!url) return;
      chrome.runtime.sendMessage({ type: "send-to-freedm", url, referer: location.href }, (res) => {
        btn.textContent = res && res.ok ? "✔ أُرسل" : "✖ البرنامج غير مفتوح";
        setTimeout(() => (btn.textContent = "⬇ FreeDM"), 2500);
      });
    });
    document.body.appendChild(btn);
    return btn;
  }

  function place() {
    for (const video of document.querySelectorAll("video")) {
      let btn = buttons.get(video);
      if (!directSource(video)) {
        if (btn) btn.style.display = "none";
        continue;
      }
      if (!btn) {
        btn = makeButton(video);
        buttons.set(video, btn);
      }
      const r = video.getBoundingClientRect();
      const visible = r.width > 80 && r.height > 60 && r.bottom > 0 && r.top < innerHeight;
      btn.style.display = visible ? "block" : "none";
      if (visible) {
        btn.style.left = `${window.scrollX + r.left + 8}px`;
        btn.style.top = `${window.scrollY + r.top + 8}px`;
      }
    }
  }

  setInterval(place, 700);
  window.addEventListener("resize", place);
})();
