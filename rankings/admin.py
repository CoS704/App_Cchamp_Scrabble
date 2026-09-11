from django.contrib import admin

from .models import StandingRow, StandingSnapshot


class StandingRowInline(admin.TabularInline):
    model = StandingRow
    extra = 0


@admin.register(StandingSnapshot)
class StandingSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "championship",
        "division",
        "phase",
        "is_current",
        "has_unresolved_tie",
        "computed_at",
    )
    list_filter = ("championship", "division", "is_current")
    inlines = [StandingRowInline]
