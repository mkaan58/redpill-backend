# payments/urls.py
from django.urls import path
from . import views
from .views import (
    CancelSubscriptionView,
    ChangePlanView,
    
)

app_name = 'payments'

urlpatterns = [
    path('subscription/', views.SubscriptionDetailView.as_view(), name='subscription-detail'),
    path('history/', views.PaymentHistoryView.as_view(), name='payment-history'),
    path('subscription/cancel/', CancelSubscriptionView.as_view(), name='subscription-cancel'),
    path('subscription/change-plan/', ChangePlanView.as_view(), name='subscription-change-plan'),
    path('webhook/lemon-squeezy/', views.lemon_squeezy_webhook, name='lemon-squeezy-webhook'),
]
