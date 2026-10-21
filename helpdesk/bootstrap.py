"""Creates the organization and starter settings on first run. Safe to run again."""

from django.db import transaction

from .models import Board, Category, Organization, Status

DEFAULT_STATUSES = [
    ("New", Status.NEW),
    ("Assigned", Status.ASSIGNED),
    ("In progress", Status.IN_PROGRESS),
    ("Waiting on employee", Status.WAITING),
    ("Resolved", Status.RESOLVED),
    ("Closed", Status.CLOSED),
]

DEFAULT_CATEGORIES = [
    "Password or sign-in",
    "Email and Outlook",
    "Printer or scanner",
    "Computer or hardware",
    "Software or app",
    "Network, Wi-Fi or VPN",
    "Phone or voicemail",
    "New employee setup",
    "Something else",
]


@transaction.atomic
def ensure_defaults(name=None):
    org = Organization.objects.order_by("id").first()
    if org is None:
        org = Organization.objects.create(name=name or "Your Organization")
    if not org.statuses.exists():
        for i, (status_name, kind) in enumerate(DEFAULT_STATUSES):
            Status.objects.create(organization=org, name=status_name, kind=kind, order=(i + 1) * 10)
    if not org.boards.exists():
        Board.objects.create(
            organization=org, name="Help Desk", description="Everyday IT requests", is_default=True, order=10
        )
    if not org.categories.exists():
        for i, category_name in enumerate(DEFAULT_CATEGORIES):
            Category.objects.create(organization=org, name=category_name, order=(i + 1) * 10)
    return org
