// Apply the saved light/dark theme before the app paints (avoids a white flash in dark mode).
try {
  var t = localStorage.getItem("mytech.theme");
  var d = t === "dark" || ((!t || t === "system") && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = d ? "dark" : "light";
} catch (e) {}
