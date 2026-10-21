import time

from django import forms
from django.conf import settings
from django.core import signing

from .models import Board, Category, Note, Status, Ticket, User
from .uploads import AttachmentsField

FORM_STAMP_SALT = "tixsys.portal.form-stamp"


def form_stamp():
    return signing.dumps(time.time(), salt=FORM_STAMP_SALT)


def stamp_age(value):
    try:
        return time.time() - float(signing.loads(value, salt=FORM_STAMP_SALT, max_age=60 * 60 * 24))
    except (signing.BadSignature, TypeError, ValueError):
        return None


class SpamCheckMixin(forms.Form):
    """A field people never see (bots fill it) plus a signed time stamp
    (bots submit faster than any person can type)."""

    leave_blank = forms.CharField(required=False, label="Leave this empty", widget=forms.TextInput(
        attrs={"autocomplete": "off", "tabindex": "-1"}
    ))
    stamp = forms.CharField(required=False, widget=forms.HiddenInput)

    def looks_like_spam(self):
        if self.data.get("leave_blank"):
            return True
        age = stamp_age(self.data.get("stamp", ""))
        return age is None or age < settings.PORTAL_MIN_FORM_SECONDS


class SubmitTicketForm(SpamCheckMixin):
    name = forms.CharField(label="Your name", max_length=120, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(
        label="Phone or extension",
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
    )
    location = forms.CharField(
        label="Where you are",
        max_length=120,
        required=False,
        help_text="Building, floor or room, so a tech can find you.",
    )
    category = forms.ModelChoiceField(
        label="What is it about?", queryset=Category.objects.none(), empty_label="Choose one", required=True
    )
    description = forms.CharField(
        label="What's going on?",
        max_length=8000,
        widget=forms.Textarea(attrs={"rows": 7}),
        help_text="What you were doing, what happened, and any error message you saw.",
    )
    files = AttachmentsField(label="Screenshots")

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.org = org
        self.fields["category"].queryset = Category.objects.filter(
            organization=org, is_active=True, show_on_portal=True
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        domains = self.org.allowed_domains() if self.org else []
        if domains and email.rsplit("@", 1)[-1] not in domains:
            allowed = " or ".join("@" + d for d in domains)
            raise forms.ValidationError(f"Use your work email address (ending in {allowed}).")
        return email


class ReplyForm(SpamCheckMixin):
    body = forms.CharField(label="Your reply", max_length=8000, widget=forms.Textarea(attrs={"rows": 4}))
    files = AttachmentsField(label="Add screenshots")


class EmailLinksForm(SpamCheckMixin):
    email = forms.EmailField(label="Your email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))


# --- Staff -------------------------------------------------------------------


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Username", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True})
    )
    password = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class CodeForm(forms.Form):
    code = forms.CharField(
        label="6-digit code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "pattern": "[0-9]{6}", "autofocus": True}
        ),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip().replace(" ", "")
        if not code.isdigit():
            raise forms.ValidationError("Enter the 6 numbers from your authenticator app.")
        return code


def staff_queryset(org):
    return User.objects.filter(organization=org, is_active=True).order_by("first_name", "last_name", "username")


class StaffChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name


class LogCallForm(forms.Form):
    source = forms.ChoiceField(
        label="How they reached you",
        choices=[c for c in Ticket.SOURCE_CHOICES if c[0] != Ticket.PORTAL],
        initial=Ticket.PHONE,
    )
    requester_name = forms.CharField(label="Their name", max_length=120)
    requester_phone = forms.CharField(label="Phone or extension", max_length=60, required=False)
    requester_email = forms.EmailField(label="Email", required=False, help_text="If you have it, they get updates.")
    location = forms.CharField(label="Location", max_length=120, required=False)
    board = forms.ModelChoiceField(label="Board", queryset=Board.objects.none(), empty_label=None)
    category = forms.ModelChoiceField(label="Category", queryset=Category.objects.none(), required=False)
    priority = forms.ChoiceField(label="Priority", choices=Ticket.PRIORITY_CHOICES, initial=Ticket.MEDIUM)
    description = forms.CharField(
        label="What they need",
        max_length=8000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="The first line becomes the ticket summary.",
    )
    assign_to_me = forms.BooleanField(label="Assign it to me", required=False, initial=True)
    files = AttachmentsField(label="Files")

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["board"].queryset = Board.objects.filter(organization=org, is_active=True)
        self.fields["category"].queryset = Category.objects.filter(organization=org, is_active=True)
        default = org.default_board() if org else None
        if default:
            self.fields["board"].initial = default.pk


class TicketUpdateForm(forms.ModelForm):
    assignee = StaffChoiceField(queryset=User.objects.none(), required=False, empty_label="Unassigned")

    class Meta:
        model = Ticket
        fields = ["summary", "board", "status", "priority", "category", "assignee"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = self.instance.organization
        self.fields["board"].queryset = Board.objects.filter(organization=org).filter(
            is_active=True
        ) | Board.objects.filter(pk=self.instance.board_id)
        self.fields["status"].queryset = Status.objects.filter(organization=org, is_active=True) | Status.objects.filter(
            pk=self.instance.status_id
        )
        self.fields["category"].queryset = Category.objects.filter(organization=org, is_active=True)
        self.fields["category"].empty_label = "None"
        self.fields["assignee"].queryset = staff_queryset(org)
        self.fields["board"].empty_label = None
        self.fields["status"].empty_label = None


class NoteForm(forms.Form):
    kind = forms.ChoiceField(
        label="Note type",
        choices=[
            (Note.DISCUSSION, "Discussion — the employee sees it"),
            (Note.INTERNAL, "Internal — staff only"),
            (Note.RESOLUTION, "Resolution — the employee sees it, and the ticket is resolved"),
        ],
        initial=Note.DISCUSSION,
        widget=forms.RadioSelect,
    )
    body = forms.CharField(label="Note", max_length=8000, widget=forms.Textarea(attrs={"rows": 5}))
    mark_waiting = forms.BooleanField(label="Set status to waiting on employee", required=False)
    files = AttachmentsField(label="Files")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "zoom_link", "email_alerts"]
        labels = {"first_name": "First name", "last_name": "Last name"}


class PasswordConfirmForm(forms.Form):
    password = forms.CharField(label="Your password", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
