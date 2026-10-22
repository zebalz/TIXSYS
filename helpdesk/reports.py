"""Numbers for the Reports page.

Everything is counted in the database with a handful of grouped queries,
then shaped into small lists for the page. The page draws the charts from
these lists (static/js/charts.js) and also prints every number in
"Show as a table" sections, so nothing depends on the charts.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Count
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate, TruncWeek
from django.utils import timezone

from .models import Status, Ticket

RANGES = (4, 12, 26)  # weeks the page can show
DEFAULT_WEEKS = 12

# Channel order is fixed: it decides each channel's chart color (slot 1, 2, 3...).
CHANNELS = [
    (Ticket.PORTAL, "Portal"),
    (Ticket.PHONE, "Phone"),
    (Ticket.WALKUP, "Walk-up"),
    (Ticket.TEXT, "Text"),
    (Ticket.EMAIL, "Email"),
    (Ticket.OTHER, "Other"),
]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_LONG = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
OFFICE_HOURS = (8, 17)  # 8 AM to 5 PM, Monday to Friday


def hour_label(h):
    h = h % 24
    return f"{12 if h % 12 == 0 else h % 12} {'AM' if h < 12 else 'PM'}"


def pick_weeks(raw):
    try:
        weeks = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WEEKS
    return weeks if weeks in RANGES else DEFAULT_WEEKS


def percentile(sorted_values, p):
    """Linear-interpolated percentile of an already sorted list (p from 0 to 1)."""
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def hours_words(hours):
    """3.25 -> '3 hr 15 min'; 0.4 -> '24 min'; 50 -> '2 days 2 hr'."""
    if hours is None:
        return "—"
    minutes = round(hours * 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    days, minutes = divmod(minutes, 24 * 60)
    hrs, minutes = divmod(minutes, 60)
    if days:
        return f"{days} day{'s' if days != 1 else ''}" + (f" {hrs} hr" if hrs else "")
    return f"{hrs} hr" + (f" {minutes} min" if minutes else "")


def hours_short(hours):
    """Headline version: 0.75 -> '45 min', 1.5 -> '1 hr 30 min', 3.9 -> '4 hr', 60 -> '2.5 days'."""
    if hours is None:
        return "—"
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 3:
        whole = int(hours)
        minutes = round((hours - whole) * 60)
        if minutes == 60:
            whole, minutes = whole + 1, 0
        return f"{whole} hr" + (f" {minutes} min" if minutes else "")
    if hours < 48:
        return f"{round(hours)} hr"
    days = round(hours / 24, 1)
    return f"{days:g} days"


def _local_monday(moment):
    local = timezone.localtime(moment)
    monday = local.date() - timedelta(days=local.weekday())
    return timezone.make_aware(datetime.combine(monday, time.min))


def _as_date(value):
    """Database week/day buckets arrive as dates or local datetimes."""
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def _resolve_hours(rows):
    return sorted((r - c).total_seconds() / 3600 for c, r in rows if r >= c)


def build(org, weeks=DEFAULT_WEEKS, now=None):
    now = now or timezone.now()
    tickets = Ticket.objects.filter(organization=org)
    start = _local_monday(now) - timedelta(weeks=weeks - 1)
    prev_start = start - timedelta(weeks=weeks)
    in_range = tickets.filter(created_at__gte=start)
    resolved_in_range = tickets.filter(resolved_at__gte=start)
    open_qs = tickets.exclude(status__kind__in=Status.DONE_KINDS)

    # --- Weekly series -------------------------------------------------------
    week_starts = [(start + timedelta(weeks=i)).date() for i in range(weeks)]
    opened = defaultdict(int)
    portal = defaultdict(int)
    for row in in_range.annotate(w=TruncWeek("created_at")).values("w", "source").annotate(n=Count("id")).order_by():
        w = _as_date(row["w"])
        opened[w] += row["n"]
        if row["source"] == Ticket.PORTAL:
            portal[w] += row["n"]

    resolved_rows = list(resolved_in_range.values_list("created_at", "resolved_at"))
    durations_by_week = defaultdict(list)
    for created, resolved in resolved_rows:
        if resolved >= created:
            w = timezone.localtime(resolved).date()
            w = w - timedelta(days=w.weekday())
            durations_by_week[w].append((resolved - created).total_seconds() / 3600)

    week_list = []
    for w in week_starts:
        hours = sorted(durations_by_week.get(w, []))
        total = opened.get(w, 0)
        week_list.append(
            {
                "start": w.isoformat(),
                "label": f"{w:%b} {w.day}",
                "opened": total,
                "resolved": len(hours),
                "portal": portal.get(w, 0),
                "share": round(100 * portal.get(w, 0) / total) if total else None,
                "p25": _round(percentile(hours, 0.25)),
                "p50": _round(percentile(hours, 0.5)),
                "p75": _round(percentile(hours, 0.75)),
            }
        )
    for w in week_list:
        net = w["opened"] - w["resolved"]
        w["net"] = f"up {net}" if net > 0 else (f"down {-net}" if net < 0 else "no change")
        w["median_words"] = hours_words(w["p50"]) if w["p50"] is not None else "—"
        w["middle_words"] = f"{hours_words(w['p25'])} – {hours_words(w['p75'])}" if w["p25"] is not None else "—"

    # --- Every day (the 3D chart) -------------------------------------------
    per_day = {
        _as_date(r["d"]): r["n"]
        for r in in_range.annotate(d=TruncDate("created_at")).values("d").annotate(n=Count("id")).order_by()
    }
    top_by_day = {}
    for r in (
        in_range.annotate(d=TruncDate("created_at"))
        .values("d", "category__name")
        .annotate(n=Count("id"))
        .order_by("d", "-n", "category__name")
    ):
        top_by_day.setdefault(_as_date(r["d"]), (r["category__name"] or "No category", r["n"]))
    today = timezone.localtime(now).date()
    day_list = []
    for i in range(weeks * 7):
        d = start.date() + timedelta(days=i)
        top = top_by_day.get(d)
        day_list.append(
            {
                "d": d.isoformat(),
                "label": f"{DAY_NAMES[d.weekday()]}, {d:%b} {d.day}",
                "n": per_day.get(d, 0),
                "top": top[0] if top else "",
                "topn": top[1] if top else 0,
                "future": d > today,
            }
        )

    # --- Day of week x hour (punch card) ------------------------------------
    punch = [[0] * 24 for _ in range(7)]
    for r in (
        in_range.annotate(wd=ExtractIsoWeekDay("created_at"), hr=ExtractHour("created_at"))
        .values("wd", "hr")
        .annotate(n=Count("id"))
        .order_by()
    ):
        punch[r["wd"] - 1][r["hr"]] += r["n"]
    busiest_slot = max(((punch[d][h], d, h) for d in range(7) for h in range(24)), default=(0, 0, 0))
    after_hours = sum(
        punch[d][h] for d in range(7) for h in range(24) if d >= 5 or h < OFFICE_HOURS[0] or h >= OFFICE_HOURS[1]
    )

    # --- How tickets came in -------------------------------------------------
    by_source = {r["source"]: r["n"] for r in in_range.values("source").annotate(n=Count("id")).order_by()}
    total_in_range = sum(by_source.values())
    channels = [
        {"key": key, "label": label, "n": by_source.get(key, 0), "pct": _pct(by_source.get(key, 0), total_in_range)}
        for key, label in CHANNELS
    ]

    # --- Flow: channel -> board -> fixed or still open -----------------------
    strands = []
    for r in in_range.values("source", "board__name", "status__kind").annotate(n=Count("id")).order_by():
        strands.append(
            {
                "s": r["source"],
                "b": r["board__name"] or "No board",
                "o": "fixed" if r["status__kind"] in Status.DONE_KINDS else "open",
                "n": r["n"],
            }
        )
    merged = defaultdict(int)
    for s in strands:
        merged[(s["s"], s["b"], s["o"])] += s["n"]
    strands = [{"s": s, "b": b, "o": o, "n": n} for (s, b, o), n in merged.items()]
    board_order = list(org.boards.order_by("order", "name").values_list("name", flat=True))

    # --- Headline numbers ----------------------------------------------------
    hours = _resolve_hours(resolved_rows)
    prev_hours = _resolve_hours(
        tickets.filter(resolved_at__gte=prev_start, resolved_at__lt=start).values_list("created_at", "resolved_at")
    )
    median = percentile(hours, 0.5)
    prev_median = percentile(prev_hours, 0.5)
    within_day = _pct(sum(1 for h in hours if h <= 24), len(hours)) if hours else None
    prev_resolved = len(prev_hours)
    portal_total = by_source.get(Ticket.PORTAL, 0)

    first_share = next((w["share"] for w in week_list if w["share"] is not None), None)
    last_share = next((w["share"] for w in reversed(week_list) if w["share"] is not None), None)

    kpis = {
        "open_now": open_qs.count(),
        "unassigned": open_qs.filter(assignee__isnull=True).count(),
        "waiting": open_qs.filter(status__kind=Status.WAITING).count(),
        "resolved": len(hours),
        "resolved_change": _change(len(hours), prev_resolved),
        "resolved_change_abs": abs(_change(len(hours), prev_resolved) or 0),
        "median": hours_short(median),
        "median_change": _change(median, prev_median),
        "median_change_abs": abs(_change(median, prev_median) or 0),
        "within_day": within_day,
        "portal_total": portal_total,
        "portal_share": _pct(portal_total, total_in_range),
        "total": total_in_range,
        "first_share": first_share,
        "last_share": last_share,
    }

    busiest = max(day_list, key=lambda d: d["n"]) if day_list else None

    return {
        "weeks": weeks,
        "start": start.date(),
        "end": today,
        "kpis": kpis,
        "week_list": week_list,
        "day_list": day_list,
        "day_grid": [
            {
                "label": date_label(date.fromisoformat(day_list[i]["d"])),
                "days": day_list[i : i + 7],
                "total": sum(d["n"] for d in day_list[i : i + 7]),
            }
            for i in range(0, len(day_list), 7)
        ],
        "flow_rows": _flow_rows(strands, board_order),
        "busiest": busiest if busiest and busiest["n"] else None,
        "busiest_slot": {
            "n": busiest_slot[0],
            "day": DAY_LONG[busiest_slot[1]],
            "hours": f"{hour_label(busiest_slot[2])}–{hour_label(busiest_slot[2] + 1)}",
        }
        if busiest_slot[0]
        else None,
        "after_hours": after_hours,
        "office_hours": f"{hour_label(OFFICE_HOURS[0])}–{hour_label(OFFICE_HOURS[1])}",
        "hour_labels": [hour_label(h) for h in range(24)],
        "punch": punch,
        "punch_rows": [{"day": DAY_NAMES[i], "hours": punch[i]} for i in range(7)],
        "channels": channels,
        "strands": strands,
        "boards": board_order,
        "chart_data": {
            "weeks": week_list,
            "days": day_list,
            "punch": punch,
            "channels": channels,
            "strands": strands,
            "boards": board_order,
            "dayNames": DAY_NAMES,
        },
    }


def _flow_rows(strands, board_order):
    labels = dict(CHANNELS)
    rows = {}
    for s in strands:
        row = rows.setdefault(
            (s["s"], s["b"]), {"source": labels.get(s["s"], s["s"]), "board": s["b"], "fixed": 0, "open": 0}
        )
        row[s["o"]] += s["n"]
    channel_rank = {key: i for i, (key, _) in enumerate(CHANNELS)}
    board_rank = {name: i for i, name in enumerate(board_order)}
    return [rows[k] for k in sorted(rows, key=lambda k: (channel_rank.get(k[0], 99), board_rank.get(k[1], 99), k[1]))]


def _round(value):
    return None if value is None else round(value, 2)


def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


def _change(current, previous):
    """Percent change from the previous period, or None when there's nothing to compare."""
    if current is None or not previous:
        return None
    return round(100 * (current - previous) / previous)


def date_label(d: date):
    return f"{d:%b} {d.day}"
