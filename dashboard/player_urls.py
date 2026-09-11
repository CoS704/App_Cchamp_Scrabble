from django.urls import path

from . import views

app_name = "dashboard_player"

urlpatterns = [
    path("", views.SimulationView.as_view(), name="simulation"),
]
