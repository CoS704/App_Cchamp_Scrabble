from django import forms

from core.forms import BootstrapFormMixin


class ConfirmTransitionForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(label="Nom de la nouvelle édition", max_length=180)
    season = forms.CharField(label="Saison", max_length=40, help_text="Ex. « 2027 ».")


class MoveEditForm(BootstrapFormMixin, forms.Form):
    to_carryover_key = forms.ChoiceField(label="Division cible", choices=(), required=False)

    def __init__(self, *args, championship, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_carryover_key"].choices = [("", "— sortie de structure —")] + [
            (d.carryover_key, d.name) for d in championship.divisions.all()
        ]
