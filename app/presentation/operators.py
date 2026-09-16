"""BON-22: operator authentication and the manual-run trigger (`docs/bonus2_design.md`).
Plain function views, matching `presentation.views`' style; `django.contrib.auth` handles
accounts/permissions/sessions, this module only adds the login throttle and admission wiring.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST
from processing import admission
from processing.admission import AdmissionConflict
from processing.clock import SystemClock
from processing.models import LoginFailure


def client_ip(request: HttpRequest) -> str:
    """Only Caddy can reach `web` on the internal network (ADR-0001's isolated backend
    network); its `reverse_proxy` appends the true connecting address as the *last* entry of
    `X-Forwarded-For` rather than trusting a client-supplied one, so only that last hop is ever
    read here -- an arbitrary header value a client sends itself is never authoritative.
    """
    forwarded: str = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return str(forwarded.rsplit(",", 1)[-1].strip())
    return str(request.META.get("REMOTE_ADDR", "unknown"))


def _throttled(fingerprint: str) -> bool:
    window_start = SystemClock().now_utc() - timedelta(
        seconds=settings.LOGIN_THROTTLE_WINDOW_SECONDS
    )
    count = LoginFailure.objects.filter(
        fingerprint=fingerprint, created_at__gte=window_start
    ).count()
    return count >= settings.LOGIN_THROTTLE_MAX_ATTEMPTS


def _wants_json(request: HttpRequest) -> bool:
    return "application/json" in request.headers.get("Accept", "")


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    return JsonResponse({"error": "forbidden"}, status=403)


@require_http_methods(["GET", "POST"])
@never_cache
@csrf_protect
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("monitoring")
    error = None
    if request.method == "POST":
        # One generic message for every rejection reason (design: no hint of which factor
        # blocked the attempt); only a *genuine* credential check that actually ran records a
        # failure, so hammering an already-throttled key cannot itself grow this table further.
        error = "Invalid username or password."
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if username and password:
            user_key = f"user:{username.lower()}"
            ip_key = f"ip:{client_ip(request)}"
            if not _throttled(user_key) and not _throttled(ip_key):
                user = authenticate(request, username=username, password=password)
                if user is not None and user.is_active:
                    login(request, user)
                    return redirect("monitoring")
                LoginFailure.objects.bulk_create(
                    [LoginFailure(fingerprint=user_key), LoginFailure(fingerprint=ip_key)]
                )
    return render(request, "presentation/login.html", {"error": error})


@require_POST
@never_cache
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("monitoring")


@require_POST
@never_cache
def run_view(request: HttpRequest) -> HttpResponse:
    if not settings.OPS_MANUAL_RUN_ENABLED:
        raise Http404
    # Anonymous/no-permission always gets JSON 403, matching CSRF failures -- never a login
    # redirect, which would silently swallow "no external calls happened" for a script client.
    if not request.user.is_authenticated or not request.user.has_perm("processing.trigger_run"):
        return JsonResponse({"error": "forbidden"}, status=403)

    def error(
        request: HttpRequest, code: str, status: int, retry_after: int | None = None
    ) -> HttpResponse:
        response: HttpResponse
        if _wants_json(request):
            response = JsonResponse({"error": code}, status=status)
        else:
            response = redirect(f"{reverse('monitoring')}?run_error={code}")
        if retry_after is not None:
            response["Retry-After"] = str(retry_after)
        return response

    raw_key = request.POST.get("request_id", "")
    try:
        request_id = uuid.UUID(raw_key)
    except (ValueError, AttributeError, TypeError):
        return error(request, "invalid_request", 400)

    try:
        result = admission.admit(request.user, request_id, SystemClock())
    except AdmissionConflict:
        return error(request, "invalid_request", 400)

    if result.outcome == "busy":
        return error(request, "busy", 409)
    if result.outcome == "rate_limited":
        return error(request, "rate_limited", 429, retry_after=result.retry_after_seconds)

    request_record = result.request
    if request_record is None:  # only "busy"/"rate_limited" (handled above) ever omit it
        return error(request, "invalid_request", 400)
    if _wants_json(request):
        return JsonResponse(
            {"request_id": str(request_record.request_id), "state": request_record.state},
            status=202 if result.outcome == "accepted" else 200,
        )
    return redirect(f"{reverse('monitoring')}?request={request_record.request_id}")


@never_cache
def run_status_view(request: HttpRequest, request_id: uuid.UUID) -> JsonResponse:
    if not settings.OPS_MANUAL_RUN_ENABLED:
        raise Http404
    if not request.user.is_authenticated:
        return JsonResponse({"error": "forbidden"}, status=403)
    found = admission.lookup(request_id, request.user)
    if found is None:
        return JsonResponse({"error": "not_found"}, status=404)
    return JsonResponse(
        {
            "request_id": str(found.request_id),
            "state": found.state,
            "run_id": found.run_id,
            "reason_code": found.reason_code,
        }
    )
