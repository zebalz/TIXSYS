from django.shortcuts import render


def not_found(request, exception=None):
    return render(
        request,
        "error.html",
        {
            "title": "Page not found",
            "message": "This page doesn't exist, or the link is incomplete. Check the link and try again.",
        },
        status=404,
    )


def forbidden(request, exception=None):
    return render(
        request,
        "error.html",
        {
            "title": "Not allowed",
            "message": "Your account can't open this page. Ask the administrator if you need access.",
        },
        status=403,
    )


def server_error(request):
    return render(
        request,
        "error.html",
        {
            "title": "Something went wrong",
            "message": "The help desk hit an error. Try again in a minute. If it keeps happening, call the help desk.",
        },
        status=500,
    )
