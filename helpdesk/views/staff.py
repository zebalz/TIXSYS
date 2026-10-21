"""The staff workspace."""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Max, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .. import services
from ..forms import LogCallForm, NoteForm, TicketUpdateForm, staff_queryset
from ..models import Attachment, Board, Status, Ticket
from .portal import file_response

VIEWS = [
    ("open", "All open"),
    ("mine", "Mine"),
    ("unassigned", "Unassigned"),
    ("myboard", "My board"),
    ("done", "Resolved and closed"),
    ("all", "Everything"),
]
SORTS = [
    ("newest", "Newest first"),
    ("oldest", "Oldest first"),
    ("updated", "Recently updated"),
    ("priority", "Priority"),
]
PRIORITY_ORDER = Case(
    *[When(priority=key, then=Value(rank)) for key, rank in Ticket.PRIORITY_RANK.items()],
    default=Value(2),
    output_field=IntegerField(),
)


def staff_required(view):
    return login_required(view)


def _ticket_or_404(request, number):
    return get_object_or_404(
        Ticket.objects.select_related("status", "board", "category", "assignee", "created_by"),
        organization=request.org,
        number=number,
    )


@staff_required
@require_GET
def ticket_list(request):
    org = request.org
    user = request.user
    view = request.GET.get("view", "open")
    if view not in dict(VIEWS) or (view == "myboard" and not user.specialty_id):
        view = "open"
    qs = Ticket.objects.filter(organization=org).select_related("status", "board", "assignee", "category")
    done = Q(status__kind__in=Status.DONE_KINDS)
    if view == "open":
        qs = qs.exclude(done)
    elif view == "mine":
        qs = qs.filter(assignee=user).exclude(done)
    elif view == "unassigned":
        qs = qs.filter(assignee__isnull=True).exclude(done)
    elif view == "myboard":
        qs = qs.filter(board_id=user.specialty_id).exclude(done)
    elif view == "done":
        qs = qs.filter(done)

    f = {k: request.GET.get(k, "").strip() for k in ("board", "status", "priority", "assignee", "q")}
    if f["board"].isdigit():
        qs = qs.filter(board_id=int(f["board"]))
    if f["status"].isdigit():
        qs = qs.filter(status_id=int(f["status"]))
    if f["priority"] in dict(Ticket.PRIORITY_CHOICES):
        qs = qs.filter(priority=f["priority"])
    if f["assignee"] == "none":
        qs = qs.filter(assignee__isnull=True)
    elif f["assignee"].isdigit():
        qs = qs.filter(assignee_id=int(f["assignee"]))
    if f["q"]:
        q = f["q"].lstrip("#")
        match = (
            Q(summary__icontains=q)
            | Q(description__icontains=q)
            | Q(requester_name__icontains=q)
            | Q(requester_email__icontains=q)
            | Q(location__icontains=q)
        )
        if q.isdigit():
            match |= Q(number=int(q))
        qs = qs.filter(match)

    sort = request.GET.get("sort", "newest")
    if sort == "oldest":
        qs = qs.order_by("created_at")
    elif sort == "updated":
        qs = qs.order_by("-updated_at")
    elif sort == "priority":
        qs = qs.annotate(prank=PRIORITY_ORDER).order_by("prank", "created_at")
    else:
        sort = "newest"
        qs = qs.order_by("-created_at")

    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    keep = {k: v for k, v in f.items() if v}
    keep.update({"view": view, "sort": sort})
    filters_active = any(f.values())

    counts = {
        "open": Ticket.objects.filter(organization=org).exclude(done).count(),
        "mine": Ticket.objects.filter(organization=org, assignee=user).exclude(done).count(),
        "unassigned": Ticket.objects.filter(organization=org, assignee__isnull=True).exclude(done).count(),
    }
    if user.specialty_id:
        counts["myboard"] = Ticket.objects.filter(organization=org, board_id=user.specialty_id).exclude(done).count()
    views = [(key, label, counts.get(key)) for key, label in VIEWS if key != "myboard" or user.specialty_id]

    latest_id = Ticket.objects.filter(organization=org).aggregate(m=Max("id"))["m"] or 0
    return render(
        request,
        "staff/ticket_list.html",
        {
            "nav": "tickets",
            "page": page,
            "view": view,
            "views": views,
            "sort": sort,
            "sorts": SORTS,
            "f": f,
            "filters_active": filters_active,
            "boards": Board.objects.filter(organization=org),
            "statuses": Status.objects.filter(organization=org),
            "priorities": Ticket.PRIORITY_CHOICES,
            "staff": staff_queryset(org),
            "query_without_page": urlencode(keep),
            "latest_id": latest_id,
        },
    )


def _timeline(ticket):
    """Notes and field changes in time order. Note and file events are left out
    because the notes themselves show them."""
    items = [("note", n.created_at, n) for n in ticket.notes.select_related("author").prefetch_related("attachments")]
    for e in ticket.events.filter(action__in=["created", "changed"]):
        items.append(("event", e.created_at, e))
    items.sort(key=lambda i: (i[1], 0 if i[0] == "event" else 1))
    return items


