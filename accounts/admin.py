from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import ChampionshipStaff, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Profil", {"fields": ("photo", "phone")}),
    )


@admin.register(ChampionshipStaff)
class ChampionshipStaffAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "championship", "is_active")
    list_filter = ("role", "is_active", "championship")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user", "championship", "assigned_by")
    filter_horizontal = ("divisions",)
