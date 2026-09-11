from django.urls import path

from . import views

app_name = "rankings"

urlpatterns = [
    path("", views.StandingsView.as_view(), name="standings"),
]