def _ticket_page(request, ticket, update_form=None, note_form=None, status=200):
    return render(
        request,
        "staff/ticket.html",
        {
            "nav": "tickets",
            "ticket": ticket,
            "timeline": _timeline(ticket),
            "history": ticket.events.select_related("actor").order_by("-created_at", "-id"),
            "loose_files": ticket.attachments.filter(note__isnull=True),
            "update_form": update_form or TicketUpdateForm(instance=ticket),
            "note_form": note_form or NoteForm(),
            "private_link": request.build_absolute_uri(reverse("portal:ticket", args=[ticket.token])),
        },
        status=status,
    )


@staff_required
@require_GET
def ticket_detail(request, number):
    return _ticket_page(request, _ticket_or_404(request, number))


@staff_required
@require_POST
def ticket_update(request, number):
    ticket = _ticket_or_404(request, number)
    form = TicketUpdateForm(request.POST, instance=Ticket.objects.get(pk=ticket.pk))
    if not form.is_valid():
        return _ticket_page(request, ticket, update_form=form, status=400)
    changes = {name: form.cleaned_data[name] for name in services.TRACKED_FIELDS}
    try:
        changed = services.update_ticket(ticket, request.user, changes)
    except services.NotAllowed as e:
        messages.error(request, str(e))
        return redirect("staff:ticket", number=number)
    if changed:
        messages.success(request, "Saved: " + ", ".join(changed) + ".")
    else:
        messages.info(request, "Nothing changed.")
    return redirect("staff:ticket", number=number)


@staff_required
@require_POST
def ticket_take(request, number):
    ticket = _ticket_or_404(request, number)
    try:
        services.update_ticket(ticket, request.user, {"assignee": request.user})
    except services.NotAllowed as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Ticket #{ticket.number} is yours.")
    return redirect("staff:ticket", number=number)


@staff_required
@require_POST
def ticket_note(request, number):
    ticket = _ticket_or_404(request, number)
    form = NoteForm(request.POST, request.FILES)
    if not form.is_valid():
        return _ticket_page(request, ticket, note_form=form, status=400)
    data = form.cleaned_data
    note = services.add_note(ticket, request.user, data["kind"], data["body"], data["files"], data["mark_waiting"])
    messages.success(request, f"{note.get_kind_display()} note added.")
    return redirect(reverse("staff:ticket", args=[number]) + "#latest")


@staff_required
def attachment(request, attachment_id):
    att = get_object_or_404(Attachment.objects.select_related("ticket"), pk=attachment_id)
    if att.ticket.organization_id != request.org.id:
        raise PermissionDenied
    return file_response(att)


@staff_required
@require_http_methods(["GET", "POST"])
def log_call(request):
    org = request.org
    form = LogCallForm(request.POST or None, request.FILES or None, org=org)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ticket = services.create_ticket(
            org,
            requester_name=d["requester_name"],
            requester_email=d["requester_email"] or "",
            requester_phone=d["requester_phone"],
            location=d["location"],
            category=d["category"],
            board=d["board"],
            priority=d["priority"],
            source=d["source"],
            description=d["description"],
            created_by=request.user,
            assignee=request.user if d["assign_to_me"] else None,
            files=d["files"],
        )
        messages.success(request, f"Ticket #{ticket.number} logged.")
        return redirect("staff:ticket", number=ticket.number)
    return render(request, "staff/log_call.html", {"form": form, "nav": "log"})


@staff_required
@require_GET
def poll(request):
    """Polled by the workspace every few seconds for new-ticket alerts."""
    org = request.org
    try:
        after = int(request.GET.get("after", "0"))
    except ValueError:
        after = 0
    new = list(
        Ticket.objects.filter(organization=org, id__gt=after)
        .exclude(created_by=request.user)
        .select_related("board")
        .order_by("id")
        .values("id", "number", "summary", "board__name", "requester_name")[:20]
    )
    latest = Ticket.objects.filter(organization=org).aggregate(m=Max("id"))["m"] or 0
    return JsonResponse(
        {
            "latest_id": latest,
            "new": [
                {
                    "number": t["number"],
                    "summary": t["summary"],
                    "board": t["board__name"],
                    "requester": t["requester_name"],
                    "url": reverse("staff:ticket", args=[t["number"]]),
                }
                for t in new
            ],
        }
    )


# --- Reports -----------------------------------------------------------------


