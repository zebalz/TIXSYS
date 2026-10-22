from django.conf import settings
from django.shortcuts import redirect
from django.utils.functional import SimpleLazyObject

from .models import Organization, User

# The browser security policy. Pages may only load scripts, styles, fonts and
# images from this server; inline scripts and inline styles are refused, so
# injected markup can't run code or restyle the page.
CSP = "; ".join(  # noqa: FLY002 - one directive per line is easier to review
    [
        "default-src 'self'",
        "img-src 'self' data:",
        "style-src 'self'",
        "script-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)
# The settings area is Django's built-in admin, which uses some inline styles.
# It's only open to administrators, after sign-in and the authenticator code.
CSP_SETTINGS = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")


def current_organization():
    org = Organization.objects.order_by("id").first()
    if org is None:
        from .bootstrap import ensure_defaults

        org = ensure_defaults()
    return org


class CurrentOrganizationMiddleware:
    """v1 serves one organization. Every query is still filtered by it,
    so serving several later only changes how this is chosen."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "organization_id", None):
            request.org = SimpleLazyObject(lambda: user.organization)
        else:
            request.org = SimpleLazyObject(current_organization)
        return self.get_response(request)


def authenticator_required(user):
    rule = settings.REQUIRE_AUTHENTICATOR_FOR
    if rule == "all":
        return True
    if rule == "supervisors":
        return user.role in (User.SUPERVISOR, User.ADMIN)
    if rule == "admin":
        return user.role == User.ADMIN
    return False


class RequireAuthenticatorMiddleware:
    """Staff whose role needs an authenticator app can't use anything else until it's set up."""

    ALLOWED_PREFIXES = ("/staff/account/authenticator/", "/staff/logout/", "/static/", "/brand", "/healthz")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.totp_enabled
            and request.path.startswith("/staff/")
            and not request.path.startswith(self.ALLOWED_PREFIXES)
            and authenticator_required(user)
        ):
            return redirect("/staff/account/authenticator/?required=1")
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        policy = CSP_SETTINGS if request.path.startswith("/staff/settings/") else CSP
        response.headers.setdefault("Content-Security-Policy", policy)
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request.path.startswith("/staff/") or request.path.startswith("/t/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
