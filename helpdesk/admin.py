"""Settings area for the administrator, at /staff/settings/.
Built on Django's admin, but signing in always goes through the staff sign-in
page (so the authenticator code is never skipped)."""

from urllib.parse import quote

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from . import security_log
from .models import Board, Category, Organization, Resource, SecurityEvent, Status, User


class SettingsSite(admin.AdminSite):
    site_header = "TIXSYS settings"
    site_title = "TIXSYS settings"
    index_title = "Settings"
    site_url = None  # the header has its own "Back to tickets" link
    enable_nav_sidebar = False

    def has_permission(self, request):
        user = request.user
        return user.is_active and user.is_authenticated and getattr(user, "role", None) == User.ADMIN

    def login(self, request, extra_context=None):
        target = request.GET.get("next") or "/staff/settings/"
        if not target.startswith("/staff/settings/"):
            target = "/staff/settings/"
        if request.user.is_authenticated:
            if self.has_permission(request):
                return redirect(target)
            raise PermissionDenied  # signed in, but not an administrator
        return redirect("/staff/login/?next=" + quote(target))

    def logout(self, request, extra_context=None):
        from django.contrib.auth import logout

        if request.method == "POST":
            logout(request)
            return redirect("/staff/login/")
        return redirect("/staff/settings/")


settings_site = SettingsSite(name="settings")


class OrgScopedAdmin(admin.ModelAdmin):
    """Sets the organization automatically; v1 has one."""

    exclude = ("organization",)

    def save_model(self, request, obj, form, change):
        if not obj.organization_id:
            obj.organization = request.org
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(organization=request.org)


@admin.register(Organization, site=settings_site)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "portal_title", "help_phone")
    fieldsets = (
        ("Name", {"fields": ("name", "portal_title")}),
        ("Look", {"fields": ("logo", "brand_color", "header_color")}),
        ("Portal text", {"fields": ("help_phone", "welcome_text", "remote_help_text")}),
        ("Spam protection", {"fields": ("allowed_email_domain",)}),
    )

    def has_add_permission(self, request):
        return not Organization.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Board, site=settings_site)
class BoardAdmin(OrgScopedAdmin):
    list_display = ("name", "description", "is_default", "is_active", "order")
    list_editable = ("order",)


@admin.register(Category, site=settings_site)
class CategoryAdmin(OrgScopedAdmin):
    list_display = ("name", "board", "show_on_portal", "is_active", "order")
    list_editable = ("order",)
    list_filter = ("board", "show_on_portal", "is_active")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "board":
            kwargs["queryset"] = Board.objects.filter(organization=request.org)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Status, site=settings_site)
class StatusAdmin(OrgScopedAdmin):
    list_display = ("name", "kind", "is_active", "order")
    list_editable = ("order",)

    def has_delete_permission(self, request, obj=None):
        # Statuses in use can't be deleted (tickets point at them); turn them off instead.
        return obj is None or not obj.tickets.exists()


@admin.register(Resource, site=settings_site)
class ResourceAdmin(OrgScopedAdmin):
    list_display = ("title", "is_published", "order", "updated_at")
    list_editable = ("order",)


class StaffCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role")


class StaffChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User, site=settings_site)
class StaffAdmin(UserAdmin):
    form = StaffChangeForm
    add_form = StaffCreationForm
    list_display = ("username", "display_name", "role", "email", "is_active", "two_step")
    list_filter = ("role", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("first_name", "last_name", "username")
    readonly_fields = ("last_login", "date_joined", "two_step")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Person", {"fields": ("first_name", "last_name", "email", "phone", "zoom_link")}),
        ("Access", {"fields": ("role", "specialty", "is_active", "email_alerts", "two_step")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "first_name", "last_name", "email", "role", "password1", "password2"),
            },
        ),
    )
    actions = ["turn_off_authenticator"]

    @admin.display(description="Authenticator app", boolean=True)
    def two_step(self, obj):
        return obj.totp_enabled

    @admin.action(description="Turn off the authenticator app (if someone lost their phone)")
    def turn_off_authenticator(self, request, queryset):
        updated = 0
        for user in queryset:
            user.totp_enabled = False
            user.totp_secret = ""  # erases the secret; not a password  # nosec B105
            user.totp_last_counter = 0
            user.save(update_fields=["totp_enabled", "totp_secret", "totp_last_counter"])
            security_log.record(
                request, SecurityEvent.AUTHENTICATOR_RESET, user=request.user, detail=f"for {user.username}"
            )
            updated += 1
        self.message_user(request, f"Turned off the authenticator app for {updated} account(s).")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(organization=request.org)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "specialty":
            kwargs["queryset"] = Board.objects.filter(organization=request.org)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not obj.organization_id:
            obj.organization = request.org
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        # Keep history intact: turn accounts off (Active) instead of deleting.
        return False


@admin.register(SecurityEvent, site=settings_site)
class SecurityEventAdmin(admin.ModelAdmin):
    """Read-only security log: sign-ins, failures, lockouts, authenticator changes, exports."""

    list_display = ("created_at", "kind", "username", "ip", "detail")
    list_filter = ("kind",)
    search_fields = ("username", "ip", "detail")
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(organization=request.org)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