def _duration_words(td):
    if td is None:
        return "—"
    minutes = int(td.total_seconds() // 60)
    days, minutes = divmod(minutes, 60 * 24)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if not days and minutes:
        parts.append(f"{minutes} min")
    return " ".join(parts) or "under a minute"


def _bars(rows, label_key, count_key="n"):
    top = max([r[count_key] for r in rows] or [0]) or 1
    return [
        {"label": r[label_key] or "Unassigned", "n": r[count_key], "pct": round(100 * r[count_key] / top, 1)}
        for r in rows
    ]


@staff_required
@require_GET
def reports(request):
    from datetime import timedelta

    from django.db.models import Avg, Count, F
    from django.db.models.functions import TruncWeek
    from django.utils import timezone

    if not request.user.is_supervisor:
        raise PermissionDenied
    org = request.org
    tickets = Ticket.objects.filter(organization=org)
    open_qs = tickets.exclude(status__kind__in=Status.DONE_KINDS)

    by_board = _bars(list(open_qs.values("board__name").annotate(n=Count("id")).order_by("-n", "board__name")), "board__name")
    by_status = _bars(
        list(open_qs.values("status__name", "status__order").annotate(n=Count("id")).order_by("status__order")),
        "status__name",
    )
    assignee_rows = list(
        open_qs.values("assignee__first_name", "assignee__last_name", "assignee__username")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    for r in assignee_rows:
        full = f"{r['assignee__first_name'] or ''} {r['assignee__last_name'] or ''}".strip()
        r["who"] = full or r["assignee__username"]
    by_assignee = _bars(assignee_rows, "who")

    # Opened vs. resolved, last 8 weeks (weeks start Monday).
    weeks = 8
    now = timezone.localtime()
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = this_monday - timedelta(weeks=weeks - 1)
    opened = {
        r["w"].date(): r["n"]
        for r in tickets.filter(created_at__gte=start).annotate(w=TruncWeek("created_at")).values("w").annotate(n=Count("id"))
    }
    resolved = {
        r["w"].date(): r["n"]
        for r in tickets.filter(resolved_at__gte=start)
        .annotate(w=TruncWeek("resolved_at"))
        .values("w")
        .annotate(n=Count("id"))
    }
    week_rows = []
    for i in range(weeks):
        monday = (start + timedelta(weeks=i)).date()
        week_rows.append({"week": monday, "opened": opened.get(monday, 0), "resolved": resolved.get(monday, 0)})
    chart = _week_chart(week_rows)

    done = tickets.filter(resolved_at__isnull=False)
    avg_30 = done.filter(resolved_at__gte=now - timedelta(days=30)).aggregate(a=Avg(F("resolved_at") - F("created_at")))["a"]
    avg_all = done.aggregate(a=Avg(F("resolved_at") - F("created_at")))["a"]
    resolved_30 = done.filter(resolved_at__gte=now - timedelta(days=30)).count()

    oldest = open_qs.select_related("status", "board", "assignee").order_by("created_at")[:10]

    return render(
        request,
        "staff/reports.html",
        {
            "nav": "reports",
            "open_total": open_qs.count(),
            "by_board": by_board,
            "by_status": by_status,
            "by_assignee": by_assignee,
            "week_rows": week_rows,
            "chart": chart,
            "avg_30": _duration_words(avg_30),
            "avg_all": _duration_words(avg_all),
            "resolved_30": resolved_30,
            "oldest": oldest,
        },
    )


def _week_chart(rows):
    """Geometry for a paired bar chart drawn as SVG in the template."""
    width, height = 720, 240
    left, right, top, bottom = 36, 8, 16, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max([max(r["opened"], r["resolved"]) for r in rows] or [0])
    step = 1
    for candidate in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        step = candidate
        if peak / candidate <= 5:
            break
    y_max = max(step, ((peak + step - 1) // step) * step)
    group_w = plot_w / max(len(rows), 1)
    bar_w = min(22, (group_w - 14) / 2)
    gap = 2
    groups = []
    for i, r in enumerate(rows):
        gx = left + i * group_w
        center = gx + group_w / 2
        bars = []
        for j, key in enumerate(("opened", "resolved")):
            value = r[key]
            h = plot_h * value / y_max if y_max else 0
            x = center - bar_w - gap / 2 if j == 0 else center + gap / 2
            base = top + plot_h
            y = base - h
            rad = min(4, bar_w / 2, h)
            # Rounded at the data end only; square where it meets the baseline.
            d = (
                f"M{x:.1f},{base:.1f} V{y + rad:.1f} Q{x:.1f},{y:.1f} {x + rad:.1f},{y:.1f} "
                f"H{x + bar_w - rad:.1f} Q{x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + rad:.1f} V{base:.1f} Z"
            )
            bars.append({"key": key, "value": value, "d": d if h > 0 else "", "label_x": round(x + bar_w / 2, 1), "label_y": round(y - 5, 1)})
        groups.append(
            {
                "x": round(gx, 1),
                "w": round(group_w, 1),
                "center": round(center, 1),
                "label": r["week"].strftime("%b %-d"),
                "week": r["week"],
                "opened": r["opened"],
                "resolved": r["resolved"],
                "bars": bars,
            }
        )
    ticks = []
    value = 0
    while value <= y_max:
        ticks.append({"value": value, "y": round(top + plot_h - plot_h * value / y_max, 1)})
        value += step
    return {
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "base": top + plot_h,
        "label_y": height - 12,
        "groups": groups,
        "ticks": ticks,
    }
