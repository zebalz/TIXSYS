// Shared page helpers: copy buttons, growing text boxes, attached-file names, phone menu.
(function () {
  "use strict";

  // Copy buttons: <button data-copy="input-id">, optionally with <span class="copy-label">.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var input = document.getElementById(button.getAttribute("data-copy"));
    if (!input) return;
    var label = button.querySelector(".copy-label");
    function done() {
      var before = label ? label.textContent : null;
      if (label) label.textContent = "Copied";
      button.classList.add("copied");
      button.setAttribute("title", "Copied");
      setTimeout(function () {
        if (label) label.textContent = before;
        button.classList.remove("copied");
        button.setAttribute("title", "Copy link");
      }, 2000);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
    } else {
      input.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* text is selected for manual copy */ }
    }
  });

  // Text boxes that grow with what's typed: <textarea data-autogrow>
  function grow(box) {
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight + 2, window.innerHeight * 0.4) + "px";
  }
  document.querySelectorAll("textarea[data-autogrow]").forEach(function (box) {
    grow(box);
    box.addEventListener("input", function () { grow(box); });
  });

  // Show the names of attached files: <ul data-file-list="file-input-id">
  document.querySelectorAll("[data-file-list]").forEach(function (list) {
    var input = document.getElementById(list.getAttribute("data-file-list"));
    if (!input) return;
    input.addEventListener("change", function () {
      list.textContent = "";
      Array.prototype.forEach.call(input.files || [], function (file) {
        var item = document.createElement("li");
        item.textContent = file.name;
        item.title = file.name;
        list.appendChild(item);
      });
    });
  });

  // Phone-size menu: <button data-menu aria-controls="side">
  var menuButton = document.querySelector("[data-menu]");
  var side = document.getElementById("side");
  if (menuButton && side) {
    var scrim = null;
    var close = function () {
      side.classList.remove("open");
      menuButton.setAttribute("aria-expanded", "false");
      if (scrim) { scrim.remove(); scrim = null; }
    };
    menuButton.addEventListener("click", function () {
      if (side.classList.contains("open")) { close(); return; }
      side.classList.add("open");
      menuButton.setAttribute("aria-expanded", "true");
      scrim = document.createElement("div");
      scrim.className = "scrim";
      scrim.addEventListener("click", close);
      document.body.appendChild(scrim);
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  }

  // Forms that ask "are you sure?" first: <form data-confirm="Question?">
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var question = form.getAttribute && form.getAttribute("data-confirm");
    if (question && !window.confirm(question)) event.preventDefault();
  }, true);

  // Don't send a form twice if someone double-clicks.
  document.querySelectorAll("form[method=post]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      setTimeout(function () {
        form.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = true; });
      }, 0);
    });
  });
})();
