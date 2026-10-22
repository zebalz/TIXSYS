// Liquid glass: real refraction for elements marked data-liquid.
//
// Chrome and Edge can run an SVG filter on what's *behind* an element
// (backdrop-filter: url(#filter)). We build a displacement map for each glass
// shape: near the rounded edge, the backdrop is pulled inward, the way a thick
// glass rim bends light. Safari and Firefox can't do this yet, so they keep the
// plain frosted glass from the stylesheet. Nothing is drawn on top to imitate it.
(function () {
  "use strict";

  var brands = navigator.userAgentData && navigator.userAgentData.brands;
  var chromium = !!(brands && brands.some(function (b) { return /Chrom/.test(b.brand); }));
  var reduce = window.matchMedia && (window.matchMedia("(prefers-reduced-transparency: reduce)").matches ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  if (!chromium || reduce) return;

  var NS = "http://www.w3.org/2000/svg";
  var holder = document.createElementNS(NS, "svg");
  holder.setAttribute("class", "svg-defs");
  holder.setAttribute("aria-hidden", "true");
  holder.setAttribute("width", "0");
  holder.setAttribute("height", "0");
  document.body.appendChild(holder);

  var made = {};
  var counter = 0;

  // A map pixel's red/green say how far to shift sideways/vertically (128 = no shift).
  function displacementMap(w, h, radius, bezel) {
    var canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext("2d");
    var img = ctx.createImageData(w, h);
    var d = img.data;
    var hw = w / 2, hh = h / 2;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        var px = x + 0.5 - hw, py = y + 0.5 - hh;
        var qx = Math.abs(px) - (hw - radius), qy = Math.abs(py) - (hh - radius);
        var outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - radius;
        var inside = -outside;
        var dx = 0, dy = 0;
        if (inside > 0 && inside < bezel) {
          var nx, ny;
          if (qx > 0 && qy > 0) {
            var len = Math.hypot(qx, qy) || 1;
            nx = qx / len; ny = qy / len;
          } else if (qx > qy) { nx = 1; ny = 0; } else { nx = 0; ny = 1; }
          nx *= px < 0 ? -1 : 1;
          ny *= py < 0 ? -1 : 1;
          var t = 1 - inside / bezel;           // 1 at the very edge, 0 where the rim ends
          var m = t * t * (3 - 2 * t);          // smooth falloff
          dx = -nx * m;
          dy = -ny * m;
        }
        var i = (y * w + x) * 4;
        d[i] = Math.round(128 + dx * 127);
        d[i + 1] = Math.round(128 + dy * 127);
        d[i + 2] = 128;
        d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL("image/png");
  }

  function filterFor(w, h, radius, blur) {
    var bezel = Math.max(5, Math.min(14, Math.min(w, h) * 0.3));
    var strength = Math.round(bezel * 1.1);
    var key = [w, h, radius, bezel, blur].join("x");
    if (made[key]) return made[key];
    var id = "liquid-" + (++counter);
    var filter = document.createElementNS(NS, "filter");
    filter.setAttribute("id", id);
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    filter.setAttribute("width", String(w));
    filter.setAttribute("height", String(h));
    filter.setAttribute("filterUnits", "userSpaceOnUse");
    filter.setAttribute("color-interpolation-filters", "sRGB");
    var image = document.createElementNS(NS, "feImage");
    image.setAttribute("href", displacementMap(w, h, radius, bezel));
    image.setAttribute("x", "0");
    image.setAttribute("y", "0");
    image.setAttribute("width", String(w));
    image.setAttribute("height", String(h));
    image.setAttribute("preserveAspectRatio", "none");
    image.setAttribute("result", "map");
    // Frost first, then bend the frosted backdrop at the rim, then lift the colors.
    var frost = document.createElementNS(NS, "feGaussianBlur");
    frost.setAttribute("in", "SourceGraphic");
    frost.setAttribute("stdDeviation", String(blur));
    frost.setAttribute("result", "frost");
    var shift = document.createElementNS(NS, "feDisplacementMap");
    shift.setAttribute("in", "frost");
    shift.setAttribute("in2", "map");
    shift.setAttribute("scale", String(strength));
    shift.setAttribute("xChannelSelector", "R");
    shift.setAttribute("yChannelSelector", "G");
    shift.setAttribute("result", "bent");
    var color = document.createElementNS(NS, "feColorMatrix");
    color.setAttribute("in", "bent");
    color.setAttribute("type", "saturate");
    color.setAttribute("values", "1.8");
    filter.appendChild(frost);
    filter.appendChild(image);
    filter.appendChild(shift);
    filter.appendChild(color);
    holder.appendChild(filter);
    made[key] = id;
    return id;
  }

  function apply(el) {
    var rect = el.getBoundingClientRect();
    var w = Math.round(rect.width), h = Math.round(rect.height);
    if (w < 8 || h < 8 || w * h > 600000) return; // skip hidden or very large elements
    var radius = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
    radius = Math.min(radius, w / 2, h / 2);
    var blur = el.getAttribute("data-liquid") === "clear" ? 1.5 : 5;
    var id = filterFor(w, h, Math.round(radius), blur);
    el.style.backdropFilter = "url(#" + id + ")";
    el.classList.add("liquid-on");
  }

  var pending = new Set();
  var scheduled = false;
  function schedule(el) {
    pending.add(el);
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () {
      scheduled = false;
      pending.forEach(apply);
      pending.clear();
    });
  }

  var watcher = "ResizeObserver" in window ? new ResizeObserver(function (entries) {
    entries.forEach(function (e) { schedule(e.target); });
  }) : null;

  function scan(root) {
    (root || document).querySelectorAll("[data-liquid]").forEach(function (el) {
      if (el.__liquid) return;
      el.__liquid = true;
      schedule(el);
      if (watcher) watcher.observe(el);
    });
  }
  scan();
  window.TixsysGlass = { scan: scan };
})();
