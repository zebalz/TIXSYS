"""Ticket actions. Every change goes through here so history is always recorded."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Max
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Attachment, Note, Organization, Status, Ticket, TicketEvent, User

log = logging.getLogger(__name__)

FIRST_TICKET_NUMBER = 1001


def summary_from(description, limit=120):
    first_line = next((line.strip() for line in description.splitlines() if line.strip()), "")
    if len(first_line) <= limit:
        return first_line or "(no description)"
    cut = first_line[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "…"


def actor_label(user):
    return user.display_name if user else "System"


def record(ticket, action, actor=None, actor_name=None, field="", old="", new="", detail=""):
    return TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        actor_name=actor_name or actor_label(actor),
        action=action,
        field=field,
        old_value=str(old or "")[:200],
        new_value=str(new or "")[:200],
        detail=detail[:200],
    )


def touch(ticket, when=None):
    ticket.updated_at = when or timezone.now()
    Ticket.objects.filter(pk=ticket.pk).update(updated_at=ticket.updated_at)


def set_status(ticket, new_status):
    """Keeps resolved_at in step with the status."""
    ticket.status = new_status
    if new_status.is_done:
        if ticket.resolved_at is None:
            ticket.resolved_at = timezone.now()
    else:
        ticket.resolved_at = None


def private_url(ticket):
    return settings.SITE_URL + reverse("portal:ticket", args=[ticket.token])


def staff_url(ticket):
    return settings.SITE_URL + reverse("staff:ticket", args=[ticket.number])


@transaction.atomic
def create_ticket(
    org,
    *,
    requester_name,
    description,
    requester_email="",
    requester_phone="",
    location="",
    category=None,
    board=None,
    priority=Ticket.MEDIUM,
    source=Ticket.PORTAL,
    created_by=None,
    assignee=None,
    files=(),
    is_demo=False,
    created_at=None,
):
    # Lock the organization row so two tickets can't get the same number.
    Organization.objects.select_for_update().get(pk=org.pk)
    last = Ticket.objects.filter(organization=org).aggregate(m=Max("number"))["m"]
    number = (last or FIRST_TICKET_NUMBER - 1) + 1

    if board is None:
        board = (category.board if category and category.board and category.board.is_active else None) or org.default_board()
    status = org.status_of_kind(Status.ASSIGNED if assignee else Status.NEW) or org.status_of_kind(Status.NEW)
    when = created_at or timezone.now()

    ticket = Ticket.objects.create(
        organization=org,
        number=number,
        summary=summary_from(description),
        description=description.strip(),
        board=board,
        status=status,
        priority=priority,
        category=category,
        assignee=assignee,
        requester_name=requester_name.strip(),
        requester_email=requester_email.strip().lower(),
        requester_phone=requester_phone.strip(),
        location=location.strip(),
        source=source,
        created_by=created_by,
        created_at=when,
        updated_at=when,
        is_demo=is_demo,
    )
    via = dict(Ticket.SOURCE_CHOICES).get(source, source).lower()
    if created_by:
        event = record(ticket, TicketEvent.CREATED, actor=created_by, detail=f"logged a {via} from {ticket.requester_name}")
    else:
        event = record(ticket, TicketEvent.CREATED, actor_name=ticket.requester_name, detail="submitted on the portal")
    if created_at:
        TicketEvent.objects.filter(pk=event.pk).update(created_at=when)
    if assignee:
        ev = record(ticket, TicketEvent.CHANGED, actor=created_by, field="assignee", new=assignee.display_name)
        if created_at:
            TicketEvent.objects.filter(pk=ev.pk).update(created_at=when)

    for f in files:
        save_attachment(ticket, f, from_requester=created_by is None, uploaded_by=created_by)

    if not is_demo:
        transaction.on_commit(lambda: notify_new_ticket(ticket))
    return ticket


def save_attachment(ticket, uploaded, *, note=None, from_requester=False, uploaded_by=None):
    from .uploads import detected_type

    content_type = detected_type(uploaded)
    uploaded.seek(0)
    att = Attachment(
        ticket=ticket,
        note=note,
        original_name=uploaded.name[:200],
        content_type=content_type,
        size=uploaded.size,
        from_requester=from_requester,
        uploaded_by=uploaded_by,
    )
    att.file.save(uploaded.name, uploaded, save=False)
    att.save()
    who = ticket.requester_name if from_requester else None
    record(ticket, TicketEvent.ATTACHMENT, actor=uploaded_by, actor_name=who, detail=f"added a file: {att.original_name}")
    return att


TRACKED_FIELDS = ("summary", "assignee", "status", "priority", "board", "category")


def field_label(ticket, name):
    value = getattr(ticket, name)
    if name == "priority":
        return ticket.get_priority_display()
    if value is None:
        return ""
    if name == "assignee":
        return value.display_name
    return str(value)


class NotAllowed(Exception):
    pass


@transaction.atomic
def update_ticket(ticket, user, changes):
    """changes: dict of field -> new value for any of TRACKED_FIELDS."""
    before = {name: getattr(ticket, name) for name in TRACKED_FIELDS}
    labels_before = {name: field_label(ticket, name) for name in TRACKED_FIELDS}

    new_assignee = changes.get("assignee", before["assignee"])
    if new_assignee != before["assignee"] and before["assignee"] is not None and before["assignee"] != user:
        if not user.is_supervisor:
            raise NotAllowed(
                f"This ticket belongs to {before['assignee'].display_name}. Only a supervisor can reassign it."
            )

    for name in ("summary", "board", "priority", "category", "assignee"):
        if name in changes:
            setattr(ticket, name, changes[name])

    status_given = "status" in changes and changes["status"] != before["status"]
    if status_given:
        set_status(ticket, changes["status"])
    elif ticket.assignee and before["assignee"] is None and ticket.status.kind == Status.NEW:
        assigned = ticket.organization.status_of_kind(Status.ASSIGNED)
        if assigned:
            set_status(ticket, assigned)
    elif ticket.assignee is None and before["assignee"] is not None and ticket.status.kind == Status.ASSIGNED:
        new_status = ticket.organization.status_of_kind(Status.NEW)
        if new_status:
            set_status(ticket, new_status)

    changed = []
    for name in TRACKED_FIELDS:
        if getattr(ticket, name) != before[name]:
            changed.append(name)
            record(ticket, TicketEvent.CHANGED, actor=user, field=name, old=labels_before[name], new=field_label(ticket, name))
    if changed:
        ticket.updated_at = timezone.now()
        ticket.save()
    return changed


@transaction.atomic
def add_note(ticket, user, kind, body, files=(), mark_waiting=False):
    note = Note.objects.create(ticket=ticket, kind=kind, body=body.strip(), author=user, author_name=user.display_name)
    record(ticket, TicketEvent.NOTE, actor=user, detail=f"added a {note.get_kind_display().lower()} note")
    for f in files:
        save_attachment(ticket, f, note=note, uploaded_by=user)

    target = None
    if kind == Note.RESOLUTION:
        target = ticket.organization.status_of_kind(Status.RESOLVED)
    elif kind == Note.DISCUSSION and mark_waiting:
        target = ticket.organization.status_of_kind(Status.WAITING)
    if target and ticket.status != target:
        old = ticket.status.name
        set_status(ticket, target)
        record(ticket, TicketEvent.CHANGED, actor=user, field="status", old=old, new=target.name)
    ticket.updated_at = timezone.now()
    ticket.save()

    if note.visible_to_requester:
        transaction.on_commit(lambda: notify_requester_of_note(ticket, note))
    return note


@transaction.atomic
def add_requester_reply(ticket, body, files=()):
    note = Note.objects.create(
        ticket=ticket,
        kind=Note.DISCUSSION,
        body=body.strip(),
        author_name=ticket.requester_name,
        from_requester=True,
    )
    record(ticket, TicketEvent.REPLY, actor_name=ticket.requester_name, detail="replied")
    for f in files:
        save_attachment(ticket, f, note=note, from_requester=True)

    # A reply means someone needs to look again.
    if ticket.status.kind in (Status.WAITING, Status.RESOLVED):
        target = ticket.organization.status_of_kind(Status.IN_PROGRESS) or ticket.organization.status_of_kind(
            Status.NEW
        )
        if target:
            old = ticket.status.name
            set_status(ticket, target)
            record(
                ticket,
                TicketEvent.CHANGED,
                actor_name=ticket.requester_name,
                field="status",
                old=old,
                new=target.name,
            )
    ticket.updated_at = timezone.now()
    ticket.save()
    transaction.on_commit(lambda: notify_staff_of_reply(ticket, note))
    return note


# --- Email -------------------------------------------------------------------


def _send(subject, template, context, recipients):
    recipients = [r for r in recipients if r]
    if not settings.EMAIL_ENABLED or not recipients:
        return 0
    try:
        body = render_to_string(template, context)
        return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
    except Exception:  # email trouble must never break the help desk
        log.exception("Could not send email: %s", subject)
        return 0


def staff_alert_recipients(org):
    return list(
        User.objects.filter(organization=org, is_active=True, email_alerts=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def notify_new_ticket(ticket):
    org = ticket.organization
    if ticket.requester_email:
        _send(
            f"Ticket #{ticket.number} received: {ticket.summary}",
            "email/requester_new.txt",
            {"ticket": ticket, "org": org, "link": private_url(ticket)},
            [ticket.requester_email],
        )
    _send(
        f"New ticket #{ticket.number} on {ticket.board}: {ticket.summary}",
        "email/staff_new.txt",
        {"ticket": ticket, "org": org, "link": staff_url(ticket)},
        staff_alert_recipients(org),
    )


def notify_requester_of_note(ticket, note):
    if not ticket.requester_email:
        return
    subject = (
        f"Ticket #{ticket.number} resolved: {ticket.summary}"
        if note.kind == Note.RESOLUTION
        else f"Update on ticket #{ticket.number}: {ticket.summary}"
    )
    _send(
        subject,
        "email/requester_note.txt",
        {"ticket": ticket, "note": note, "org": ticket.organization, "link": private_url(ticket)},
        [ticket.requester_email],
    )


def notify_staff_of_reply(ticket, note):
    if ticket.assignee and ticket.assignee.email:
        recipients = [ticket.assignee.email]
    else:
        recipients = staff_alert_recipients(ticket.organization)
    _send(
        f"Reply on ticket #{ticket.number}: {ticket.summary}",
        "email/staff_reply.txt",
        {"ticket": ticket, "note": note, "org": ticket.organization, "link": staff_url(ticket)},
        recipients,
    )


def send_ticket_links(org, email):
    tickets = list(
        Ticket.objects.filter(organization=org, requester_email=email.strip().lower()).order_by("-created_at")[:50]
    )
    if not tickets:
        return 0
    links = [(t, private_url(t)) for t in tickets]
    return _send(
        f"Your {org.portal_title} tickets",
        "email/requester_links.txt",
        {"org": org, "links": links},
        [email],
    )
