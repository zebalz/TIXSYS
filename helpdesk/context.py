from django.conf import settings


def site(request):
    org = getattr(request, "org", None)

    def sidebar_tickets():
        # Only runs when a portal page actually shows the sidebar list.
        from .views.portal import sidebar_tickets as load

        return load(request)

    def saved_searches():
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return []
        return list(user.saved_searches.all()[:20])

    def brand_version():
        # Changes whenever the colors change, so browsers fetch the new brand.css.
        import hashlib

        if not org:
            return "0"
        return hashlib.sha256(f"{org.brand_color}{org.header_color}".encode()).hexdigest()[:10]

    return {
        "org": org,
        "brand_version": brand_version,
        "saved_searches": saved_searches,
        "email_enabled": settings.EMAIL_ENABLED,
        "max_attachment_mb": settings.MAX_ATTACHMENT_MB,
        "max_attachments": settings.MAX_ATTACHMENTS_PER_UPLOAD,
        "sidebar_tickets": sidebar_tickets,
    }
