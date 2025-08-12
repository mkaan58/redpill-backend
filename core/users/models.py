# users/models.py
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from .managers import CustomUserManager

class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    surname = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

        # Abonelik tipi için alan ekleyelim
    SUBSCRIPTION_CHOICES = [
        ('free', 'Free'),
        ('basic', 'Basic'),
        ('premium', 'Premium'),
    ]
    subscription_type = models.CharField(
        max_length=10,
        choices=SUBSCRIPTION_CHOICES,
        default='free'
    )
    subscription_expiry = models.DateTimeField(blank=True, null=True)
    
    # Fields for email verification
    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=255, blank=True, null=True)
    email_verification_token_created = models.DateTimeField(blank=True, null=True)
    social_provider = models.CharField(max_length=30, blank=True, null=True)
    
    # Fields for password reset
    password_reset_token = models.CharField(max_length=255, blank=True, null=True)
    password_reset_token_created = models.DateTimeField(blank=True, null=True)
    
    objects = CustomUserManager()
    
    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def get_full_name(self):
        if self.name and self.surname:
            return f"{self.name} {self.surname}"
        return self.email
    
    def get_short_name(self):
        return self.name or self.email.split('@')[0]
        # Sosyal giriş bağlantısı olup olmadığını kontrol eden helper fonksiyon
    def has_social_login(self):
        return bool(self.social_provider)
    
    # Hem şifre hem de sosyal bağlantı kontrol
    def has_login_methods(self):
        return self.has_usable_password() or self.has_social_login()

    @property
    def is_basic(self):
        """Kullanıcının Basic plan olup olmadığını kontrol eder"""
        if self.subscription_type == 'basic':
            # Eğer abonelik süresi dolmamışsa Basic kullanıcı
            if self.subscription_expiry and self.subscription_expiry > timezone.now():
                return True
            # Abonelik süresi dolmuşsa Free'ye düşür
            else:
                self.subscription_type = 'free'
                self.subscription_expiry = None
                self.save(update_fields=['subscription_type', 'subscription_expiry'])
                return False
        return False

    @property
    def is_premium(self):
        """Kullanıcının Premium plan olup olmadığını kontrol eder"""
        if self.subscription_type == 'premium':
            # Eğer abonelik süresi dolmamışsa Premium kullanıcı
            if self.subscription_expiry and self.subscription_expiry > timezone.now():
                return True
            # Abonelik süresi dolmuşsa Free'ye düşür
            else:
                self.subscription_type = 'free'
                self.subscription_expiry = None
                self.save(update_fields=['subscription_type', 'subscription_expiry'])
                return False
        return False

    @property
    def is_pro(self):
        """Geriye dönük uyumluluk için - Premium kullanıcıları Pro olarak kabul eder"""
        return self.is_premium

    @property
    def is_free(self):
        """Kullanıcının Free plan olup olmadığını kontrol eder"""
        return self.subscription_type == 'free'

    @property
    def subscription_tier(self):
        """Kullanıcının aktif abonelik seviyesini döndürür"""
        if self.is_premium:
            return 'premium'
        elif self.is_basic:
            return 'basic'
        else:
            return 'free'