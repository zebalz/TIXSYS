// Employee portal: copy buttons.
(function () {
  "use strict";

  function copyFrom(button) {
    var input = document.getElementById(button.getAttribute("data-copy"));
    if (!input) return;
    var original = button.getAttribute("data-label") || button.textContent;
    button.setAttribute("data-label", original);
    function done() {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = original; }, 2000);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
    } else {
      input.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* the text is selected; the person can copy it */ }
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (button) copyFrom(button);
  });
})();
