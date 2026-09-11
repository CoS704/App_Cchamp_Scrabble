from django.urls import path

from . import views

app_name = "competition"

urlpatterns = [
    path("", views.CalendarView.as_view(), name="list"),
    path(
        "generer/<int:division_id>/",
        views.ScheduleGenerateView.as_view(),
        name="generate",
    ),
    path("<int:pk>/reprogrammer/", views.MatchRescheduleView.as_view(), name="reschedule"),
    path("<int:pk>/reporter/", views.MatchPostponeView.as_view(), name="postpone"),
    path("<int:pk>/annuler/", views.MatchCancelView.as_view(), name="cancel"),
    path("<int:pk>/forfait/", views.MatchForfeitView.as_view(), name="forfeit"),
    path("<int:pk>/resultat/", views.MatchResultView.as_view(), name="result"),
    path("<int:pk>/rejeter/", views.MatchRejectResultView.as_view(), name="reject"),
]
