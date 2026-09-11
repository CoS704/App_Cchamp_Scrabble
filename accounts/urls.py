from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import (
    StyledAuthenticationForm,
    StyledPasswordChangeForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)

app_name = "accounts"

urlpatterns = [
    path(
        "connexion/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=StyledAuthenticationForm,
        ),
        name="login",
    ),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "mot-de-passe/changer/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            form_class=StyledPasswordChangeForm,
            success_url="/accounts/mot-de-passe/changer/termine/",
        ),
        name="password_change",
    ),
    path(
        "mot-de-passe/changer/termine/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),
    path(
        "mot-de-passe/oublie/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            form_class=StyledPasswordResetForm,
            email_template_name="accounts/password_reset_email.txt",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url="/accounts/mot-de-passe/oublie/envoye/",
        ),
        name="password_reset",
    ),
    path(
        "mot-de-passe/oublie/envoye/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "mot-de-passe/reinitialiser/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            form_class=StyledSetPasswordForm,
            success_url="/accounts/mot-de-passe/reinitialiser/termine/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "mot-de-passe/reinitialiser/termine/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("profil/", views.ProfileView.as_view(), name="profile"),
]
