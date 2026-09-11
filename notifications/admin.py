from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("kind", "recipient", "title", "priority", "is_read", "created_at")
    list_filter = ("kind", "priority", "is_read")
    search_fields = ("title", "recipient__username", "recipient__email")
