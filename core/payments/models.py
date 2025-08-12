# payments/models.py
from django.db import models
from django.utils import timezone
from users.models import User

class Subscription(models.Model):
    """
    Kullanıcının abonelik bilgilerini saklar
    """
    SUBSCRIPTION_STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('paused', 'Paused'),
        ('expired', 'Expired'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription')
    lemon_squeezy_customer_id = models.CharField(max_length=255, blank=True, null=True)
    lemon_squeezy_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    lemon_squeezy_order_id = models.CharField(max_length=255, blank=True, null=True)
    lemon_squeezy_product_id = models.CharField(max_length=255, blank=True, null=True)
    lemon_squeezy_variant_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Abonelik durumu ve tarihleri
    status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS_CHOICES, default='active')
    is_trial = models.BooleanField(default=False)
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    renews_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    
    # Ödeme bilgileri
    card_brand = models.CharField(max_length=50, blank=True, null=True)
    card_last_four = models.CharField(max_length=4, blank=True, null=True)
    update_payment_url = models.TextField(blank=True, null=True)
    customer_portal_url = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email}'s Subscription"
    
    @property
    def is_active(self):
        """
        Aboneliğin aktif olup olmadığını kontrol eder
        """
        if self.status != 'active':
            return False
        
        if self.is_trial and self.trial_ends_at:
            return self.trial_ends_at > timezone.now()
        
        if self.ends_at:
            return self.ends_at > timezone.now()
        
        return True

class Payment(models.Model):
    """
    Kullanıcının ödeme geçmişini saklar
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    
    # Lemon Squeezy Bilgileri
    lemon_squeezy_order_id = models.CharField(max_length=255)
    lemon_squeezy_order_item_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Ödeme bilgileri
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(max_length=20, default='completed')
    
    # İşlem bilgileri
    invoice_url = models.URLField(blank=True, null=True)
    receipt_url = models.URLField(blank=True, null=True)
    
    # Timestamps
    payment_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email}'s Payment of {self.amount} {self.currency}"