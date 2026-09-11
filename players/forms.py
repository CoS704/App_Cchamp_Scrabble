from django import forms

from core.forms import BootstrapFormMixin

from .models import Player


class PlayerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Player
        fields = [
            "first_name",
            "last_name",
            "display_name",
            "scrabblego_id",
            "photo",
            "birth_date",
            "country",
            "club",
            "bio",
            "is_active",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 2}),
            "birth_date": forms.DateInput(attrs={"type": "date"}),
        }


class PlayerScrabbleGoForm(BootstrapFormMixin, forms.ModelForm):
    """Auto-édition par le joueur de son seul identifiant ScrabbleGO (§profil) :
    pas besoin de passer par un administrateur pour ce champ déclaratif."""

    class Meta:
        model = Player
        fields = ["scrabblego_id"]


class PlayerImportForm(BootstrapFormMixin, forms.Form):
    csv_file = forms.FileField(
        label="Fichier CSV",
        help_text="Colonnes attendues : prenom, nom, club (facultatif), pays (facultatif).",
    )
