from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from players.forms import PlayerScrabbleGoForm


class ProfileView(LoginRequiredMixin, TemplateView):
    """Vue de profil minimale : compte, rôles d'édition, éventuel profil joueur.

    Sera enrichie (photo, historique, notifications…) aux étapes UI.
    """

    template_name = "accounts/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["staff_roles"] = (
            user.staff_roles.select_related("championship").filter(is_active=True)
        )
        player = getattr(user, "player", None)
        context["player"] = player
        if player and "scrabblego_form" not in context:
            context["scrabblego_form"] = PlayerScrabbleGoForm(instance=player)
        return context

    def post(self, request, *args, **kwargs):
        player = getattr(request.user, "player", None)
        if not player:
            return redirect("accounts:profile")
        form = PlayerScrabbleGoForm(request.POST, instance=player)
        if form.is_valid():
            form.save()
            messages.success(request, "Identifiant ScrabbleGO mis à jour.")
            return redirect(reverse("accounts:profile"))
        context = self.get_context_data(scrabblego_form=form)
        return self.render_to_response(context)
