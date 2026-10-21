from django.conf import settings


def site(request):
    org = getattr(request, "org", None)

    def sidebar_tickets():
        # Only runs when a portal page actually shows the sidebar list.
        from .views.portal import sidebar_tickets as load

        return load(request)

    return {
        "org": org,
        "email_enabled": settings.EMAIL_ENABLED,
        "max_attachment_mb": settings.MAX_ATTACHMENT_MB,
        "max_attachments": settings.MAX_ATTACHMENTS_PER_UPLOAD,
        "sidebar_tickets": sidebar_tickets,
    }
