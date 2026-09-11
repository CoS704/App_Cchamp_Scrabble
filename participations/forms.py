from django import forms

from core.forms import BootstrapFormMixin
from players.models import Player


class ParticipationForm(BootstrapFormMixin, forms.Form):
    """Formulaire de saisie ; la validation métier (capacité, doublon) vit dans
    ``participations.services.register_participation``, pas ici (§52)."""

    player = forms.ModelChoiceField(queryset=Player.objects.none(), label="Joueur")
    division = forms.ModelChoiceField(queryset=None, label="Division")
    seed = forms.IntegerField(required=False, min_value=1, label="Tête de série")

    def __init__(self, *args, championship, **kwargs):
        super().__init__(*args, **kwargs)
        already_registered = championship.participations.values_list("player_id", flat=True)
        self.fields["player"].queryset = (
            Player.objects.filter(is_active=True)
            .exclude(id__in=already_registered)
            .order_by("last_name", "first_name")
        )
        self.fields["division"].queryset = championship.divisions.all()
