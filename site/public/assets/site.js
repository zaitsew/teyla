// Copies a command. No network calls and no storage.
(function () {
  "use strict";

  function copy(button) {
    var target = document.getElementById(button.getAttribute("data-copy"));
    var label = button.textContent;
    var done = function (text) {
      button.textContent = text;
      window.setTimeout(function () { button.textContent = label; }, 1800);
    };
    if (!target) return;
    if (!navigator.clipboard) { done("Select it"); return; }
    navigator.clipboard.writeText(target.textContent.trim()).then(
      function () { done("Copied"); },
      function () { done("Select it"); }
    );
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () { copy(button); });
  });
})();
