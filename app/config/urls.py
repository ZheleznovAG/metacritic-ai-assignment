from django.urls import path
from presentation import monitoring, operators, views

urlpatterns = [
    path("", views.index, name="index"),
    path("games/<int:game_id>/", views.game_detail, name="game-detail"),
    path("ops/", monitoring.index, name="monitoring"),
    path("ops/status/", monitoring.status, name="monitoring-status"),
    path("ops/login/", operators.login_view, name="operator-login"),
    path("ops/logout/", operators.logout_view, name="operator-logout"),
    path("ops/run/", operators.run_view, name="manual-run"),
    path("ops/run/<uuid:request_id>/", operators.run_status_view, name="manual-run-status"),
    path("health/live/", views.live, name="live"),
    path("health/ready/", views.ready, name="ready"),
]
