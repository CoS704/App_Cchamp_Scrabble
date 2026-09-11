from django.contrib import admin

from .models import SeasonTransition, SeasonTransitionMove


class SeasonTransitionMoveInline(admin.TabularInline):
    model = SeasonTransitionMove
    extra = 0
    autocomplete_fields = ("source_participation", "player")


@admin.register(SeasonTransition)
class SeasonTransitionAdmin(admin.ModelAdmin):
    list_display = ("from_championship", "to_championship", "status", "created_by", "created_at")
    list_filter = ("status",)
    inlines = [SeasonTransitionMoveInline]


@admin.register(SeasonTransitionMove)
class SeasonTransitionMoveAdmin(admin.ModelAdmin):
    list_display = (
        "transition",
        "player",
        "from_carryover_key",
        "to_carryover_key",
        "move_type",
        "is_manual_override",
    )
    list_filter = ("move_type", "is_manual_override")
