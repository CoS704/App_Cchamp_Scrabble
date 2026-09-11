from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("<int:pk>/lu/", views.MarkReadView.as_view(), name="mark_read"),
    path("tout-marquer-lu/", views.MarkAllReadView.as_view(), name="mark_all_read"),
]
