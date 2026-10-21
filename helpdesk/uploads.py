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
ACCEPT_ATTR = ".png,.jpg,.jpeg,.gif,.webp,.pdf,image/png,image/jpeg,image/gif,image/webp,application/pdf"


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
        try:
            from PIL import Image

            with Image.open(uploaded) as img:
                img.verify()
        except Exception:
            raise forms.ValidationError(f"{name} looks damaged and can't be opened as an image.")
        finally:
            uploaded.seek(0)
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
