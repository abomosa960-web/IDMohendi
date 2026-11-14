const $ = (id) => document.getElementById(id);

chrome.storage.local.get({ enabled: true, port: 8765, token: "" }, (cfg) => {
  $("enabled").checked = cfg.enabled;
  $("port").value = cfg.port;
  $("token").value = cfg.token;
});

$("save").addEventListener("click", () => {
  chrome.storage.local.set(
    {
      enabled: $("enabled").checked,
      port: Number($("port").value) || 8765,
      token: $("token").value.trim(),
    },
    () => ($("msg").textContent = "تم الحفظ")
  );
});
