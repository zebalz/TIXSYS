// Staff workspace: new-ticket alerts, copy buttons, note form helpers.
(function () {
  "use strict";

  var app = document.getElementById("app");
  if (!app) return;

  // ---- Copy buttons ---------------------------------------------------------
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
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
      try { document.execCommand("copy"); done(); } catch (e) { /* selected for manual copy */ }
    }
  });

  // ---- Note form: "waiting on employee" only makes sense for discussion notes
  var waitingWrap = document.getElementById("waiting-wrap");
  if (waitingWrap) {
    var radios = document.querySelectorAll('input[name="kind"]');
    var sync = function () {
      var checked = document.querySelector('input[name="kind"]:checked');
      var show = !checked || checked.value === "discussion";
      waitingWrap.hidden = !show;
      if (!show) {
        var box = waitingWrap.querySelector("input[type=checkbox]");
        if (box) box.checked = false;
      }
    };
    radios.forEach(function (r) { r.addEventListener("change", sync); });
    sync();
  }

  // ---- New-ticket alerts ----------------------------------------------------
  var POLL_MS = 15000;
  var STORE_KEY = "tixsys-alerts";
  var pollUrl = app.getAttribute("data-poll-url");
  var toggle = document.getElementById("alerts-toggle");
  var note = document.getElementById("alerts-note");
  var badge = document.getElementById("new-badge");
  var banner = document.getElementById("new-banner");
  var bannerText = document.getElementById("new-banner-text");
  var baseTitle = document.title;
  var latestId = null;
  var unseen = 0;
  var audio = null;

  function readPref() {
    try { return window.localStorage.getItem(STORE_KEY) === "on"; } catch (e) { return false; }
  }
  function writePref(on) {
    try { window.localStorage.setItem(STORE_KEY, on ? "on" : "off"); } catch (e) { /* private window */ }
  }
  var alertsOn = readPref();

  function ensureAudio() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audio) audio = new Ctx();
    if (audio.state === "suspended") audio.resume();
    return audio;
  }

  function chime() {
    var ctx = ensureAudio();
    if (!ctx || ctx.state !== "running") return false;
    var start = ctx.currentTime + 0.02;
    [880, 1318.5].forEach(function (freq, i) {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      var t = start + i * 0.18;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.4);
    });
    return true;
  }

  function renderToggle() {
    if (!toggle) return;
    toggle.setAttribute("aria-pressed", alertsOn ? "true" : "false");
    toggle.textContent = alertsOn ? "Alerts are on" : "Turn on alerts";
    if (!note) return;
    if (!alertsOn) {
      note.textContent = "Sound and a desktop notification when a new ticket comes in.";
    } else if (audio && audio.state === "running") {
      note.textContent = "You'll hear a chime and see a notification. Keep this tab open.";
    } else {
      note.textContent = "Click anywhere on the page once so the browser allows the chime.";
    }
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      alertsOn = !alertsOn;
      writePref(alertsOn);
      if (alertsOn) {
        ensureAudio();
        if ("Notification" in window && Notification.permission === "default") {
          Notification.requestPermission().then(renderToggle);
        }
        setTimeout(function () { chime(); renderToggle(); }, 50);
      }
      renderToggle();
    });
  }
  // Browsers only allow sound after the person interacts with the page.
  ["pointerdown", "keydown"].forEach(function (type) {
    document.addEventListener(type, function once() {
      if (alertsOn) { ensureAudio(); setTimeout(renderToggle, 50); }
    }, { once: true });
  });

  function showNew(tickets) {
    unseen += tickets.length;
    document.title = "(" + unseen + ") " + baseTitle;
    if (badge) { badge.hidden = false; badge.textContent = String(unseen); }
    if (banner && bannerText) {
      var first = tickets[tickets.length - 1];
      bannerText.textContent = unseen === 1
        ? "New ticket #" + first.number + ": " + first.summary
        : unseen + " new tickets came in. Latest: #" + first.number + " " + first.summary;
      banner.classList.add("show");
    }
    if (!alertsOn) return;
    chime();
    if ("Notification" in window && Notification.permission === "granted") {
      tickets.slice(-3).forEach(function (t) {
        try {
          var n = new Notification("New ticket #" + t.number + " — " + t.board, {
            body: t.summary + "\nFrom " + t.requester,
            tag: "tixsys-" + t.number
          });
          n.onclick = function () { window.focus(); window.location.href = t.url; n.close(); };
        } catch (e) { /* some browsers only allow notifications from a service worker */ }
      });
    }
  }

  function poll() {
    var url = pollUrl + (latestId === null ? "?after=999999999999" : "?after=" + latestId);
    fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) {
        if (r.status === 401 || r.status === 403 || r.redirected) throw new Error("signed out");
        return r.json();
      })
      .then(function (data) {
        if (latestId !== null && data.new && data.new.length) showNew(data.new);
        latestId = data.latest_id;
      })
      .catch(function () { /* try again next time */ })
      .finally(function () { setTimeout(poll, POLL_MS); });
  }

  renderToggle();
  if (pollUrl) poll();
})();
