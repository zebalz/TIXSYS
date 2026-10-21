from django.http import HttpResponse
from django.urls import include, path

from helpdesk.admin import settings_site


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("staff/settings/", settings_site.urls),
    path("staff/", include("helpdesk.urls_staff")),
    path("", include("helpdesk.urls_portal")),
]

handler404 = "helpdesk.views.errors.not_found"
handler500 = "helpdesk.views.errors.server_error"
handler403 = "helpdesk.views.errors.forbidden"
