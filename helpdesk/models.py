import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

hex_color = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use a 6-digit hex color like #2A5585.")


def new_ticket_token():
    # 256 bits of randomness: the private link can't be guessed from the ticket number.
    return secrets.token_urlsafe(32)


class Organization(models.Model):
    """One organization. Every record points at one, so a single install
    can serve several organizations later without changing the data."""

    name = models.CharField(max_length=120, default="Your Organization")
    slug = models.SlugField(unique=True, default="main")
    portal_title = models.CharField("Portal title", max_length=120, default="IT Help Desk")
    logo = models.ImageField(upload_to="branding/", blank=True, help_text="PNG or JPG. Shown in the portal header.")
    brand_color = models.CharField(
        max_length=7, default="#2A5585", validators=[hex_color], help_text="Buttons and links, e.g. #2A5585."
    )
    header_color = models.CharField(
        max_length=7, default="#17222E", validators=[hex_color], help_text="Portal header background, e.g. #17222E."
    )
    help_phone = models.CharField(
        "Help desk phone", max_length=60, blank=True, help_text="Shown on the portal for urgent problems."
    )
    welcome_text = models.TextField(
        blank=True, help_text="Optional short message under the portal heading (outages, holiday hours)."
    )
    remote_help_text = models.TextField(
        blank=True, help_text="Optional extra instructions on the Get remote help page."
    )
    allowed_email_domain = models.CharField(
        max_length=200,
        blank=True,
        help_text="If set (e.g. example.org), the portal only accepts email addresses from this domain. "
        "Separate several domains with commas.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "organization and branding"
        verbose_name_plural = "organization and branding"

    def __str__(self):
        return self.name

    def allowed_domains(self):
        return [d.strip().lower().lstrip("@") for d in self.allowed_email_domain.split(",") if d.strip()]

    def default_board(self):
        return self.boards.filter(is_active=True).order_by("-is_default", "order", "id").first()

    def status_of_kind(self, kind):
        return self.statuses.filter(kind=kind, is_active=True).order_by("order", "id").first()


class Board(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="boards")
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=10)
    is_default = models.BooleanField(
        "Default board", default=False, help_text="New portal tickets land here unless their category says otherwise."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name


class Category(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    board = models.ForeignKey(
        Board,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categories",
        help_text="Tickets in this category go to this board. Leave empty for the default board.",
    )
    show_on_portal = models.BooleanField(default=True, help_text="Employees can pick it on the portal.")
    order = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "categories"
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name


class Status(models.Model):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    RESOLVED = "resolved"
    CLOSED = "closed"
    OPEN_OTHER = "open"
    KIND_CHOICES = [
        (NEW, "New — given to every new ticket"),
        (ASSIGNED, "Assigned — set when a new ticket gets an assignee"),
        (IN_PROGRESS, "In progress — set when the employee replies"),
        (WAITING, "Waiting on employee"),
        (RESOLVED, "Resolved — set by a resolution note"),
        (CLOSED, "Closed"),
        (OPEN_OTHER, "Other open status"),
    ]
    DONE_KINDS = (RESOLVED, CLOSED)

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="statuses")
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=OPEN_OTHER)
    order = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name_plural = "statuses"
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name

    @property
    def is_done(self):
        return self.kind in self.DONE_KINDS


class User(AbstractUser):
    """A staff account. Employees who submit tickets don't need an account."""

    TECHNICIAN = "technician"
    DEVELOPER = "developer"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    ROLE_CHOICES = [
        (TECHNICIAN, "Technician"),
        (DEVELOPER, "Developer"),
        (SUPERVISOR, "Supervisor"),
        (ADMIN, "Administrator"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True, related_name="staff"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=TECHNICIAN)
    phone = models.CharField("Phone or extension", max_length=60, blank=True)
    zoom_link = models.URLField(
        "Zoom link", blank=True, help_text="Personal meeting link. Shown on the portal's Get remote help page."
    )
    specialty = models.ForeignKey(
        Board,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="specialists",
        help_text="For developers: the board for their specialty. Shows as 'My board' in the workspace.",
    )
    email_alerts = models.BooleanField(
        "Email me about new tickets", default=True, help_text="Only used when email is turned on."
    )
    totp_secret = models.CharField(max_length=64, blank=True, editable=False)
    totp_enabled = models.BooleanField("Authenticator app required", default=False, editable=False)
    totp_last_counter = models.BigIntegerField(default=0, editable=False)

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]
        verbose_name = "staff account"

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def is_supervisor(self):
        return self.role in (self.SUPERVISOR, self.ADMIN)

    @property
    def is_admin_role(self):
        return self.role == self.ADMIN

    def save(self, *args, **kwargs):
        # The role is the single source of truth for access to settings.
        if self.is_superuser and self.role != self.ADMIN and not self.pk:
            self.role = self.ADMIN  # createsuperuser
        self.is_staff = self.is_superuser = self.role == self.ADMIN
        if self.organization_id is None:
            self.organization = Organization.objects.order_by("id").first()
        super().save(*args, **kwargs)


