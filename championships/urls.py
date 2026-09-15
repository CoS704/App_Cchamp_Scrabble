from django.urls import path

from . import views

app_name = "championships"

urlpatterns = [
    path("", views.ChampionshipListView.as_view(), name="list"),
    path("nouveau/", views.ChampionshipCreateView.as_view(), name="create"),
    path("<slug:slug>/", views.ChampionshipDetailView.as_view(), name="detail"),
    path(
        "<slug:slug>/parametres/",
        views.ChampionshipSettingsUpdateView.as_view(),
        name="settings",
    ),
    path("<slug:slug>/verrouiller/", views.LockRulesView.as_view(), name="lock_rules"),
    path("<slug:slug>/supprimer/", views.ChampionshipDeleteView.as_view(), name="delete"),
    path(
        "<slug:slug>/divisions/nouvelle/",
        views.DivisionCreateView.as_view(),
        name="division_create",
    ),
    path(
        "<slug:slug>/divisions/<int:pk>/modifier/",
        views.DivisionUpdateView.as_view(),
        name="division_update",
    ),
    path(
        "<slug:slug>/divisions/<int:pk>/supprimer/",
        views.DivisionDeleteView.as_view(),
        name="division_delete",
    ),
    path(
        "<slug:slug>/promotions/nouvelle/",
        views.MovementRuleCreateView.as_view(),
        name="movement_rule_create",
    ),
    path(
        "<slug:slug>/promotions/<int:pk>/supprimer/",
        views.MovementRuleDeleteView.as_view(),
        name="movement_rule_delete",
    ),
]
