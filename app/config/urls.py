from django.urls import path
from presentation import monitoring, views

urlpatterns = [
    path("", views.index, name="index"),
    path("games/<int:game_id>/", views.game_detail, name="game-detail"),
    path("ops/", monitoring.index, name="monitoring"),
    path("ops/status/", monitoring.status, name="monitoring-status"),
    path("health/live/", views.live, name="live"),
    path("health/ready/", views.ready, name="ready"),
]
