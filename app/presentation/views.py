"""IMP-01 public scaffold: no ingestion, user accounts or AI endpoints."""

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@require_safe
@never_cache
def index(request: HttpRequest) -> HttpResponse:
    return render(request, "presentation/index.html", {"version": settings.APP_VERSION})


@require_safe
@never_cache
def live(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "version": settings.APP_VERSION})


@require_safe
@never_cache
def ready(request: HttpRequest) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise DatabaseError("Unexpected readiness result")
    except DatabaseError:
        # Do not include connection strings, hostnames or provider credentials.
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready", "version": settings.APP_VERSION})
