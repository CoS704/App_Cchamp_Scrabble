from django.urls import path

from . import views

app_name = "public_rankings"

urlpatterns = [
    path("", views.PublicChampionshipListView.as_view(), name="list"),
    path("<slug:slug>/", views.PublicStandingsView.as_view(), name="detail"),
]
