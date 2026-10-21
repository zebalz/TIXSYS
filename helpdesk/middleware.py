from django.utils.functional import SimpleLazyObject

from .models import Organization

CSP = "; ".join(
    [
        "default-src 'self'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


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


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.path.startswith("/staff/") or request.path.startswith("/t/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
