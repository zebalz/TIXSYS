"""The employee portal. No account needed."""

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .. import services, throttle
from ..forms import EmailLinksForm, ReplyForm, SubmitTicketForm, form_stamp
from ..models import Attachment, Note, Resource, Ticket, User

MINE_COOKIE = "tixsys_mine"
MINE_SALT = "tixsys.portal.mine"
MINE_LIMIT = 40


def _mine_tokens(request):
    try:
        raw = request.get_signed_cookie(MINE_COOKIE, default="", salt=MINE_SALT)
    except signing.BadSignature:
        return []
    return [t for t in raw.split(",") if t]


def _remember(response, request, token):
    tokens = [t for t in _mine_tokens(request) if t != token]
    tokens.insert(0, token)
    response.set_signed_cookie(
        MINE_COOKIE,
        ",".join(tokens[:MINE_LIMIT]),
        salt=MINE_SALT,
        max_age=60 * 60 * 24 * 730,
        httponly=True,
        samesite="Lax",
        secure=settings.COOKIES_SECURE,
    )
    return response


def sidebar_tickets(request):
    """The tickets this browser has sent or opened, newest first (for the portal sidebar)."""
    tokens = _mine_tokens(request)
    current = getattr(request, "portal_current_token", None)
    if current and current not in tokens:
        tokens.insert(0, current)  # opened from a link for the first time
    if not tokens:
        return []
    found = {
        t.token: t for t in Ticket.objects.filter(organization=request.org, token__in=tokens).select_related("status")
    }
    return [found[t] for t in tokens if t in found]


def _home(request, form, status=200):
    return render(request, "portal/home.html", {"form": form, "stamp": form_stamp(), "page": "new"}, status=status)


def home(request):
    return _home(request, SubmitTicketForm(org=request.org))


@require_http_methods(["GET", "POST"])
def submit(request):
    org = request.org
    if request.method == "GET":
        return redirect("portal:home")
    if request.method == "POST":
        form = SubmitTicketForm(request.POST, request.FILES, org=org)
        if form.looks_like_spam():
            return render(request, "portal/spam.html", status=200)
        ip = throttle.client_ip(request)
        if throttle.over_limit(f"portal-submit:ip:{ip}", settings.PORTAL_TICKETS_PER_IP_PER_HOUR, 3600):
            form.add_error(
                None,
                "Too many tickets were sent from this network in the last hour. Try again later, or call the help desk.",
            )
        elif form.is_valid():
            data = form.cleaned_data
            if throttle.over_limit(
                f"portal-submit:email:{data['email']}", settings.PORTAL_TICKETS_PER_EMAIL_PER_HOUR, 3600
            ):
                form.add_error(
                    None, "You've sent a lot of tickets in the last hour. Try again later, or call the help desk."
                )
            else:
                ticket = services.create_ticket(
                    org,
                    requester_name=data["name"],
                    requester_email=data["email"],
                    requester_phone=data["phone"],
                    location=data["location"],
                    category=data["category"],
                    description=data["description"],
                    files=data["files"],
                )
                response = redirect("portal:received", token=ticket.token)
                return _remember(response, request, ticket.token)
    return _home(request, form)


def _ticket_for_token(request, token):
    return get_object_or_404(
        Ticket.objects.select_related("status", "board", "category", "assignee"),
        token=token,
        organization=request.org,
    )


def received(request, token):
    ticket = _ticket_for_token(request, token)
    request.portal_current_token = ticket.token
    link = request.build_absolute_uri(reverse("portal:ticket", args=[ticket.token]))
    return render(request, "portal/received.html", {"ticket": ticket, "link": link, "current_ticket": ticket})


