from django import forms

from core.forms import BootstrapFormMixin

from .models import Championship, ChampionshipSettings, Division, PromotionRelegationRule


class ChampionshipForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Championship
        fields = [
            "series",
            "name",
            "season",
            "edition_number",
            "description",
            "start_date",
            "end_date",
            "registration_opens_at",
            "registration_closes_at",
            "is_inaugural",
            "previous_edition",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "registration_opens_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "registration_closes_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        help_texts = {
            "is_inaugural": (
                "Cochez pour une première édition : pensez à ouvrir largement la "
                "capacité de la division d'entrée, tous les joueurs pouvant y démarrer."
            ),
        }


class ChampionshipSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ChampionshipSettings
        fields = [
            "points_win",
            "points_draw",
            "points_loss",
            "points_forfeit_win",
            "points_forfeit_loss",
            "forfeit_score_for",
            "forfeit_score_against",
            "primary_tiebreak",
            "round_robin_legs",
            "result_entry_policy",
            "result_confirmation_required",
            "double_entry_auto_confirm",
            "late_match_threshold_days",
            "max_matches_per_day",
            "finals_enabled",
            "finals_qualifiers_count",
            "finals_format",
            "finals_third_place",
            "carry_over_between_editions",
        ]
        widgets = {"max_matches_per_day": forms.NumberInput(attrs={"min": 1})}


class DivisionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Division
        fields = [
            "name",
            "level",
            "carryover_key",
            "capacity_min",
            "capacity_max",
            "is_unlimited",
            "color",
            "status",
            "description",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "carryover_key": "Identifiant stable d'une édition à l'autre (ex. « d1 »).",
            "capacity_max": "Laissez vide, ou cochez « illimitée », si sans plafond.",
        }


class PromotionRelegationRuleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PromotionRelegationRule
        fields = [
            "movement_type",
            "source_division",
            "target_division",
            "method",
            "value_n",
            "percentage",
            "rank_min",
            "rank_max",
            "priority",
            "is_active",
        ]

    def __init__(self, *args, championship=None, **kwargs):
        super().__init__(*args, **kwargs)
        if championship is not None:
            queryset = championship.divisions.all()
            self.fields["source_division"].queryset = queryset
            self.fields["target_division"].queryset = queryset
