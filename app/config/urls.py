from django.urls import path
from presentation import views

urlpatterns = [
    path("", views.index, name="index"),
    path("health/live/", views.live, name="live"),
    path("health/ready/", views.ready, name="ready"),
]
