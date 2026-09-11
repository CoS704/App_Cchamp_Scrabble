from django.contrib import admin

from .models import ChampionshipParticipation


@admin.register(ChampionshipParticipation)
class ChampionshipParticipationAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "championship",
        "division",
        "seed",
        "status",
        "entry_origin",
        "final_rank",
    )
    list_filter = ("championship", "division", "status", "entry_origin")
    search_fields = ("player__first_name", "player__last_name", "player__display_name")
    autocomplete_fields = ("player", "championship", "division", "source_participation")
