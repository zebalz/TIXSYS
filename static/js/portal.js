// Employee portal: remember the person's details on this computer.
(function () {
  "use strict";

  var KEY = "tixsys-my-details";
  var FIELDS = ["name", "email", "phone", "location"];
  var form = document.getElementById("ticket-form");
  if (!form) return;

  function load() {
    try { return JSON.parse(window.localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function save(values) {
    try { window.localStorage.setItem(KEY, JSON.stringify(values)); } catch (e) { /* private window */ }
  }

  var saved = load();
  FIELDS.forEach(function (name) {
    var input = form.elements[name];
    if (input && !input.value && saved[name]) input.value = saved[name];
  });

  form.addEventListener("submit", function () {
    var values = {};
    FIELDS.forEach(function (name) {
      var input = form.elements[name];
      if (input) values[name] = input.value.trim();
    });
    save(values);
  });

  // Enter sends from the description box only with Ctrl/Cmd, so new lines still work.
  var box = form.querySelector("textarea[name=description]");
  if (box) {
    box.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      }
    });
  }
})();