@require_http_methods(["GET", "POST"])
def ticket(request, token):
    ticket = _ticket_for_token(request, token)
    request.portal_current_token = ticket.token
    closed = ticket.status.kind == "closed"
    if request.method == "POST":
        form = ReplyForm(request.POST, request.FILES)
        if form.looks_like_spam():
            return redirect("portal:ticket", token=token)
        ip = throttle.client_ip(request)
        if closed:
            form.add_error(None, "This ticket is closed. Submit a new ticket if you still need help.")
        elif throttle.over_limit(f"portal-reply:ip:{ip}", settings.PORTAL_REPLIES_PER_IP_PER_HOUR, 3600):
            form.add_error(None, "Too many replies from this network in the last hour. Try again later.")
        elif form.is_valid():
            services.add_requester_reply(ticket, form.cleaned_data["body"], form.cleaned_data["files"])
            messages.success(request, "Reply sent. The help desk has been told.")
            return redirect(reverse("portal:ticket", args=[token]) + "#latest")
    else:
        form = ReplyForm()

    notes = list(
        ticket.notes.filter(kind__in=Note.VISIBLE_TO_REQUESTER).prefetch_related("attachments").select_related("author")
    )
    loose_files = list(ticket.attachments.filter(note__isnull=True))
    resolution = next((n for n in reversed(notes) if n.kind == Note.RESOLUTION), None)
    response = render(
        request,
        "portal/ticket.html",
        {
            "ticket": ticket,
            "notes": notes,
            "loose_files": loose_files,
            "resolution": resolution if ticket.status.is_done else None,
            "form": form,
            "stamp": form_stamp(),
            "closed": closed,
            "current_ticket": ticket,
        },
    )
    return _remember(response, request, ticket.token)


def attachment(request, token, attachment_id):
    ticket = _ticket_for_token(request, token)
    att = get_object_or_404(Attachment.objects.select_related("note"), pk=attachment_id, ticket=ticket)
    if not att.visible_to_requester:
        raise Http404
    return file_response(att)


def file_response(att):
    try:
        handle = att.file.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    as_download = not att.is_image
    response = FileResponse(
        handle, content_type=att.content_type, as_attachment=as_download, filename=att.original_name
    )
    # Shown on its own, with nothing allowed to run: even a disguised file can't execute anything.
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET", "POST"])
def my_tickets(request):
    org = request.org
    tickets = sidebar_tickets(request)

    sent = False
    form = EmailLinksForm()
    if request.method == "POST" and settings.EMAIL_ENABLED:
        form = EmailLinksForm(request.POST)
        ip = throttle.client_ip(request)
        if form.looks_like_spam():
            sent = True
        elif throttle.over_limit(f"portal-links:ip:{ip}", 20, 3600):
            form.add_error(None, "Too many requests from this network. Try again in an hour.")
        elif form.is_valid():
            email = form.cleaned_data["email"].strip().lower()
            if not throttle.over_limit(f"portal-links:email:{email}", 3, 3600):
                services.send_ticket_links(org, email)
            # Same answer either way, so no one can test which addresses have tickets.
            sent = True
    return render(
        request,
        "portal/my_tickets.html",
        {"tickets": tickets, "form": form, "sent": sent, "stamp": form_stamp(), "page": "mine"},
    )


def remote_help(request):
    techs = User.objects.filter(organization=request.org, is_active=True).exclude(zoom_link="")
    return render(request, "portal/remote_help.html", {"techs": techs, "page": "remote"})


def resources(request):
    items = Resource.objects.filter(organization=request.org, is_published=True)
    return render(request, "portal/resources.html", {"resources": items, "page": "howto"})


def resource(request, resource_id):
    item = get_object_or_404(Resource, pk=resource_id, organization=request.org, is_published=True)
    return render(request, "portal/resource.html", {"resource": item, "page": "howto"})


def logo(request):
    org = request.org
    if not org.logo:
        raise Http404
    try:
        handle = org.logo.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    response = FileResponse(handle)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


def brand_css(request):
    """The organization's colors as CSS variables. A separate file (not inline styles)
    lets the browser security policy block every inline style."""
    import re

    from django.http import HttpResponse

    from ..templatetags.desk import readable_on

    def safe(value, fallback):
        # Only plain #RRGGBB colors reach the stylesheet.
        return value if re.fullmatch(r"#[0-9A-Fa-f]{6}", value or "") else fallback

    org = request.org
    brand = safe(org.brand_color, "#26232F")
    accent = safe(org.header_color, "#CFC6FF")
    css = f":root{{--brand:{brand};--brand-ink:{readable_on(brand)};--accent:{accent};}}\n"
    response = HttpResponse(css, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "public, max-age=86400"
    return response
