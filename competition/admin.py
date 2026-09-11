from django.contrib import admin

from .models import Match, Matchday, Phase, ResultSubmission, TieResolution


class MatchdayInline(admin.TabularInline):
    model = Matchday
    extra = 0


class ResultSubmissionInline(admin.TabularInline):
    model = ResultSubmission
    extra = 0


@admin.register(Phase)
class PhaseAdmin(admin.ModelAdmin):
    list_display = ("name", "championship", "division", "kind", "order", "status")
    list_filter = ("championship", "kind", "status")
    search_fields = ("name", "championship__name", "division__name")
    inlines = [MatchdayInline]


@admin.register(Matchday)
class MatchdayAdmin(admin.ModelAdmin):
    list_display = ("__str__", "phase", "number", "scheduled_date", "status")
    list_filter = ("status", "phase__championship")
    search_fields = ("name", "phase__name", "phase__championship__name")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "championship",
        "division",
        "matchday",
        "status",
        "result_status",
        "score1",
        "score2",
        "counts_for_standings",
    )
    list_filter = ("championship", "division", "status", "result_status", "phase__kind")
    search_fields = (
        "player1__player__last_name",
        "player2__player__last_name",
    )
    autocomplete_fields = ("player1", "player2", "winner", "matchday", "phase")
    inlines = [ResultSubmissionInline]
    readonly_fields = ("pair_key",)


@admin.register(ResultSubmission)
class ResultSubmissionAdmin(admin.ModelAdmin):
    list_display = ("match", "score1", "score2", "source", "submitted_by", "is_superseded")
    list_filter = ("source", "is_superseded", "outcome_type")


@admin.register(TieResolution)
class TieResolutionAdmin(admin.ModelAdmin):
    list_display = ("championship", "division", "phase", "decided_by", "created_at")
    list_filter = ("championship", "division")
    filter_horizontal = ("participations",)
