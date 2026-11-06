// Applies the saved theme and language before the app renders, to avoid a flash.
try {
  var t = localStorage.getItem("cp.theme") || "system";
  var dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  var l = localStorage.getItem("cp.lang");
  if (l === "ar" || l === "en") {
    document.documentElement.lang = l;
    document.documentElement.dir = l === "ar" ? "rtl" : "ltr";
  }
} catch (e) {}
