"""Tickets as plain text, for copying each one into another ticketing system."""

from django.utils import timezone

from .models import Note

RULE = "=" * 60


def _when(value):
    return timezone.localtime(value).strftime("%b %d, %Y %I:%M %p") if value else ""


def ticket_as_text(ticket, include_internal=True):
    lines = [
        f"Ticket #{ticket.number}: {ticket.summary}",
        f"Status: {ticket.status.name}",
        f"Priority: {ticket.get_priority_display()}",
        f"Board: {ticket.board.name}",
        f"Category: {ticket.category.name if ticket.category else ''}",
        f"Assigned to: {ticket.assignee.display_name if ticket.assignee else 'Unassigned'}",
        f"Opened: {_when(ticket.created_at)}",
    ]
    if ticket.resolved_at:
        lines.append(f"Resolved: {_when(ticket.resolved_at)}")
    lines += [
        f"Requester: {ticket.requester_name}",
        f"Email: {ticket.requester_email}",
        f"Phone: {ticket.requester_phone}",
        f"Location: {ticket.location}",
        f"Came in by: {ticket.get_source_display()}",
        "",
        "Description:",
        ticket.description,
    ]
    notes = [n for n in ticket.notes.all() if include_internal or n.kind != Note.INTERNAL]
    if notes:
        lines += ["", "Notes:"]
        for n in notes:
            kind = "Employee reply" if n.from_requester else n.get_kind_display()
            lines.append(f"- {_when(n.created_at)}, {n.author_name} ({kind}): {n.body}")
    return "\n".join(lines).strip() + "\n"


def tickets_as_text(tickets):
    blocks = [ticket_as_text(t) for t in tickets]
    return f"\n{RULE}\n\n".join(blocks) if blocks else "No tickets matched.\n"
