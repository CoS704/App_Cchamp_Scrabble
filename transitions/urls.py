from django.urls import path

from . import views

app_name = "transitions"

urlpatterns = [
    path("", views.TransitionDetailView.as_view(), name="detail"),
    path("proposer/", views.ProposeTransitionView.as_view(), name="propose"),
    path("<int:move_id>/modifier/", views.MoveEditView.as_view(), name="move_edit"),
    path("confirmer/", views.ConfirmTransitionView.as_view(), name="confirm"),
    path("annuler/", views.CancelTransitionView.as_view(), name="cancel"),
]
