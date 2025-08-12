# chatbot/admin.py
from django.contrib import admin
from .models import ChatSession, ChatMessage, UserChatSettings, ChatFeedback, ChatUsageStats

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'title', 'message_count', 'created_at', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['user__email', 'title']
    readonly_fields = ['id', 'created_at', 'updated_at']

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'session', 'is_user', 'timestamp', 'response_time']
    list_filter = ['is_user', 'timestamp']
    search_fields = ['session__user__email', 'content']
    readonly_fields = ['id', 'timestamp']

@admin.register(UserChatSettings)
class UserChatSettingsAdmin(admin.ModelAdmin):
    list_display = ['user', 'response_style', 'context_length', 'auto_title_generation']
    list_filter = ['response_style', 'auto_title_generation']
    search_fields = ['user__email']

@admin.register(ChatFeedback)
class ChatFeedbackAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['user__email']

@admin.register(ChatUsageStats)
class ChatUsageStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'total_messages_sent', 'monthly_messages_sent', 'last_chat_date']
    search_fields = ['user__email']
    readonly_fields = ['user', 'total_messages_sent', 'total_sessions_created']