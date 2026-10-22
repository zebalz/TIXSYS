"""Staff sign-in: password, then an authenticator code if the account has one."""

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .. import security_log, throttle, totp
from ..forms import CodeForm, LoginForm, PasswordConfirmForm, ProfileForm
from ..middleware import authenticator_required
from ..models import SecurityEvent, User

PENDING_KEY = "tixsys_pending_2fa"
PENDING_SECONDS = 300
SETUP_KEY = "tixsys_totp_setup"


def _safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request, settings.LOGIN_REDIRECT_URL))
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        ip = throttle.client_ip(request)
        with throttle.sign_in_turn(username):
            try:
                throttle.check_sign_in_allowed(username, ip)
            except throttle.SignInBlocked as blocked:
                security_log.record(request, SecurityEvent.LOGIN_BLOCKED, username=username)
                form.add_error(None, blocked.message)
            else:
                user = authenticate(request, username=username, password=form.cleaned_data["password"])
                if user is None:
                    throttle.record_failure(username, ip)
                    security_log.record(request, SecurityEvent.LOGIN_FAILED, username=username)
                    form.add_error(None, "That username and password don't match. Check them and try again.")
                elif user.totp_enabled:
                    request.session.cycle_key()
                    request.session[PENDING_KEY] = {
                        "user": user.pk,
                        "username": user.username,
                        "backend": user.backend,
                        "at": time.time(),
                        "next": _safe_next(request, settings.LOGIN_REDIRECT_URL),
                    }
                    return redirect("staff:login_code")
                else:
                    throttle.record_success(username)
                    login(request, user)
                    security_log.record(request, SecurityEvent.LOGIN_OK, user=user, detail="password")
                    return redirect(_safe_next(request, settings.LOGIN_REDIRECT_URL))
    return render(request, "staff/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_http_methods(["GET", "POST"])
def login_code_view(request):
    pending = request.session.get(PENDING_KEY)
    if not pending or time.time() - pending["at"] > PENDING_SECONDS:
        request.session.pop(PENDING_KEY, None)
        messages.info(request, "Sign in again to get a new code prompt.")
        return redirect("staff:login")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ip = throttle.client_ip(request)
        username = pending["username"]
        with throttle.sign_in_turn(username):
            try:
                throttle.check_sign_in_allowed(username, ip)
            except throttle.SignInBlocked as blocked:
                security_log.record(request, SecurityEvent.LOGIN_BLOCKED, username=username)
                form.add_error(None, blocked.message)
            else:
                user = User.objects.filter(pk=pending["user"], is_active=True).first()
                if user and totp.verify_for_user(user, form.cleaned_data["code"]):
                    throttle.record_success(username)
                    request.session.pop(PENDING_KEY, None)
                    login(request, user, backend=pending["backend"])
                    security_log.record(
                        request, SecurityEvent.LOGIN_OK, user=user, detail="password and authenticator code"
                    )
                    return redirect(pending.get("next") or settings.LOGIN_REDIRECT_URL)
                throttle.record_failure(username, ip)
                security_log.record(request, SecurityEvent.CODE_FAILED, user=user, username=username)
                form.add_error("code", "That code didn't work. Codes change every 30 seconds; enter the current one.")
    return render(request, "staff/login_code.html", {"form": form})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        security_log.record(request, SecurityEvent.LOGOUT, user=request.user)
    logout(request)
    return redirect("staff:login")


@login_required
@require_http_methods(["GET", "POST"])
def account(request):
    user = request.user
    form = ProfileForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("staff:account")
    required = authenticator_required(user) and not user.totp_enabled
    return render(request, "staff/account.html", {"form": form, "nav": "account", "authenticator_required": required})


@login_required
@require_http_methods(["GET", "POST"])
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        security_log.record(request, SecurityEvent.PASSWORD_CHANGED, user=user)
        messages.success(request, "Password changed.")
        return redirect("staff:account")
    return render(request, "staff/password.html", {"form": form, "nav": "account"})


@login_required
@require_http_methods(["GET", "POST"])
def authenticator(request):
    user = request.user
    required = authenticator_required(user)
    if user.totp_enabled:
        form = PasswordConfirmForm(request.POST or None)
        if required:
            return render(request, "staff/authenticator_on.html", {"form": form, "nav": "account", "required": True})
        if request.method == "POST" and form.is_valid():
            if user.check_password(form.cleaned_data["password"]):
                user.totp_enabled = False
                user.totp_secret = ""  # erases the secret; not a password  # nosec B105
                user.totp_last_counter = 0
                user.save(update_fields=["totp_enabled", "totp_secret", "totp_last_counter"])
                security_log.record(request, SecurityEvent.AUTHENTICATOR_OFF, user=user)
                messages.success(request, "Authenticator app turned off. You'll sign in with your password only.")
                return redirect("staff:account")
            form.add_error("password", "That password isn't right.")
        return render(request, "staff/authenticator_on.html", {"form": form, "nav": "account"})

    secret = request.session.get(SETUP_KEY)
    if not secret or (request.method == "GET" and request.GET.get("new")):
        secret = totp.new_secret()
        request.session[SETUP_KEY] = secret
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        counter = totp.matching_counter(secret, form.cleaned_data["code"])
        if counter is not None:
            user.totp_secret = secret
            user.totp_enabled = True
            user.totp_last_counter = counter
            user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_counter"])
            request.session.pop(SETUP_KEY, None)
            security_log.record(request, SecurityEvent.AUTHENTICATOR_ON, user=user)
            messages.success(request, "Authenticator app is on. You'll enter a code each time you sign in.")
            return redirect("staff:tickets" if required else "staff:account")
        form.add_error(
            "code", "That code didn't match. Make sure you scanned this page's code, then enter the current number."
        )
    issuer = f"{request.org.name} help desk"
    uri = totp.provisioning_uri(secret, user.username, issuer)
    spaced = " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))
    return render(
        request,
        "staff/authenticator_setup.html",
        {"form": form, "qr": totp.qr_svg(uri), "secret": spaced, "nav": "account", "required": required},
    )
