from django.urls import path, register_converter

from .safe import NumberConverter, TokenConverter
from .views import portal

register_converter(TokenConverter, "token")
register_converter(NumberConverter, "num")

app_name = "portal"

urlpatterns = [
    path("", portal.home, name="home"),
    path("submit/", portal.submit, name="submit"),
    path("t/<token:token>/", portal.ticket, name="ticket"),
    path("t/<token:token>/received/", portal.received, name="received"),
    path("t/<token:token>/files/<num:attachment_id>/", portal.attachment, name="attachment"),
    path("my-tickets/", portal.my_tickets, name="my_tickets"),
    path("remote-help/", portal.remote_help, name="remote_help"),
    path("how-to/", portal.resources, name="resources"),
    path("how-to/<num:resource_id>/", portal.resource, name="resource"),
    path("brand/logo/", portal.logo, name="logo"),
    path("brand.css", portal.brand_css, name="brand_css"),
]
