from django.urls import path, register_converter

from .safe import NumberConverter
from .views import auth, staff

register_converter(NumberConverter, "num")

app_name = "staff"

urlpatterns = [
    path("login/", auth.login_view, name="login"),
    path("login/code/", auth.login_code_view, name="login_code"),
    path("logout/", auth.logout_view, name="logout"),
    path("account/", auth.account, name="account"),
    path("account/password/", auth.change_password, name="password"),
    path("account/authenticator/", auth.authenticator, name="authenticator"),
    path("", staff.ticket_list, name="tickets"),
    path("new/", staff.log_call, name="log_call"),
    path("tickets/<num:number>/", staff.ticket_detail, name="ticket"),
    path("tickets/<num:number>/update/", staff.ticket_update, name="ticket_update"),
    path("tickets/<num:number>/take/", staff.ticket_take, name="ticket_take"),
    path("tickets/<num:number>/note/", staff.ticket_note, name="ticket_note"),
    path("files/<num:attachment_id>/", staff.attachment, name="attachment"),
    path("reports/", staff.reports, name="reports"),
    path("api/poll/", staff.poll, name="poll"),
    path("export.txt", staff.export_text, name="export_text"),
    path("searches/save/", staff.save_search, name="save_search"),
    path("searches/<num:search_id>/delete/", staff.delete_search, name="delete_search"),
    path("tickets/<num:number>/reset-link/", staff.reset_link, name="reset_link"),
]
