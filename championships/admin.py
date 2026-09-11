from django.contrib import admin

from .models import (
    Championship,
    ChampionshipSettings,
    ChampionshipTiebreak,
    CompetitionSeries,
    Division,
    PromotionRelegationRule,
)


class DivisionInline(admin.TabularInline):
    model = Division
    extra = 0


class ChampionshipTiebreakInline(admin.TabularInline):
    model = ChampionshipTiebreak
    extra = 0


class PromotionRelegationRuleInline(admin.TabularInline):
    model = PromotionRelegationRule
    extra = 0
    fk_name = "championship"


class ChampionshipSettingsInline(admin.StackedInline):
    model = ChampionshipSettings
    extra = 0
    can_delete = False


@admin.register(CompetitionSeries)
class CompetitionSeriesAdmin(admin.ModelAdmin):
    list_display = ("name", "organizer", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Championship)
class ChampionshipAdmin(admin.ModelAdmin):
    list_display = ("name", "season", "series", "status", "is_inaugural", "rules_locked")
    list_filter = ("status", "is_inaugural", "series")
    search_fields = ("name", "season")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("series", "previous_edition", "created_by")
    inlines = [
        ChampionshipSettingsInline,
        DivisionInline,
        ChampionshipTiebreakInline,
        PromotionRelegationRuleInline,
    ]


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ("name", "championship", "level", "capacity_max", "registered_count", "status")
    list_filter = ("championship", "status")
    search_fields = ("name",)


@admin.register(PromotionRelegationRule)
class PromotionRelegationRuleAdmin(admin.ModelAdmin):
    list_display = (
        "championship",
        "movement_type",
        "source_division",
        "target_division",
        "method",
        "priority",
        "is_active",
    )
    list_filter = ("championship", "movement_type", "method", "is_active")
