from django.urls import path

from . import views

app_name = "public_finals"

urlpatterns = [
    path("", views.PublicBracketListView.as_view(), name="list"),
    path("<int:pk>/", views.PublicBracketDetailView.as_view(), name="detail"),
]
