"""IMP-01 public scaffold, extended by IMP-05 with a stateless search/filter/sort list: no
ingestion, user accounts, AI endpoints, or server-side session — the list's state lives entirely
in the URL's `q`/`platform` query params, which is also how a detail page can link back to the
exact list a visitor came from (`AC-UI-06`) without any new persisted state.
"""

from urllib.parse import urlencode

from catalog.models import Game
from catalog.queries import get_game_detail, list_games, list_platform_options, list_similar_games
from django.conf import settings
from django.db import DatabaseError, connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from presentation.summaries import get_summaries


def _list_params(request: HttpRequest) -> dict[str, str]:
    params: dict[str, str] = {}
    query = request.GET.get("q", "").strip()
    if query:
        params["q"] = query
    platform = request.GET.get("platform", "").strip()
    if platform:
        params["platform"] = platform
    return params


@require_safe
@never_cache
def index(request: HttpRequest) -> HttpResponse:
    params = _list_params(request)
    query = params.get("q", "")
    platform = params.get("platform")
    context = {
        "version": settings.APP_VERSION,
        "games": list_games(query=query, platform=platform),
        "platforms": list_platform_options(),
        "query": query,
        "selected_platform": platform or "",
        "query_string": urlencode(params),
        "monitoring_enabled": settings.OPS_MONITORING_ENABLED,
    }
    return render(request, "presentation/index.html", context)


@require_safe
@never_cache
def game_detail(request: HttpRequest, game_id: int) -> HttpResponse:
    detail = get_game_detail(game_id)
    if detail is None:
        raise Http404("Game not found")
    summaries = get_summaries(Game.objects.get(pk=game_id))
    context = {
        "game": detail,
        "summaries": summaries,
        "similar_games": list_similar_games(game_id),
        "back_query_string": urlencode(_list_params(request)),
        "monitoring_enabled": settings.OPS_MONITORING_ENABLED,
    }
    return render(request, "presentation/game_detail.html", context)


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