class Ticket(models.Model):
    LOW, MEDIUM, HIGH, CRITICAL = "low", "medium", "high", "critical"
    PRIORITY_CHOICES = [(LOW, "Low"), (MEDIUM, "Medium"), (HIGH, "High"), (CRITICAL, "Critical")]
    PRIORITY_RANK = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

    PORTAL, PHONE, TEXT, WALKUP, EMAIL, OTHER = "portal", "phone", "text", "walkup", "email", "other"
    SOURCE_CHOICES = [
        (PORTAL, "Portal"),
        (PHONE, "Phone call"),
        (TEXT, "Text message"),
        (WALKUP, "Walk-up"),
        (EMAIL, "Email"),
        (OTHER, "Other"),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tickets")
    number = models.PositiveIntegerField()
    token = models.CharField(max_length=64, unique=True, default=new_ticket_token, editable=False)
    summary = models.CharField(max_length=200)
    description = models.TextField()
    board = models.ForeignKey(Board, on_delete=models.PROTECT, related_name="tickets")
    status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="tickets")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=MEDIUM)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets"
    )
    requester_name = models.CharField(max_length=120)
    requester_email = models.EmailField(blank=True)
    requester_phone = models.CharField(max_length=60, blank=True)
    location = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=PORTAL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="logged_tickets"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("organization", "number")]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "assignee"]),
            models.Index(fields=["organization", "board"]),
            models.Index(fields=["requester_email"]),
        ]

    def __str__(self):
        return f"#{self.number} {self.summary}"

    @property
    def is_open(self):
        return not self.status.is_done

    @property
    def priority_rank(self):
        return self.PRIORITY_RANK.get(self.priority, 2)


class Note(models.Model):
    DISCUSSION = "discussion"
    INTERNAL = "internal"
    RESOLUTION = "resolution"
    KIND_CHOICES = [
        (DISCUSSION, "Discussion"),
        (INTERNAL, "Internal"),
        (RESOLUTION, "Resolution"),
    ]
    VISIBLE_TO_REQUESTER = (DISCUSSION, RESOLUTION)

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="notes")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=DISCUSSION)
    body = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    author_name = models.CharField(max_length=120)
    from_requester = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_kind_display()} note on #{self.ticket.number}"

    @property
    def visible_to_requester(self):
        return self.kind in self.VISIBLE_TO_REQUESTER


def attachment_path(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"attachments/{instance.ticket.organization_id}/{instance.ticket.number}/{uuid.uuid4().hex}{ext}"


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    note = models.ForeignKey(Note, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments")
    file = models.FileField(upload_to=attachment_path)
    original_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=80)
    size = models.PositiveIntegerField()
    from_requester = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        return self.content_type.startswith("image/")

    @property
    def visible_to_requester(self):
        return self.note is None or self.note.visible_to_requester


class TicketEvent(models.Model):
    """The history: who changed what, and when."""

    CREATED = "created"
    CHANGED = "changed"
    NOTE = "note"
    REPLY = "reply"
    ATTACHMENT = "attachment"
    ACTION_CHOICES = [
        (CREATED, "Created"),
        (CHANGED, "Changed a field"),
        (NOTE, "Added a note"),
        (REPLY, "Employee replied"),
        (ATTACHMENT, "Added a file"),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actor_name = models.CharField(max_length=120)
    action = models.CharField(max_length=12, choices=ACTION_CHOICES)
    field = models.CharField(max_length=40, blank=True)
    old_value = models.CharField(max_length=200, blank=True)
    new_value = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.sentence

    @property
    def sentence(self):
        if self.action == self.CHANGED:
            if self.field == "assignee":
                if self.old_value and self.new_value:
                    return f"reassigned it from {self.old_value} to {self.new_value}"
                if self.new_value:
                    return f"assigned it to {self.new_value}"
                return f"unassigned {self.old_value}"
            if self.old_value and self.new_value:
                return f"changed {self.field} from {self.old_value} to {self.new_value}"
            if self.new_value:
                return f"set {self.field} to {self.new_value}"
            return f"cleared {self.field} (was {self.old_value})"
        if self.action == self.CREATED:
            return f"opened the ticket{(' — ' + self.detail) if self.detail else ''}"
        return self.detail or self.get_action_display().lower()


class Resource(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="resources")
    title = models.CharField(max_length=150)
    body = models.TextField(blank=True, help_text="Plain text. Line breaks are kept; web addresses become links.")
    link = models.URLField(blank=True, help_text="Optional. A page the article points to.")
    order = models.PositiveIntegerField(default=10)
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "how-to article"

    def __str__(self):
        return self.title
