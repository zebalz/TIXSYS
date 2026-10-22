"""Attachment checks: images and PDFs only, with a size cap.
The file's first bytes decide its type, not its name."""

from pathlib import Path

from django import forms
from django.conf import settings

SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
]
EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/gif": {".gif"},
    "image/webp": {".webp"},
    "application/pdf": {".pdf"},
}
MAX_PIXELS = 40_000_000  # about 8000 x 5000; bigger than any real screenshot
ACCEPT_ATTR = ".png,.jpg,.jpeg,.gif,.webp,.pdf,image/png,image/jpeg,image/gif,image/webp,application/pdf"
LOGO_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def detected_type(uploaded):
    uploaded.seek(0)
    head = uploaded.read(16)
    uploaded.seek(0)
    for signature, content_type in SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def check_file(uploaded):
    limit = settings.MAX_ATTACHMENT_MB * 1024 * 1024
    name = uploaded.name or "file"
    if uploaded.size > limit:
        raise forms.ValidationError(f"{name} is larger than {settings.MAX_ATTACHMENT_MB} MB.")
    content_type = detected_type(uploaded)
    if content_type is None:
        raise forms.ValidationError(f"{name} isn't an image or PDF. Attach PNG, JPG, GIF, WEBP or PDF files.")
    if Path(name).suffix.lower() not in EXTENSIONS[content_type]:
        raise forms.ValidationError(f"{name} has the wrong file extension for its contents.")
    if content_type.startswith("image/"):
        import warnings

        from PIL import Image

        try:
            with warnings.catch_warnings():
                # A huge image hidden in a small file ("decompression bomb") is refused.
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(uploaded) as img:
                    if img.width * img.height > MAX_PIXELS:
                        raise ValueError("too many pixels")
                    img.verify()
        except Exception:  # noqa: BLE001 - any failure to read it means it isn't a usable image
            raise forms.ValidationError(f"{name} looks damaged or too large and can't be used as an image.") from None
        finally:
            uploaded.seek(0)
    return uploaded


def check_logo(uploaded):
    """The portal logo: the same checks as attachments, and it must be a picture."""
    check_file(uploaded)
    if detected_type(uploaded) not in LOGO_TYPES:
        raise forms.ValidationError("Use a PNG, JPG, GIF or WEBP picture for the logo.")
    return uploaded


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class AttachmentsField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "widget", MultipleFileInput(attrs={"accept": ACCEPT_ATTR, "multiple": True, "class": "file-input"})
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        files = [f for f in files if f]
        if len(files) > settings.MAX_ATTACHMENTS_PER_UPLOAD:
            raise forms.ValidationError(f"Attach up to {settings.MAX_ATTACHMENTS_PER_UPLOAD} files at a time.")
        errors = []
        for f in files:
            try:
                check_file(f)
            except forms.ValidationError as e:
                errors.extend(e.messages)
        if errors:
            raise forms.ValidationError(errors)
        return files
