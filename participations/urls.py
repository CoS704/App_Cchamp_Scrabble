from django.urls import path

from . import views

app_name = "participations"

urlpatterns = [
    path("", views.ParticipationListView.as_view(), name="list"),
    path("inscrire/", views.ParticipationCreateView.as_view(), name="create"),
    path("<int:pk>/retirer/", views.ParticipationWithdrawView.as_view(), name="withdraw"),
]
