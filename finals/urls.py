from django.urls import path

from . import views

app_name = "finals"

urlpatterns = [
    path("", views.BracketListView.as_view(), name="list"),
    path("generer/<int:division_id>/", views.BracketGenerateView.as_view(), name="generate"),
    path("<int:pk>/", views.BracketDetailView.as_view(), name="detail"),
]
