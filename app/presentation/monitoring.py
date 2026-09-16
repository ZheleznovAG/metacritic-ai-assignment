"""Read-only OPS-01 endpoints; raw diagnostics and operator information are never public."""

from django.conf import settings
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from processing.monitoring import snapshot


def _enabled() -> None:
    if not settings.OPS_MONITORING_ENABLED:
        raise Http404


@require_safe
@never_cache
def index(request: HttpRequest) -> HttpResponse:
    _enabled()
    try:
        data = snapshot()
    except DatabaseError:
        data = None
    return render(
        request, "presentation/monitoring.html", {"snapshot": data}, status=200 if data else 503
    )


@require_safe
@never_cache
def status(request: HttpRequest) -> JsonResponse:
    _enabled()
    try:
        return JsonResponse(snapshot())
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
