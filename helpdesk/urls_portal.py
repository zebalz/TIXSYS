from django.urls import path

from .views import portal

app_name = "portal"

urlpatterns = [
    path("", portal.home, name="home"),
    path("submit/", portal.submit, name="submit"),
    path("t/<str:token>/", portal.ticket, name="ticket"),
    path("t/<str:token>/received/", portal.received, name="received"),
    path("t/<str:token>/files/<int:attachment_id>/", portal.attachment, name="attachment"),
    path("my-tickets/", portal.my_tickets, name="my_tickets"),
    path("remote-help/", portal.remote_help, name="remote_help"),
    path("how-to/", portal.resources, name="resources"),
    path("how-to/<int:resource_id>/", portal.resource, name="resource"),
    path("brand/logo/", portal.logo, name="logo"),
]
