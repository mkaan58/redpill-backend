# payments/serializers.py
from rest_framework import serializers
from .models import Subscription, Payment

class SubscriptionSerializer(serializers.ModelSerializer):
    """
    Abonelik bilgilerini serialize eder
    """
    class Meta:
        model = Subscription
        fields = [
            'status', 'is_trial', 'trial_ends_at', 'renews_at', 'ends_at',
            'card_brand', 'card_last_four', 'update_payment_url',
            'created_at', 'updated_at'
        ]

class PaymentSerializer(serializers.ModelSerializer):
    """
    Ödeme geçmişini serialize eder
    """
    class Meta:
        model = Payment
        fields = [
            'amount', 'currency', 'status',
            'invoice_url', 'receipt_url', 'payment_date'
        ]

class SubscriptionDetailSerializer(serializers.ModelSerializer):
    """
    Abonelik ve son ödeme bilgilerini birlikte serialize eder
    """
    last_payment = serializers.SerializerMethodField()
    
    class Meta:
        model = Subscription
        fields = [
            'status', 'is_trial', 'trial_ends_at', 'renews_at', 'ends_at',
            'card_brand', 'card_last_four', 'update_payment_url',
            'created_at', 'updated_at', 'last_payment','customer_portal_url'
        ]
    
    def get_last_payment(self, obj):
        last_payment = obj.payments.order_by('-payment_date').first()
        if last_payment:
            return {
                'amount': last_payment.amount,
                'currency': last_payment.currency,
                'payment_date': last_payment.payment_date,
                'status': last_payment.status
            }
        return None