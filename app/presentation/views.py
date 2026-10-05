"""Public presentation views.

UI-OPT-01 keeps the catalog URL-addressable while bounding each response to one database-backed
page. A detail page carries q/platform/sort/page back to the exact catalog page without sessions.
"""

from urllib.parse import urlencode

from catalog.models import Game
from catalog.queries import (
    get_game_detail,
    list_platform_options,
    list_similar_games,
    paginate_games,
)
from django.conf import settings
from django.db import DatabaseError, connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_safe

from presentation.letsplays import get_letsplay
from presentation.summaries import get_summaries


def _list_params(request: HttpRequest, *, include_page: bool = True) -> dict[str, str]:
    params: dict[str, str] = {}
    query = request.GET.get("q", "").strip()
    if query:
        params["q"] = query
    platform = request.GET.get("platform", "").strip()
    if platform:
        params["platform"] = platform
    sort = request.GET.get("sort")
    if sort is not None:
        # Kept even when empty so a card's "back" link reproduces the list URL exactly; any
        # value other than `release` means the default order.
        params["sort"] = "release" if sort.strip() == "release" else ""
    if include_page:
        raw_page = request.GET.get("page", "").strip()
        try:
            page_number = int(raw_page) if raw_page.isdecimal() else 1
        except ValueError:
            page_number = 1
        if page_number > 1:
            params["page"] = str(page_number)
    return params


@require_safe
@cache_control(public=True, max_age=60)
def index(request: HttpRequest) -> HttpResponse:
    params = _list_params(request, include_page=False)
    query = params.get("q", "")
    platform = params.get("platform")
    page = paginate_games(
        query=query,
        platform=platform,
        sort=params.get("sort", "score"),
        page=request.GET.get("page"),
    )

    detail_params = dict(params)
    if page.number > 1:
        detail_params["page"] = str(page.number)

    context = {
        "version": settings.APP_VERSION,
        "games": page.items,
        "page": page,
        "platforms": list_platform_options(),
        "query": query,
        "selected_platform": platform or "",
        "selected_sort": params.get("sort", "score"),
        "query_string": urlencode(detail_params),
        "pagination_query_string": urlencode(params),
        "monitoring_enabled": settings.OPS_MONITORING_ENABLED,
    }
    return render(request, "presentation/index.html", context)


@require_safe
@cache_control(public=True, max_age=60)
def game_detail(request: HttpRequest, game_id: int) -> HttpResponse:
    detail = get_game_detail(game_id)
    if detail is None:
        raise Http404("Game not found")
    game = Game.objects.get(pk=game_id)
    context = {
        "game": detail,
        "summaries": get_summaries(game),
        "letsplay": get_letsplay(game),
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
