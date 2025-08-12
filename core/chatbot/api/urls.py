# chatbot/urls.py
from django.urls import path, include
from . import views

app_name = 'chatbot'

urlpatterns = [
    # Chat Sessions
    path('sessions/', views.ChatSessionListCreateView.as_view(), name='session-list-create'),
    path('sessions/<uuid:pk>/', views.ChatSessionDetailView.as_view(), name='session-detail'),
    path('sessions/<uuid:session_id>/messages/', views.ChatMessagesView.as_view(), name='session-messages'),
    path('sessions/<uuid:session_id>/send/', views.SendMessageView.as_view(), name='send-message'),
    
    # Message Actions
    path('messages/<uuid:message_id>/regenerate/', views.regenerate_response, name='regenerate-response'),
    path('messages/<uuid:message_id>/edit/', views.edit_message, name='edit-message'),
    
    # User Settings & Stats
    path('settings/', views.UserChatSettingsView.as_view(), name='chat-settings'),
    path('stats/', views.ChatUsageStatsView.as_view(), name='usage-stats'),
    
    # Feedback
    path('feedback/', views.ChatFeedbackView.as_view(), name='chat-feedback'),
    
    # Utility
    path('clear-history/', views.clear_chat_history, name='clear-history'),
    path('health/', views.chat_health_check, name='health-check'),
]