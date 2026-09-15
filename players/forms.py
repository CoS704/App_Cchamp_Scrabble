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


class PlayerLoginForm(BootstrapFormMixin, forms.Form):
    """Création du compte de connexion d'un joueur (§ accès joueur) : seuls
    l'identifiant et l'e-mail se saisissent, le mot de passe est généré."""

    username = forms.CharField(label="Identifiant", max_length=150)
    email = forms.EmailField(
        label="E-mail",
        help_text=(
            "Si le joueur a une vraie adresse, ses identifiants lui seront "
            "envoyés automatiquement par e-mail. Laisser l'adresse générée "
            "(@joueurs.local) si vous ne préférez les communiquer vous-même."
        ),
    )

    def clean_username(self):
        from django.contrib.auth import get_user_model

        username = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username=username).exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé.")
        return username

    def clean_email(self):
        from django.contrib.auth import get_user_model

        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email=email).exists():
            raise forms.ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email


class PlayerImportForm(BootstrapFormMixin, forms.Form):
    csv_file = forms.FileField(
        label="Fichier CSV",
        help_text="Colonnes attendues : prenom, nom, club (facultatif), pays (facultatif).",
    )
