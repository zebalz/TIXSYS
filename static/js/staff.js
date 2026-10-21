// Staff workspace: new-ticket alerts, note types, filter changes.
(function () {
  "use strict";

  var app = document.getElementById("app");
  if (!app) return;

  // ---- Filters apply as soon as one changes ---------------------------------
  document.querySelectorAll("form[data-autosubmit] select").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });

  // ---- Note composer: show what each note type does --------------------------
  var noteBox = document.getElementById("note-box");
  var waitingWrap = document.getElementById("waiting-wrap");
  var hint = document.getElementById("kind-hint");
  if (noteBox) {
    var sync = function () {
      var checked = document.querySelector('input[name="kind"]:checked');
      var kind = checked ? checked.value : "discussion";
      noteBox.className = noteBox.className.replace(/\bk-\w+/g, "").trim() + " k-" + kind;
      if (hint && hint.getAttribute("data-" + kind)) hint.textContent = hint.getAttribute("data-" + kind);
      if (waitingWrap) {
        waitingWrap.hidden = kind !== "discussion";
        if (kind !== "discussion") {
          var box = waitingWrap.querySelector("input[type=checkbox]");
          if (box) box.checked = false;
        }
      }
    };
    document.querySelectorAll('input[name="kind"]').forEach(function (r) { r.addEventListener("change", sync); });
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
    toggle.setAttribute("aria-checked", alertsOn ? "true" : "false");
    if (!note) return;
    if (!alertsOn) {
      note.textContent = "Chime and desktop notice";
    } else if (audio && audio.state === "running") {
      note.textContent = "On. Keep this tab open.";
    } else {
      note.textContent = "On. Click the page once to allow sound.";
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
    document.addEventListener(type, function () {
      if (alertsOn) { ensureAudio(); setTimeout(renderToggle, 50); }
    }, { once: true });
  });

  function showNew(tickets) {
    unseen += tickets.length;
    document.title = "(" + unseen + ") " + baseTitle;
    if (badge) { badge.hidden = false; badge.textContent = String(unseen); }
    if (banner && bannerText) {
      var last = tickets[tickets.length - 1];
      bannerText.textContent = unseen === 1
        ? "New ticket #" + last.number + ": " + last.summary
        : unseen + " new tickets came in. Latest: #" + last.number + " " + last.summary;
      banner.classList.add("show");
    }
    if (!alertsOn) return;
    chime();
    if ("Notification" in window && Notification.permission === "granted") {
      tickets.slice(-3).forEach(function (t) {
        try {
          var n = new Notification("New ticket #" + t.number + " on " + t.board, {
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
        if (!r.ok || r.redirected) throw new Error("not signed in");
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
