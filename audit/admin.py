from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_label", "action", "target_repr", "championship")
    list_filter = ("action", "championship", "created_at")
    search_fields = ("actor_label", "target_repr", "reason")
    readonly_fields = [f.name for f in AuditLog._meta.fields] + ["target"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
