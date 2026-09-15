from django.urls import path

from . import views

app_name = "players"

urlpatterns = [
    path("", views.PlayerListView.as_view(), name="list"),
    path("nouveau/", views.PlayerCreateView.as_view(), name="create"),
    path("importer/", views.PlayerImportView.as_view(), name="import"),
    path("<slug:slug>/modifier/", views.PlayerUpdateView.as_view(), name="update"),
    path("<slug:slug>/creer-acces/", views.PlayerLoginCreateView.as_view(), name="login_create"),
    path("<slug:slug>/reinitialiser-mot-de-passe/", views.PlayerLoginResetView.as_view(), name="login_reset"),
]
