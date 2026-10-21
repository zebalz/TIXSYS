from django.conf import settings


def site(request):
    org = getattr(request, "org", None)
    return {
        "org": org,
        "email_enabled": settings.EMAIL_ENABLED,
        "max_attachment_mb": settings.MAX_ATTACHMENT_MB,
        "max_attachments": settings.MAX_ATTACHMENTS_PER_UPLOAD,
    }
