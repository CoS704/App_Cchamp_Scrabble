from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from dashboard.views import PlayerDashboardView

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("mon-espace/", PlayerDashboardView.as_view(), name="player_dashboard"),
    path("mon-espace/simulation/", include("dashboard.player_urls")),
    path("notifications/", include("notifications.urls")),
    path("classements/", include("rankings.public_urls")),
    path(
        "gestion/championnats/<slug:slug>/dashboard/",
        include("dashboard.urls"),
    ),
    path(
        "gestion/championnats/<slug:slug>/joueurs/",
        include("participations.urls"),
    ),
    path(
        "gestion/championnats/<slug:slug>/calendrier/",
        include("competition.urls"),
    ),
    path(
        "gestion/championnats/<slug:slug>/classement/",
        include("rankings.urls"),
    ),
    path(
        "gestion/championnats/<slug:slug>/finales/",
        include("finals.urls"),
    ),
    path(
        "gestion/championnats/<slug:slug>/saison-suivante/",
        include("transitions.urls"),
    ),
    path("gestion/championnats/", include("championships.urls")),
    path("gestion/joueurs/", include("players.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
