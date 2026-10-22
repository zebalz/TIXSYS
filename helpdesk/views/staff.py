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

from .. import safe, search, security_log, services
from ..export import ticket_as_text, tickets_as_text
from ..forms import LogCallForm, NoteForm, TicketUpdateForm, staff_queryset
from ..models import Attachment, Board, SavedSearch, SecurityEvent, Status, Ticket
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
    ("best", "Best match"),
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


def _filtered_tickets(request):
    """The ticket list as the current view, filters, search and sort select it."""
    org = request.org
    user = request.user
    q_text = safe.text(request.GET.get("q"), 500)
    # A search looks through every ticket unless a view was picked.
    view = request.GET.get("view") or ("all" if q_text else "open")
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

    f = {k: safe.text(request.GET.get(k), 100) for k in ("board", "status", "priority", "assignee")}
    f["q"] = q_text
    if safe.number(f["board"]) is not None:
        qs = qs.filter(board_id=safe.number(f["board"]))
    if safe.number(f["status"]) is not None:
        qs = qs.filter(status_id=safe.number(f["status"]))
    if f["priority"] in dict(Ticket.PRIORITY_CHOICES):
        qs = qs.filter(priority=f["priority"])
    if f["assignee"] == "none":
        qs = qs.filter(assignee__isnull=True)
    elif safe.number(f["assignee"]) is not None:
        qs = qs.filter(assignee_id=safe.number(f["assignee"]))
    parsed = search.parse(f["q"], user=user)
    qs = search.apply(qs, parsed)

    sort = request.GET.get("sort") or ("best" if parsed.has_text else "newest")
    if sort == "best" and parsed.has_text:
        qs = qs.order_by("-rank", "-created_at")
    elif sort == "oldest":
        qs = qs.order_by("created_at")
    elif sort == "updated":
        qs = qs.order_by("-updated_at")
    elif sort == "priority":
        qs = qs.annotate(prank=PRIORITY_ORDER).order_by("prank", "created_at")
    else:
        sort = "newest"
        qs = qs.order_by("-created_at")
    return qs, view, sort, f, parsed


@staff_required
@require_GET
def ticket_list(request):
    org = request.org
    user = request.user
    qs, view, sort, f, parsed = _filtered_tickets(request)
    done = Q(status__kind__in=Status.DONE_KINDS)

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
            "q_param": urlencode({"q": f["q"]}) if f["q"] else "",
            "latest_id": latest_id,
            "parsed": parsed,
            "field_help": search.FIELD_HELP,
            "current_query": urlencode(keep),
        },
    )


@staff_required
@require_POST
def save_search(request):
    name = safe.text(request.POST.get("name"), 60)
    query_string = safe.query_string(request.POST.get("query_string"))
    if not name or not query_string:
        messages.error(request, "Give the search a name to save it.")
        return redirect(reverse("staff:tickets") + ("?" + query_string if query_string else ""))
    SavedSearch.objects.update_or_create(user=request.user, name=name, defaults={"query_string": query_string})
    messages.success(request, f"Saved search \u201c{name}\u201d. It's in your sidebar.")
    return redirect(reverse("staff:tickets") + "?" + query_string)


@staff_required
@require_POST
def delete_search(request, search_id):
    SavedSearch.objects.filter(user=request.user, pk=search_id).delete()
    messages.info(request, "Saved search removed.")
    return redirect("staff:tickets")


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
            "copy_text": ticket_as_text(ticket),
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
@require_POST
def reset_link(request, number):
    ticket = _ticket_or_404(request, number)
    services.reset_private_link(ticket, request.user)
    security_log.record(request, SecurityEvent.LINK_RESET, user=request.user, detail=f"ticket #{ticket.number}")
    messages.success(request, "New private link made. The old link no longer works. Send the new one to the employee.")
    return redirect("staff:ticket", number=number)


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
    after = safe.number(request.GET.get("after")) or 0
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


def _bars(rows, label_key, count_key="n"):
    top = max([r[count_key] for r in rows] or [0]) or 1
    return [
        {"label": r[label_key] or "Unassigned", "n": r[count_key], "pct": round(100 * r[count_key] / top, 1)}
        for r in rows
    ]


@staff_required
@require_GET
def reports(request):
    from django.db.models import Count

    from .. import reports as report_data

    if not request.user.is_supervisor:
        raise PermissionDenied
    org = request.org
    weeks = report_data.pick_weeks(request.GET.get("weeks"))
    data = report_data.build(org, weeks)

    tickets = Ticket.objects.filter(organization=org)
    open_qs = tickets.exclude(status__kind__in=Status.DONE_KINDS)
    by_board = _bars(
        list(open_qs.values("board__name").annotate(n=Count("id")).order_by("-n", "board__name")), "board__name"
    )
    by_status = _bars(
        list(open_qs.values("status__name", "status__order").annotate(n=Count("id")).order_by("status__order")),
        "status__name",
    )
    assignee_rows = list(
        open_qs.values("assignee__first_name", "assignee__last_name", "assignee__username")
        .annotate(n=Count("id"))
        .order_by("-n", "assignee__first_name")
    )
    for r in assignee_rows:
        full = f"{r['assignee__first_name'] or ''} {r['assignee__last_name'] or ''}".strip()
        r["who"] = full or r["assignee__username"]
    by_assignee = _bars(assignee_rows, "who")
    by_category = _bars(
        list(
            tickets.filter(created_at__gte=data["start"])
            .values("category__name")
            .annotate(n=Count("id"))
            .order_by("-n", "category__name")[:6]
        ),
        "category__name",
    )
    for r in by_category:
        if r["label"] == "Unassigned":
            r["label"] = "No category"
    oldest = open_qs.select_related("status", "board", "assignee").order_by("created_at")[:8]

    return render(
        request,
        "staff/reports.html",
        {
            "nav": "reports",
            "r": data,
            "ranges": report_data.RANGES,
            "by_board": by_board,
            "by_status": by_status,
            "by_assignee": by_assignee,
            "by_category": by_category,
            "oldest": oldest,
        },
    )


@staff_required
@require_GET
def export_text(request):
    """The tickets in the current list view as one plain-text file, one block per ticket."""
    from django.http import HttpResponse
    from django.utils import timezone

    qs, _view, _sort, f, _parsed = _filtered_tickets(request)
    body = tickets_as_text(qs.prefetch_related("notes"))
    security_log.record(
        request, SecurityEvent.EXPORT, user=request.user, detail=f"{qs.count()} tickets; search: {f['q'][:150]}"
    )
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="tickets-{stamp}.txt"'
    return response
