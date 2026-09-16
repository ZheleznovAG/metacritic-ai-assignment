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


RUN_ERRORS = {
    "invalid_request": "That request could not be understood.",
    "forbidden": "Sign in with an account that can trigger runs.",
    "busy": "Another run is already in progress.",
    "rate_limited": "Too many manual runs recently; try again soon.",
}


@require_safe
@never_cache
def index(request: HttpRequest) -> HttpResponse:
    _enabled()
    try:
        data = snapshot()
    except DatabaseError:
        data = None
    context = {
        "snapshot": data,
        "manual_run_enabled": settings.OPS_MANUAL_RUN_ENABLED,
        "can_trigger_run": request.user.is_authenticated
        and request.user.has_perm("processing.trigger_run"),
        "run_request_id": request.GET.get("request", ""),
        "run_error": RUN_ERRORS.get(request.GET.get("run_error", "")),
    }
    return render(request, "presentation/monitoring.html", context, status=200 if data else 503)


@require_safe
@never_cache
def status(request: HttpRequest) -> JsonResponse:
    _enabled()
    try:
        return JsonResponse(snapshot())
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
