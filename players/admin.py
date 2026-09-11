from django.contrib import admin

from .models import Player


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "club", "country", "is_active", "user")
    list_filter = ("is_active", "country", "club")
    search_fields = ("first_name", "last_name", "display_name", "user__username", "user__email")
    autocomplete_fields = ("user", "created_by")
    prepopulated_fields = {"slug": ("first_name", "last_name")}
