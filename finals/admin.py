from django.contrib import admin

from .models import Bracket, BracketSlot


class BracketSlotInline(admin.TabularInline):
    model = BracketSlot
    extra = 0
    fk_name = "bracket"


@admin.register(Bracket)
class BracketAdmin(admin.ModelAdmin):
    list_display = ("__str__", "championship", "division", "size", "status")
    list_filter = ("championship", "status")
    inlines = [BracketSlotInline]


@admin.register(BracketSlot)
class BracketSlotAdmin(admin.ModelAdmin):
    list_display = ("bracket", "round_index", "position", "seed", "participation", "is_third_place")
    list_filter = ("bracket__championship", "is_third_place")
