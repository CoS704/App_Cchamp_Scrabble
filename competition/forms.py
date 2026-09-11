from django import forms

from core.forms import BootstrapFormMixin

from .services.result import participation_for_user


class ScheduleGenerateForm(BootstrapFormMixin, forms.Form):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Date de la 1ʳᵉ journée",
        help_text="Facultatif — laissez vide pour ne dater aucune journée.",
    )
    interval_days = forms.IntegerField(
        min_value=1, initial=7, label="Intervalle entre journées (jours)"
    )
    force = forms.BooleanField(
        required=False,
        label="Remplacer le calendrier existant (si aucun résultat n'est validé)",
    )


class MatchRescheduleForm(BootstrapFormMixin, forms.Form):
    scheduled_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}), label="Nouvelle date"
    )
    scheduled_time = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"type": "time"}), label="Nouvelle heure"
    )


class MatchCancelForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Motif (facultatif)"
    )


class MatchForfeitForm(BootstrapFormMixin, forms.Form):
    loser = forms.ChoiceField(label="Joueur déclaré forfait", choices=())
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(self, *args, match=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = []
        if match is not None:
            choices.append((str(match.player1_id), str(match.player1.player)))
            if match.player2_id:
                choices.append((str(match.player2_id), str(match.player2.player)))
        self.fields["loser"].choices = choices


class ResultSubmissionForm(BootstrapFormMixin, forms.Form):
    """Champs adaptés à qui saisit : « mon score / adversaire » pour un
    joueur, « score {X} / score {Y} » pour un arbitre ou un admin."""

    def __init__(self, *args, match, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.participation = participation_for_user(user, match)
        if self.participation is not None:
            self.fields["my_score"] = forms.IntegerField(min_value=0, label="Mon score")
            self.fields["opponent_score"] = forms.IntegerField(
                min_value=0, label="Score de l'adversaire"
            )
        else:
            p1_name = str(match.player1.player)
            p2_name = str(match.player2.player) if match.player2_id else "Exempt"
            self.fields["score1"] = forms.IntegerField(min_value=0, label=f"Score — {p1_name}")
            self.fields["score2"] = forms.IntegerField(min_value=0, label=f"Score — {p2_name}")

    def get_orientation_scores(self):
        """Retourne (score1, score2) toujours dans l'orientation du match."""
        if self.participation is not None:
            my_score = self.cleaned_data["my_score"]
            opponent_score = self.cleaned_data["opponent_score"]
            if self.participation.id == self.match.player1_id:
                return my_score, opponent_score
            return opponent_score, my_score
        return self.cleaned_data["score1"], self.cleaned_data["score2"]
