// Two jobs: copy a command, and (variant B) build the paste line from the ticked packs.
// No network calls and no storage.
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

  var line = document.getElementById("paste-line");
  var boxes = document.querySelectorAll(".pick input");
  if (!line || !boxes.length) return;
  var base = "Set up https://github.com/zaitsew/teyla";
  function update() {
    var ids = Array.prototype.filter.call(boxes, function (b) { return b.checked; })
      .map(function (b) { return b.value; });
    line.textContent = ids.length ? base + " and tick these packs: " + ids.join(", ") : base;
  }
  boxes.forEach(function (b) { b.addEventListener("change", update); });
  update();
})();
