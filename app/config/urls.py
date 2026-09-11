from django.urls import path
from presentation import views

urlpatterns = [
    path("", views.index, name="index"),
    path("games/<int:game_id>/", views.game_detail, name="game-detail"),
    path("health/live/", views.live, name="live"),
    path("health/ready/", views.ready, name="ready"),
]
