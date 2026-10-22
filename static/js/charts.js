/* TIXSYS Reports: draws every chart from the numbers in <script id="report-data">.
   Plain JavaScript with SVG and CSS 3D: no libraries, nothing downloaded, so the page
   stays light and fast. Every number is also printed in each chart's "Show as a table"
   section, so a chart is never the only way to read a value.
   Text from the data goes in with textContent, never as HTML. */
(() => {
  "use strict";

  const source = document.getElementById("report-data");
  if (!source) return;
  const D = JSON.parse(source.textContent);

  const NS = "http://www.w3.org/2000/svg";
  const motion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  const ORDER = ["portal", "phone", "walkup", "text", "email", "other"];
  const LABELS = { portal: "Portal", phone: "Phone", walkup: "Walk-up", text: "Text", email: "Email", other: "Other" };
  const SERIES = {
    portal: token("--c1"), phone: token("--c2"), walkup: token("--c3"),
    text: token("--c4"), email: token("--c5"), other: token("--c-other"),
  };
  const C1 = token("--c1");
  const C2 = token("--c2");
  const INK = token("--ink") || "#26232f";
  const NODE = token("--ink-2") || "#57536a";
  const RAMP = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => token("--seq-" + i));
  const DAYS_LONG = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"];

  // ---------------------------------------------------------------- helpers
  function svgEl(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    if (attrs) for (const key of Object.keys(attrs)) if (attrs[key] != null) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function htmlEl(tag, cls, parent) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (parent) parent.appendChild(node);
    return node;
  }
  function label(parent, x, y, text, cls, anchor) {
    const node = svgEl("text", { x: round(x), y: round(y), class: cls || "tick", "text-anchor": anchor || "start" }, parent);
    node.textContent = text;
    return node;
  }
  const round = (n) => Math.round(n * 10) / 10;
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  const compact = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "K" : String(n));

  function hoursWords(h) {
    if (h == null) return "—";
    let m = Math.round(h * 60);
    if (m < 60) return Math.max(m, 1) + " min";
    const days = Math.floor(m / 1440);
    m -= days * 1440;
    const hrs = Math.floor(m / 60);
    m -= hrs * 60;
    if (days) return days + (days === 1 ? " day" : " days") + (hrs ? " " + hrs + " hr" : "");
    return hrs + " hr" + (m ? " " + m + " min" : "");
  }
  function hourRange(h) {
    const name = (x) => (x % 12 === 0 ? 12 : x % 12) + (x % 24 < 12 ? " AM" : " PM");
    return name(h) + "–" + name(h + 1);
  }
  function hourShort(h) {
    return (h % 12 === 0 ? 12 : h % 12) + (h < 12 ? "a" : "p");
  }

  // Clean axis steps: 0, 5, 10, 15... never 0, 3.7, 7.4.
  function niceScale(peak, maxTicks) {
    const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000];
    let step = steps[steps.length - 1];
    for (const s of steps) {
      if (peak / s <= maxTicks) {
        step = s;
        break;
      }
    }
    const top = Math.max(step, Math.ceil(peak / step) * step);
    const ticks = [];
    for (let v = 0; v <= top; v += step) ticks.push(v);
    return { top, ticks };
  }

  function rgbOf(hex) {
    const h = hex.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  }
  function shade(hex, amount) {
    // amount < 0 darkens, > 0 lightens.
    const out = rgbOf(hex).map((c) => Math.round(amount < 0 ? c * (1 + amount) : c + (255 - c) * amount));
    return "rgb(" + out.join(",") + ")";
  }
  function luminance(hex) {
    const lin = rgbOf(hex).map((c) => {
      const v = c / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  }
  // Text placed on a colored fill: white or ink, whichever reads better.
  function inkOn(hex) {
    const l = luminance(hex);
    const white = 1.05 / (l + 0.05);
    const dark = (l + 0.05) / (luminance(INK) + 0.05);
    return white >= dark ? "#ffffff" : INK;
  }
  // "How many" color: one hue, light to dark. Non-zero values use steps 3-8 so they stay visible.
  function rampColor(n, max) {
    if (!n) return RAMP[0];
    return RAMP[clamp(2 + Math.round((n / max) * 5), 2, 7)];
  }

  function segments(list, has) {
    const out = [];
    let run = [];
    list.forEach((item, i) => {
      if (has(item)) run.push(i);
      else if (run.length) {
        out.push(run);
        run = [];
      }
    });
    if (run.length) out.push(run);
    return out;
  }
  const pathOf = (points) => points.map((p, i) => (i ? "L" : "M") + round(p[0]) + "," + round(p[1])).join(" ");

  function dot(parent, x, y, color, hidden, r) {
    return svgEl("circle", { cx: round(x), cy: round(y), r: r || 4.5, fill: color, class: "end-dot", visibility: hidden ? "hidden" : null }, parent);
  }
  function moveDot(node, x, y) {
    node.setAttribute("cx", round(x));
    node.setAttribute("cy", round(y));
    node.setAttribute("visibility", "visible");
  }
  function drawIn(path, animate, delay) {
    if (!animate) return;
    path.style.setProperty("--len", Math.ceil(path.getTotalLength()) + 1);
    path.style.animationDelay = (delay || 0) + "ms";
    path.classList.add("draw");
  }
  // Week labels along the bottom; the newest week always gets one.
  function xLabels(svg, labels, X, y, span) {
    const fit = Math.max(1, Math.floor(span / 56));
    const every = Math.max(1, Math.ceil(labels.length / fit));
    for (let i = labels.length - 1; i >= 0; i -= every) label(svg, X(i), y, labels[i], "tick", "middle");
  }

  // ---------------------------------------------------------------- tooltip
  const tip = htmlEl("div", "tip", document.body);
  tip.setAttribute("aria-hidden", "true");
  function showTip(x, y, title, rows) {
    tip.replaceChildren();
    htmlEl("b", "", tip).textContent = title;
    for (const r of rows || []) {
      const row = htmlEl("div", "row", tip);
      if (r.color) htmlEl("i", "", row).style.background = r.color;
      htmlEl("strong", "", row).textContent = r.value;
      if (r.label) htmlEl("span", "", row).textContent = r.label;
    }
    tip.classList.add("show");
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    let left = x + 16;
    let top = y + 16;
    if (left + w > window.innerWidth - 8) left = x - w - 16;
    if (top + h > window.innerHeight - 8) top = y - h - 16;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  const hideTip = () => tip.classList.remove("show");
  window.addEventListener("scroll", hideTip, { passive: true });

  // Draw at the container's real width (crisp text at any size); redraw when it changes.
  function responsive(box, draw) {
    if (!box) return;
    let width = 0;
    let first = true;
    let timer = 0;
    const run = () => {
      const w = Math.floor(box.clientWidth);
      if (!w || w === width) return;
      width = w;
      box.replaceChildren();
      draw(box, w, first && motion);
      first = false;
    };
    run();
    if ("ResizeObserver" in window) {
      new ResizeObserver(() => {
        clearTimeout(timer);
        timer = setTimeout(run, 150);
      }).observe(box);
    }
  }
  function makeSvg(box, w, h) {
    const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, focusable: "false" }, box);
    svg.setAttribute("aria-hidden", "true"); // the chart box has the description; the table has the numbers
    return svg;
  }

  // A vertical line that snaps to the nearest week, with every series in one tooltip.
  // Works with a mouse, a finger, and the arrow keys (the chart box is focusable).
  function crosshair(box, svg, frame, xs, onMove, onLeave) {
    const line = svgEl("line", { class: "crosshair", y1: frame.top, y2: frame.bottom, visibility: "hidden" }, svg);
    const hit = svgEl("rect", {
      class: "hit", x: frame.left - 14, y: frame.top - 8,
      width: frame.right - frame.left + 28, height: frame.bottom - frame.top + 16,
    }, svg);
    let current = -1;
    const place = (i, cx, cy) => {
      current = i;
      line.setAttribute("x1", round(xs[i]));
      line.setAttribute("x2", round(xs[i]));
      line.setAttribute("visibility", "visible");
      onMove(i, cx, cy);
    };
    const nearest = (clientX) => {
      const x = clientX - svg.getBoundingClientRect().left;
      let best = 0;
      xs.forEach((v, i) => {
        if (Math.abs(v - x) < Math.abs(xs[best] - x)) best = i;
      });
      return best;
    };
    const clear = () => {
      current = -1;
      line.setAttribute("visibility", "hidden");
      hideTip();
      if (onLeave) onLeave();
    };
    hit.addEventListener("pointermove", (e) => place(nearest(e.clientX), e.clientX, e.clientY));
    hit.addEventListener("pointerdown", (e) => place(nearest(e.clientX), e.clientX, e.clientY));
    hit.addEventListener("pointerleave", clear);
    box.tabIndex = 0;
    box.onkeydown = (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const step = e.key === "ArrowRight" ? 1 : -1;
      const next = current < 0 ? xs.length - 1 : clamp(current + step, 0, xs.length - 1);
      const rect = svg.getBoundingClientRect();
      place(next, rect.left + xs[next], rect.top + frame.top + 30);
    };
    box.onblur = clear;
  }

  // ------------------------------------------------------ opened vs resolved
  function gapChart(box, w, animate) {
    const weeks = D.weeks;
    const n = weeks.length;
    const h = 250;
    const f = { left: 34, right: w - 40, top: 14, bottom: h - 28 };
    const svg = makeSvg(box, w, h);
    const peak = Math.max(1, ...weeks.map((x) => Math.max(x.opened, x.resolved)));
    const s = niceScale(peak, 4);
    const X = (i) => (n === 1 ? (f.left + f.right) / 2 : f.left + (i * (f.right - f.left)) / (n - 1));
    const Y = (v) => f.bottom - (v / s.top) * (f.bottom - f.top);

    for (const t of s.ticks) {
      svgEl("line", { class: t === 0 ? "baseline" : "gridline", x1: f.left, x2: f.right, y1: round(Y(t)), y2: round(Y(t)) }, svg);
      label(svg, f.left - 8, Y(t) + 4, compact(t), "tick", "end");
    }
    xLabels(svg, weeks.map((x) => x.label), X, h - 8, f.right - f.left);

    // Shade between the lines in the color of whichever was higher.
    const fills = svgEl("g", { class: animate ? "fade-in" : null }, svg);
    const pt = (i, key) => [X(i), Y(weeks[i][key])];
    const poly = (points, color) =>
      svgEl("polygon", { points: points.map((p) => round(p[0]) + "," + round(p[1])).join(" "), fill: color, class: "gap-fill" }, fills);
    for (let i = 0; i < n - 1; i++) {
      const a = weeks[i].opened - weeks[i].resolved;
      const b = weeks[i + 1].opened - weeks[i + 1].resolved;
      if (a * b >= 0) {
        if (a === 0 && b === 0) continue;
        poly([pt(i, "opened"), pt(i + 1, "opened"), pt(i + 1, "resolved"), pt(i, "resolved")], a + b > 0 ? C1 : C2);
      } else {
        const t = a / (a - b);
        const cross = [X(i) + t * (X(i + 1) - X(i)), Y(weeks[i].opened + t * (weeks[i + 1].opened - weeks[i].opened))];
        poly([pt(i, "opened"), cross, pt(i, "resolved")], a > 0 ? C1 : C2);
        poly([cross, pt(i + 1, "opened"), pt(i + 1, "resolved")], b > 0 ? C1 : C2);
      }
    }
    const resolvedLine = svgEl("path", { d: pathOf(weeks.map((x, i) => pt(i, "resolved"))), class: "series-line", stroke: C2 }, svg);
    const openedLine = svgEl("path", { d: pathOf(weeks.map((x, i) => pt(i, "opened"))), class: "series-line", stroke: C1 }, svg);
    drawIn(openedLine, animate, 0);
    drawIn(resolvedLine, animate, 150);

    // Values at the end of each line, only when they don't crowd each other.
    const last = weeks[n - 1];
    dot(svg, X(n - 1), Y(last.resolved), C2);
    dot(svg, X(n - 1), Y(last.opened), C1);
    if (Math.abs(Y(last.opened) - Y(last.resolved)) >= 14) {
      label(svg, X(n - 1) + 9, Y(last.opened) + 4, String(last.opened), "end-label");
      label(svg, X(n - 1) + 9, Y(last.resolved) + 4, String(last.resolved), "end-label");
    } else if (last.opened === last.resolved) {
      label(svg, X(n - 1) + 9, Y(last.opened) + 4, String(last.opened), "end-label");
    }

    const marks = [dot(svg, 0, 0, C2, true), dot(svg, 0, 0, C1, true)];
    crosshair(box, svg, f, weeks.map((x, i) => X(i)), (i, cx, cy) => {
      const wk = weeks[i];
      moveDot(marks[0], X(i), Y(wk.resolved));
      moveDot(marks[1], X(i), Y(wk.opened));
      const net = wk.opened - wk.resolved;
      showTip(cx, cy, "Week of " + wk.label, [
        { color: C1, value: String(wk.opened), label: "opened" },
        { color: C2, value: String(wk.resolved), label: "resolved" },
        {
          value: net > 0 ? "+" + net : net < 0 ? "−" + -net : "±0",
          label: net > 0 ? "more open tickets" : net < 0 ? "fewer open tickets" : "open tickets held steady",
        },
      ]);
    }, () => marks.forEach((m) => m.setAttribute("visibility", "hidden")));
  }

  // ---------------------------------------------------------- portal share
  function shareChart(box, w, animate) {
    const weeks = D.weeks;
    const n = weeks.length;
    const h = 130;
    const f = { left: 36, right: w - 40, top: 16, bottom: h - 24 };
    const svg = makeSvg(box, w, h);
    const X = (i) => (n === 1 ? (f.left + f.right) / 2 : f.left + (i * (f.right - f.left)) / (n - 1));
    const Y = (v) => f.bottom - (v / 100) * (f.bottom - f.top);
    for (const t of [0, 50, 100]) {
      svgEl("line", { class: t ? "gridline" : "baseline", x1: f.left, x2: f.right, y1: round(Y(t)), y2: round(Y(t)) }, svg);
      label(svg, f.left - 8, Y(t) + 4, t + "%", "tick", "end");
    }
    xLabels(svg, weeks.map((x) => x.label), X, h - 6, f.right - f.left);

    const runs = segments(weeks, (x) => x.share != null);
    for (const run of runs) {
      const top = run.map((i) => [X(i), Y(weeks[i].share)]);
      if (run.length > 1) {
        const area = pathOf(top) + ` L${round(X(run[run.length - 1]))},${f.bottom} L${round(X(run[0]))},${f.bottom} Z`;
        svgEl("path", { d: area, class: "share-area" + (animate ? " fade-in" : "") }, svg);
        drawIn(svgEl("path", { d: pathOf(top), class: "series-line", stroke: C1 }, svg), animate, 0);
      }
    }
    const withData = weeks.map((x, i) => i).filter((i) => weeks[i].share != null);
    if (withData.length) {
      const a = withData[0];
      const b = withData[withData.length - 1];
      dot(svg, X(b), Y(weeks[b].share), C1);
      label(svg, X(b) + 9, Y(weeks[b].share) + 4, weeks[b].share + "%", "end-label");
      if (a !== b) {
        dot(svg, X(a), Y(weeks[a].share), C1);
        // Put the first value on the side the line isn't heading toward.
        const next = withData[1];
        const rising = weeks[next].share >= weeks[a].share;
        const below = rising && Y(weeks[a].share) + 17 <= f.bottom;
        label(svg, X(a) + 7, Y(weeks[a].share) + (below ? 16 : -9), weeks[a].share + "%", "end-label", "start");
      }
    }
    const mark = dot(svg, 0, 0, C1, true);
    crosshair(box, svg, f, weeks.map((x, i) => X(i)), (i, cx, cy) => {
      const wk = weeks[i];
      if (wk.share == null) {
        mark.setAttribute("visibility", "hidden");
        showTip(cx, cy, "Week of " + wk.label, [{ value: "No tickets" }]);
        return;
      }
      moveDot(mark, X(i), Y(wk.share));
      showTip(cx, cy, "Week of " + wk.label, [
        { color: C1, value: wk.share + "%", label: "through the portal" },
        { value: wk.portal + " of " + wk.opened, label: "tickets" },
      ]);
    }, () => mark.setAttribute("visibility", "hidden"));
  }

  // ------------------------------------------------------- all channels bar
  function channelBar(box, w, animate) {
    const items = D.channels.filter((c) => c.n > 0);
    const total = items.reduce((sum, c) => sum + c.n, 0);
    const h = 28;
    const svg = makeSvg(box, w, h);
    if (!total) {
      label(svg, 0, 18, "No tickets in this period.", "tick");
      return;
    }
    const gap = 2;
    const barH = 22;
    const usable = w - gap * (items.length - 1);
    const group = svgEl("g", { class: animate ? "grow-x" : null }, svg);
    let x = 0;
    items.forEach((c, k) => {
      const segW = Math.max(2, (c.n / total) * usable);
      const color = SERIES[c.key];
      const last = k === items.length - 1;
      const r = last ? Math.min(4, segW / 2) : 0;
      // Square where it starts, 4px rounded at the far end.
      const d = `M${round(x)},2 H${round(x + segW - r)} Q${round(x + segW)},2 ${round(x + segW)},${2 + r} V${2 + barH - r} Q${round(x + segW)},${2 + barH} ${round(x + segW - r)},${2 + barH} H${round(x)} Z`;
      const seg = svgEl("path", { d, fill: color, class: "seg" }, group);
      const text = c.pct + "%";
      if (segW >= text.length * 7 + 14) {
        const t = label(group, x + segW / 2, 2 + barH / 2 + 4, text, "seg-label", "middle");
        t.setAttribute("fill", inkOn(color));
      }
      const show = (e) => {
        svg.querySelectorAll(".seg").forEach((node) => node.classList.toggle("dim", node !== seg));
        showTip(e.clientX, e.clientY, c.label, [
          { color, value: plural(c.n, "ticket") },
          { value: c.pct + "%", label: "of all tickets" },
        ]);
      };
      seg.addEventListener("pointermove", show);
      seg.addEventListener("pointerdown", show);
      seg.addEventListener("pointerleave", () => {
        svg.querySelectorAll(".seg").forEach((node) => node.classList.remove("dim"));
        hideTip();
      });
      x += segW + gap;
    });
  }

  // ------------------------------------------------------------ punch card
  function punchChart(box, w, animate) {
    const P = D.punch;
    const left = 40;
    const right = 6;
    const top = 6;
    const bottom = 24;
    const cw = (w - left - right) / 24;
    const ch = clamp(cw * 1.1, 20, 32);
    const h = top + ch * 7 + bottom;
    const svg = makeSvg(box, w, h);
    svg.classList.add("punch");
    const max = Math.max(1, ...P.flat());
    const rMax = Math.max(3, Math.min(cw, ch) / 2 - 1.5);

    // Office hours: 8 AM to 5 PM, Monday to Friday.
    svgEl("rect", { class: "office-band", x: round(left + cw * 8), y: top, width: round(cw * 9), height: round(ch * 5), rx: 8 }, svg);
    D.dayNames.forEach((name, d) => label(svg, left - 10, top + ch * d + ch / 2 + 4, name, "tick", "end"));
    for (let hr = 0; hr < 24; hr += 3) label(svg, left + cw * hr + cw / 2, h - 6, hourShort(hr), "tick", "middle");

    for (let d = 0; d < 7; d++) {
      for (let hr = 0; hr < 24; hr++) {
        const n = P[d][hr];
        const cx = left + cw * hr + cw / 2;
        const cy = top + ch * d + ch / 2;
        let mark = null;
        if (n) {
          // Dot area grows with the count.
          mark = svgEl("circle", { cx: round(cx), cy: round(cy), r: round(Math.max(2.5, rMax * Math.sqrt(n / max))), fill: rampColor(n, max), class: "dot" + (animate ? " pop" : "") }, svg);
          if (animate) mark.style.animationDelay = hr * 22 + d * 12 + "ms";
        } else {
          svgEl("circle", { cx: round(cx), cy: round(cy), r: 1.6, class: "dot-zero" }, svg);
        }
        const hit = svgEl("rect", { class: "hit", x: round(left + cw * hr), y: round(top + ch * d), width: round(cw), height: round(ch) }, svg);
        const show = (e) => {
          if (mark) mark.classList.add("hot");
          showTip(e.clientX, e.clientY, DAYS_LONG[d] + ", " + hourRange(hr), [{ value: n ? plural(n, "ticket") : "No tickets" }]);
        };
        hit.addEventListener("pointermove", show);
        hit.addEventListener("pointerdown", show);
        hit.addEventListener("pointerleave", () => {
          if (mark) mark.classList.remove("hot");
          hideTip();
        });
      }
    }
  }

  // ----------------------------------------------------------- time to fix
  function bandChart(box, w, animate) {
    const weeks = D.weeks;
    const n = weeks.length;
    const h = 230;
    const f = { left: 40, right: w - 64, top: 12, bottom: h - 28 };
    const svg = makeSvg(box, w, h);
    const values = weeks.flatMap((x) => [x.p25, x.p75]).filter((v) => v != null);
    if (!values.length) {
      label(svg, f.left, 40, "No tickets were fixed in this period.", "tick");
      return;
    }
    // Time doubles at each line (log scale), so 10-minute fixes and 3-day fixes both fit.
    const STEPS = [[1 / 12, "5m"], [0.25, "15m"], [0.5, "30m"], [1, "1h"], [2, "2h"], [4, "4h"], [8, "8h"], [24, "1d"], [48, "2d"], [96, "4d"], [168, "1w"], [336, "2w"], [720, "30d"]];
    const lo = Math.max(1 / 12, Math.min(...values));
    const hi = Math.max(...values);
    let a = 0;
    while (a < STEPS.length - 1 && STEPS[a + 1][0] <= lo) a++;
    let b = STEPS.length - 1;
    while (b > 0 && STEPS[b - 1][0] >= hi) b--;
    if (b <= a) b = Math.min(STEPS.length - 1, a + 1);
    const yMin = Math.log(STEPS[a][0]);
    const yMax = Math.log(STEPS[b][0]);
    const Y = (v) => f.bottom - ((Math.log(clamp(v, STEPS[a][0], STEPS[b][0])) - yMin) / (yMax - yMin)) * (f.bottom - f.top);
    const X = (i) => (n === 1 ? (f.left + f.right) / 2 : f.left + (i * (f.right - f.left)) / (n - 1));
    const labelEvery = b - a > 7 ? 2 : 1;
    for (let k = a; k <= b; k++) {
      const y = round(Y(STEPS[k][0]));
      svgEl("line", { class: k === a ? "baseline" : "gridline", x1: f.left, x2: f.right, y1: y, y2: y }, svg);
      if ((k - a) % labelEvery === 0 || k === b) label(svg, f.left - 8, y + 4, STEPS[k][1], "tick", "end");
    }
    xLabels(svg, weeks.map((x) => x.label), X, h - 8, f.right - f.left);

    for (const run of segments(weeks, (x) => x.p50 != null)) {
      if (run.length > 1) {
        const upper = run.map((i) => [X(i), Y(weeks[i].p75)]);
        const lower = run.map((i) => [X(i), Y(weeks[i].p25)]).reverse();
        svgEl("path", { d: pathOf(upper.concat(lower)) + " Z", class: "band" + (animate ? " fade-in" : "") }, svg);
        drawIn(svgEl("path", { d: pathOf(run.map((i) => [X(i), Y(weeks[i].p50)])), class: "series-line", stroke: C1 }, svg), animate, 100);
      } else {
        const i = run[0];
        svgEl("line", { class: "band-stick", x1: round(X(i)), x2: round(X(i)), y1: round(Y(weeks[i].p75)), y2: round(Y(weeks[i].p25)) }, svg);
        dot(svg, X(i), Y(weeks[i].p50), C1);
      }
    }
    const lastIndex = weeks.map((x, i) => i).filter((i) => weeks[i].p50 != null).pop();
    if (lastIndex != null) {
      dot(svg, X(lastIndex), Y(weeks[lastIndex].p50), C1);
      label(svg, X(lastIndex) + 9, Y(weeks[lastIndex].p50) + 4, hoursWords(weeks[lastIndex].p50), "end-label");
    }
    const mark = dot(svg, 0, 0, C1, true);
    crosshair(box, svg, f, weeks.map((x, i) => X(i)), (i, cx, cy) => {
      const wk = weeks[i];
      if (wk.p50 == null) {
        mark.setAttribute("visibility", "hidden");
        showTip(cx, cy, "Week of " + wk.label, [{ value: "Nothing fixed" }]);
        return;
      }
      moveDot(mark, X(i), Y(wk.p50));
      showTip(cx, cy, "Week of " + wk.label, [
        { color: C1, value: hoursWords(wk.p50), label: "median" },
        { value: hoursWords(wk.p25) + " – " + hoursWords(wk.p75), label: "middle half" },
        { value: String(wk.resolved), label: wk.resolved === 1 ? "ticket fixed" : "tickets fixed" },
      ]);
    }, () => mark.setAttribute("visibility", "hidden"));
  }

  // ------------------------------------------------------------------ flow
  function flowChart(box, w, animate) {
    const strands = D.strands;
    const total = strands.reduce((sum, s) => sum + s.n, 0);
    const h = 320;
    const svg = makeSvg(box, w, h);
    svg.classList.add("flow");
    if (!total) {
      label(svg, 0, 20, "No tickets in this period.", "tick");
      return;
    }
    const OUT = { fixed: "Fixed", open: "Still open" };
    const sources = ORDER.filter((key) => strands.some((s) => s.s === key));
    const boardNames = D.boards.concat(strands.map((s) => s.b).filter((b) => !D.boards.includes(b)));
    const boards = [...new Set(boardNames)].filter((b) => strands.some((s) => s.b === b));
    const outcomes = ["fixed", "open"].filter((o) => strands.some((s) => s.o === o));
    const sum = (field, key) => strands.filter((s) => s[field] === key).reduce((acc, s) => acc + s.n, 0);
    const count = (s, b, o) => strands.filter((x) => (!s || x.s === s) && (!b || x.b === b) && (!o || x.o === o)).reduce((acc, x) => acc + x.n, 0);

    const narrow = w < 600;
    const nodeW = 12;
    const pad = 16;
    const colX = [narrow ? 74 : 120, Math.round(w * 0.5 - nodeW / 2), w - (narrow ? 92 : 132) - nodeW];
    const top = 18;
    const avail = h - 26;
    const most = Math.max(sources.length, boards.length, outcomes.length);
    const k = (avail - pad * (most - 1)) / total; // pixels per ticket, the same everywhere

    const layout = (keys, field) => {
      const sizes = keys.map((key) => sum(field, key) * k);
      const used = sizes.reduce((acc, v) => acc + v, 0) + pad * (keys.length - 1);
      let y = top + (avail - used) / 2;
      const out = {};
      keys.forEach((key, i) => {
        out[key] = { y, h: sizes[i] };
        y += sizes[i] + pad;
      });
      return out;
    };
    const S = layout(sources, "s");
    const B = layout(boards, "b");
    const O = layout(outcomes, "o");

    // Stage 1: channel -> board. Ordered by board at the channel, by channel at the board.
    const first = [];
    for (const s of sources) for (const b of boards) {
      const n = count(s, b, null);
      if (n) first.push({ s, b, n });
    }
    const atSource = Object.fromEntries(sources.map((s) => [s, S[s].y]));
    first.forEach((p) => {
      p.y0 = atSource[p.s];
      atSource[p.s] += p.n * k;
    });
    const atBoardIn = Object.fromEntries(boards.map((b) => [b, B[b].y]));
    first.slice().sort((p, q) => ORDER.indexOf(p.s) - ORDER.indexOf(q.s)).forEach((p) => {
      p.y1 = atBoardIn[p.b];
      atBoardIn[p.b] += p.n * k;
    });
    // Stage 2: board -> fixed / still open, keeping each channel's color.
    const second = [];
    for (const b of boards) for (const o of outcomes) for (const s of sources) {
      const n = count(s, b, o);
      if (n) second.push({ s, b, o, n });
    }
    const atBoardOut = Object.fromEntries(boards.map((b) => [b, B[b].y]));
    second.forEach((p) => {
      p.y0 = atBoardOut[p.b];
      atBoardOut[p.b] += p.n * k;
    });
    const atOutcome = Object.fromEntries(outcomes.map((o) => [o, O[o].y]));
    second
      .slice()
      .sort((p, q) => boards.indexOf(p.b) - boards.indexOf(q.b) || ORDER.indexOf(p.s) - ORDER.indexOf(q.s))
      .forEach((p) => {
        p.y1 = atOutcome[p.o];
        atOutcome[p.o] += p.n * k;
      });

    const ribbon = (x0, x1, y0, y1, size) => {
      const xm = (x0 + x1) / 2;
      return `M${round(x0)},${round(y0)} C${round(xm)},${round(y0)} ${round(xm)},${round(y1)} ${round(x1)},${round(y1)} ` +
        `L${round(x1)},${round(y1 + size)} C${round(xm)},${round(y1 + size)} ${round(xm)},${round(y0 + size)} ${round(x0)},${round(y0 + size)} Z`;
    };
    const links = svgEl("g", { class: animate ? "fade-in" : null }, svg);
    const all = [];
    const focus = (key, on) => {
      svg.classList.toggle("focus", on);
      all.forEach((node) => node.classList.toggle("hot", on && node.dataset.s === key));
    };
    const addLink = (d, p, title, rows) => {
      const node = svgEl("path", { d, fill: SERIES[p.s], class: "link" }, links);
      node.dataset.s = p.s;
      all.push(node);
      const show = (e) => {
        focus(p.s, true);
        showTip(e.clientX, e.clientY, title, rows);
      };
      node.addEventListener("pointermove", show);
      node.addEventListener("pointerdown", show);
      node.addEventListener("pointerleave", () => {
        focus(p.s, false);
        hideTip();
      });
    };
    first.forEach((p) =>
      addLink(ribbon(colX[0] + nodeW, colX[1], p.y0, p.y1, p.n * k), p, LABELS[p.s] + " → " + p.b, [
        { color: SERIES[p.s], value: plural(p.n, "ticket") },
      ])
    );
    second.forEach((p) =>
      addLink(ribbon(colX[1] + nodeW, colX[2], p.y0, p.y1, p.n * k), p, p.b + " → " + OUT[p.o], [
        { color: SERIES[p.s], value: plural(p.n, "ticket"), label: "came in by " + LABELS[p.s].toLowerCase() },
      ])
    );

    const nodeLabel = (x, y, name, n, anchor) => {
      const t = svgEl("text", { x: round(x), y: round(y + 4), class: "flow-label", "text-anchor": anchor }, svg);
      svgEl("tspan", {}, t).textContent = name + " ";
      svgEl("tspan", { class: "count" }, t).textContent = String(n);
    };
    const node = (x, box2, color) =>
      svgEl("rect", { x: round(x), y: round(box2.y), width: nodeW, height: round(Math.max(1.5, box2.h)), rx: 3, fill: color }, svg);
    sources.forEach((s) => {
      node(colX[0], S[s], SERIES[s]);
      nodeLabel(colX[0] - 8, S[s].y + S[s].h / 2, LABELS[s], sum("s", s), "end");
    });
    // On narrow screens the board names go above their bars so they don't run into the right column.
    const labelsAbove = colX[2] - colX[1] < 230;
    boards.forEach((b) => {
      node(colX[1], B[b], NODE);
      if (labelsAbove) nodeLabel(colX[1] + nodeW / 2, B[b].y - 9, b, sum("b", b), "middle");
      else nodeLabel(colX[1] + nodeW + 8, B[b].y + B[b].h / 2, b, sum("b", b), "start");
    });
    outcomes.forEach((o) => {
      node(colX[2], O[o], NODE);
      nodeLabel(colX[2] + nodeW + 8, O[o].y + O[o].h / 2, OUT[o], sum("o", o), "start");
    });
  }

  // ---------------------------------------------------------------- 3D days
  function blocks(box) {
    if (!box) return;
    const days = D.days;
    const weeks = days.length / 7;
    const max = Math.max(1, ...days.map((d) => d.n));
    const START = { tilt: 58, spin: -32 };
    const state = { tilt: START.tilt, spin: START.spin, flat: false };
    const controls = document.getElementById("days-controls");
    const flatBtn = controls && controls.querySelector('[data-act="flat"]');
    let world = null;
    let bars = [];
    let callout = null;
    let width = 0;

    const calloutTransform = () => {
      if (!callout) return "";
      // Turn the label back toward the viewer, so it always faces you.
      return `translate3d(${callout.x}px, ${callout.y}px, ${callout.lift}px) rotateZ(${-state.spin}deg) rotateX(${-state.tilt}deg) translate(-50%, -100%)`;
    };
    function apply() {
      if (!world) return;
      world.style.transform = `rotateX(${state.tilt}deg) rotateZ(${state.spin}deg)`;
      if (callout) callout.node.style.transform = calloutTransform();
      bars.forEach((b) => (b.node.style.transform = `scaleZ(${state.flat ? 0.004 : 1})`));
      if (flatBtn) {
        flatBtn.textContent = state.flat ? "3D view" : "Flat view";
        flatBtn.setAttribute("aria-pressed", String(state.flat));
      }
    }

    function build(animate, scale) {
      scale = scale || 1;
      box.replaceChildren();
      bars = [];
      callout = null;
      const W = box.clientWidth;
      const H = box.clientHeight;
      const cell = clamp(Math.floor(((Math.min(W, 1000) * 0.62) / weeks) * scale), 10, 46);
      const gap = Math.max(2, Math.round(cell * 0.16));
      const size = cell - gap;
      const floorW = weeks * cell;
      const floorH = 7 * cell;
      const maxH = clamp(H * 0.42 * scale, 60, 200);

      world = htmlEl("div", "b3d-world", box);
      world.style.width = floorW + "px";
      world.style.height = floorH + "px";
      world.style.marginLeft = -floorW / 2 + "px";
      world.style.marginTop = -floorH / 2 + "px";
      const floor = htmlEl("div", "b3d-floor", world);
      const margin = Math.max(10, cell * 0.5);
      floor.style.left = -(margin + 34) + "px";
      floor.style.top = -margin + "px";
      floor.style.width = floorW + margin * 2 + 34 + "px";
      floor.style.height = floorH + margin * 2 + 20 + "px";

      // Day names down the side and week dates along the front, printed on the floor.
      D.dayNames.forEach((name, d) => {
        const l = htmlEl("div", "b3d-label day", world);
        l.textContent = name;
        l.style.width = "28px";
        l.style.left = "-36px";
        l.style.top = d * cell + cell / 2 - 6 + "px";
      });
      const every = Math.max(1, Math.ceil(weeks / Math.max(1, Math.floor(floorW / 64))));
      for (let wk = weeks - 1; wk >= 0; wk -= every) {
        const l = htmlEl("div", "b3d-label", world);
        const day = new Date(days[wk * 7].d + "T12:00:00");
        l.textContent = day.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        l.style.left = wk * cell + cell / 2 + "px";
        l.style.top = floorH + 6 + "px";
        l.style.transform = "translateX(-50%)";
      }

      let tallest = null;
      days.forEach((day, i) => {
        const wk = Math.floor(i / 7);
        const dow = i % 7;
        const x = wk * cell + gap / 2;
        const y = dow * cell + gap / 2;
        if (!day.n) {
          const tile = htmlEl("div", "b3d-tile" + (day.future ? " future" : ""), world);
          tile.style.left = x + "px";
          tile.style.top = y + "px";
          tile.style.width = size + "px";
          tile.style.height = size + "px";
          if (!day.future) tile.dataset.i = i;
          return;
        }
        const hgt = 5 + (day.n / max) * maxH;
        const color = rampColor(day.n, max);
        const node = htmlEl("div", "b3d-bar", world);
        node.dataset.i = i;
        node.style.left = x + "px";
        node.style.top = y + "px";
        node.style.width = size + "px";
        node.style.height = size + "px";
        const face = (transform, wpx, hpx, fill) => {
          const f = htmlEl("div", "b3d-face", node);
          f.style.width = wpx + "px";
          f.style.height = hpx + "px";
          f.style.transform = transform;
          f.style.background = fill;
          return f;
        };
        face("rotateX(90deg)", size, hgt, shade(color, -0.1)); // back
        face(`translateY(${size}px) rotateX(90deg)`, size, hgt, shade(color, -0.1)); // front
        face("rotateY(-90deg)", hgt, size, shade(color, -0.22)); // left
        face(`translateX(${size}px) rotateY(-90deg)`, hgt, size, shade(color, -0.22)); // right
        face(`translateZ(${hgt}px)`, size, size, color); // top
        node.style.transform = "scaleZ(0.004)";
        if (animate) node.style.transitionDelay = 250 + wk * 35 + dow * 12 + "ms";
        bars.push({ node, i });
        if (!tallest || day.n > days[tallest.i].n) tallest = { node, i, size, hgt };
      });

      // Label the busiest day right on its block.
      if (tallest) {
        const node = htmlEl("div", "b3d-callout", tallest.node);
        const day = days[tallest.i];
        node.textContent = day.label + " · " + plural(day.n, "ticket");
        callout = { node, x: tallest.size / 2, y: tallest.size / 2, lift: tallest.hgt + 8 };
      }
      const room = fit(floor, floorW, floorH);
      if (room < 0.97 && scale === 1) {
        build(animate, room * 0.96); // too big for the box: build once more, smaller
        return;
      }

      if (animate) {
        // Start flat and empty, then tip into 3D while the blocks rise.
        const target = { tilt: state.tilt, spin: state.spin, flat: state.flat };
        Object.assign(state, { tilt: 0, spin: 0, flat: true });
        box.classList.add("instant");
        apply();
        void box.offsetWidth;
        box.classList.remove("instant");
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            Object.assign(state, target);
            apply();
            setTimeout(() => bars.forEach((b) => (b.node.style.transitionDelay = "")), 2500);
          })
        );
      } else {
        box.classList.add("instant");
        apply();
        void box.offsetWidth;
        box.classList.remove("instant");
      }
    }

    // Center the whole scene (floor, blocks and label) in its box at the starting angle.
    function fit(floor, floorW, floorH) {
      const saved = { tilt: state.tilt, spin: state.spin, flat: state.flat };
      Object.assign(state, START, { flat: false });
      box.classList.add("instant");
      apply();
      const area = box.getBoundingClientRect();
      const rects = [floor.getBoundingClientRect()];
      if (callout) rects.push(callout.node.getBoundingClientRect());
      bars.forEach((b) => rects.push(b.node.lastElementChild.getBoundingClientRect()));
      const left = Math.min(...rects.map((r) => r.left));
      const right = Math.max(...rects.map((r) => r.right));
      const top = Math.min(...rects.map((r) => r.top));
      const bottom = Math.max(...rects.map((r) => r.bottom));
      const dx = area.left + area.width / 2 - (left + right) / 2;
      const dy = area.top + area.height / 2 - (top + bottom) / 2;
      world.style.marginLeft = -floorW / 2 + dx + "px";
      world.style.marginTop = -floorH / 2 + dy + "px";
      Object.assign(state, saved);
      apply();
      void box.offsetWidth;
      box.classList.remove("instant");
      // How much of the box the scene may use (1 = it fits).
      return Math.min(1, (area.width - 32) / (right - left), (area.height - 28) / (bottom - top));
    }

    // Hover: which day is under the pointer.
    let hot = null;
    const clearHot = () => {
      if (hot) hot.classList.remove("hot");
      hot = null;
    };
    box.addEventListener("pointerover", (e) => {
      if (drag) return;
      const target = e.target.closest(".b3d-bar, .b3d-tile");
      if (!target || target.dataset.i == null) return;
      clearHot();
      hot = target;
      hot.classList.add("hot");
    });
    box.addEventListener("pointerout", (e) => {
      if (!e.relatedTarget || !box.contains(e.relatedTarget) || !e.relatedTarget.closest(".b3d-bar, .b3d-tile")) {
        clearHot();
        hideTip();
      }
    });

    // Drag to turn (left-right spins, up-down tilts).
    let drag = null;
    box.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, spin: state.spin, tilt: state.tilt, moved: false, id: e.pointerId };
    });
    box.addEventListener("pointermove", (e) => {
      if (drag && drag.id === e.pointerId) {
        const dx = e.clientX - drag.x;
        const dy = e.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) > 4) {
          drag.moved = true;
          box.setPointerCapture(e.pointerId);
          box.classList.add("dragging");
          clearHot();
          hideTip();
        }
        if (drag.moved) {
          state.flat = false;
          state.spin = drag.spin + dx * 0.4;
          state.tilt = clamp(drag.tilt - dy * 0.3, 8, 80);
          apply();
          return;
        }
      }
      if (hot && hot.dataset.i != null) {
        const day = days[+hot.dataset.i];
        const rows = [{ value: day.n ? plural(day.n, "ticket") : "No tickets" }];
        if (day.top) rows.push({ value: String(day.topn), label: "about " + day.top });
        showTip(e.clientX, e.clientY, day.label, rows);
      }
    });
    const endDrag = () => {
      drag = null;
      box.classList.remove("dragging");
    };
    box.addEventListener("pointerup", endDrag);
    box.addEventListener("pointercancel", endDrag);

    // Keyboard: arrows turn and tilt, F flattens, Home resets.
    box.addEventListener("keydown", (e) => {
      const turn = { ArrowLeft: [0, -15], ArrowRight: [0, 15], ArrowUp: [6, 0], ArrowDown: [-6, 0] }[e.key];
      if (turn) {
        e.preventDefault();
        state.flat = false;
        state.tilt = clamp(state.tilt + turn[0], 8, 80);
        state.spin += turn[1];
        apply();
      } else if (e.key === "Home" || e.key === "r" || e.key === "R") {
        e.preventDefault();
        Object.assign(state, START, { flat: false });
        apply();
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        toggleFlat();
      }
    });
    function toggleFlat() {
      if (state.flat) Object.assign(state, START, { flat: false });
      else Object.assign(state, { tilt: 0, spin: 0, flat: true });
      apply();
    }
    if (controls) {
      controls.hidden = false;
      controls.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-act]");
        if (!btn) return;
        if (btn.dataset.act === "flat") toggleFlat();
        else {
          Object.assign(state, START, { flat: false });
          apply();
        }
      });
    }

    width = box.clientWidth;
    build(motion);
    if ("ResizeObserver" in window) {
      let timer = 0;
      new ResizeObserver(() => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          if (Math.abs(box.clientWidth - width) < 2) return;
          width = box.clientWidth;
          build(false);
        }, 150);
      }).observe(box);
    }
  }

  // ------------------------------------------------------------------- go
  blocks(document.getElementById("chart-days"));
  responsive(document.getElementById("chart-share"), shareChart);
  responsive(document.getElementById("chart-channels"), channelBar);
  responsive(document.getElementById("chart-gap"), gapChart);
  responsive(document.getElementById("chart-punch"), punchChart);
  responsive(document.getElementById("chart-band"), bandChart);
  responsive(document.getElementById("chart-flow"), flowChart);
})();
