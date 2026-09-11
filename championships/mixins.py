from django.shortcuts import get_object_or_404

from .models import Championship


class ChampionshipScopedMixin:
    """Résout ``self.championship`` depuis le slug de l'URL avant tout contrôle
    de permission — voir ``core.permissions.ChampionshipAdminRequiredMixin``,
    qui doit être listé APRÈS ce mixin dans les bases de la vue pour que
    ``self.championship`` existe déjà quand le test de permission s'exécute.
    """

    championship_url_kwarg = "slug"

    def dispatch(self, request, *args, **kwargs):
        self.championship = get_object_or_404(
            Championship.objects.select_related("series", "settings"),
            slug=kwargs[self.championship_url_kwarg],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_championship(self):
        return self.championship

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["championship"] = self.championship
        return context


class TitledFormMixin:
    """Ajoute un titre de page au contexte, pour un template de formulaire générique."""

    form_title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = self.form_title
        return context
