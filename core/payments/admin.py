# payments/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Subscription, Payment

# Subscription'a bağlı ödemeleri doğrudan abonelik detay sayfasında
# göstermek için bir inline sınıfı tanımlıyoruz.
class PaymentInline(admin.TabularInline):
    """
    Abonelik detay sayfasında ilgili ödemeleri listeleyen inline panel.
    """
    model = Payment
    # Alanların sıralamasını belirler
    fields = ('payment_date', 'amount', 'currency', 'status', 'view_receipt_link')
    readonly_fields = ('payment_date', 'amount', 'currency', 'status', 'view_receipt_link')
    extra = 0  # Yeni boş ödeme ekleme satırı gösterme
    can_delete = False # Admin üzerinden ödeme silmeyi engelle

    def view_receipt_link(self, obj):
        if obj.receipt_url:
            return format_html('<a href="{}" target="_blank">Makbuzu Görüntüle</a>', obj.receipt_url)
        return "Link Yok"
    view_receipt_link.short_description = "Makbuz"

    def has_add_permission(self, request, obj=None):
        # Admin üzerinden yeni ödeme eklemeyi engelle
        return False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """
    Subscription modeli için Django admin paneli ayarları.
    """
    # Liste görünümünde gösterilecek alanlar
    list_display = (
        'user_email',
        'status',
        'is_active_status',
        'renews_at',
        'ends_at',
        'updated_at',
    )
    
    # Liste görünümünde filtrelenebilecek alanlar
    list_filter = ('status', 'is_trial', 'renews_at')

    # Arama yapılabilecek alanlar
    search_fields = (
        'user__email',
        'lemon_squeezy_subscription_id',
        'lemon_squeezy_customer_id',
    )
    
    # Detay sayfasında sadece okunabilir olacak alanlar
    readonly_fields = (
        'user_link',
        'is_active_status',
        'customer_portal_link',
        'update_payment_link',
        'lemon_squeezy_customer_id',
        'lemon_squeezy_subscription_id',
        'lemon_squeezy_order_id',
        'lemon_squeezy_product_id',
        'lemon_squeezy_variant_id',
        'created_at',
        'updated_at',
    )
    
    # Detay sayfasındaki alanların gruplandırılması ve sıralanması
    fieldsets = (
        ('Kullanıcı Bilgileri', {
            'fields': ('user_link',)
        }),
        ('Abonelik Durumu', {
            'fields': ('status', 'is_active_status', 'is_trial', 'trial_ends_at', 'renews_at', 'ends_at')
        }),
        ('Yönetim Linkleri', {
            'fields': ('customer_portal_link', 'update_payment_link')
        }),
        ('Ödeme Bilgileri', {
            'fields': ('card_brand', 'card_last_four')
        }),
        ('Lemon Squeezy ID\'leri (Sadece Okunur)', {
            'classes': ('collapse',), # Bu bölümü varsayılan olarak kapalı tutar
            'fields': (
                'lemon_squeezy_customer_id',
                'lemon_squeezy_subscription_id',
                'lemon_squeezy_order_id',
                'lemon_squeezy_product_id',
                'lemon_squeezy_variant_id',
            )
        }),
        ('Tarih Bilgileri', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    # Subscription detay sayfasında Payment'ları göstermek için inline'ı ekliyoruz.
    inlines = [PaymentInline]
    
    # Kullanıcı email'ini göstermek için özel bir method
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Kullanıcı E-maili'

    # is_active property'sini admin'de göstermek için
    def is_active_status(self, obj):
        return obj.is_active
    is_active_status.boolean = True # Evet/Hayır ikonu olarak gösterir
    is_active_status.short_description = 'Aktif mi?'
    
    # Kullanıcı modeline admin içinden link vermek için
    def user_link(self, obj):
        link = reverse("admin:users_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', link, obj.user.email)
    user_link.short_description = 'Kullanıcı'

    # URL alanlarını tıklanabilir linklere çeviren methodlar
    def customer_portal_link(self, obj):
        if obj.customer_portal_url:
            return format_html('<a href="{}" target="_blank">Müşteri Portalını Aç</a>', obj.customer_portal_url)
        return "Link Yok"
    customer_portal_link.short_description = "Müşteri Portalı"

    def update_payment_link(self, obj):
        if obj.update_payment_url:
            return format_html('<a href="{}" target="_blank">Ödeme Yöntemini Güncelle</a>', obj.update_payment_url)
        return "Link Yok"
    update_payment_link.short_description = "Ödeme Yöntemi Güncelleme"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Payment modeli için Django admin paneli ayarları.
    """
    list_display = (
        'user',
        'payment_date',
        'amount',
        'currency',
        'status',
        'subscription_link',
        'view_receipt_link'
    )
    list_filter = ('status', 'payment_date', 'currency')
    search_fields = ('user__email', 'lemon_squeezy_order_id', 'subscription__lemon_squeezy_subscription_id')
    
    # Ödemeler webhook'lar tarafından oluşturulduğu için admin panelinde düzenlenemez olmalı.
    readonly_fields = [f.name for f in Payment._meta.fields]
    # Ekstra olarak tıklanabilir linkler ekleyelim
    readonly_fields.extend(['user_link', 'subscription_link', 'view_invoice_link', 'view_receipt_link'])

    fieldsets = (
        ('İlişkili Kayıtlar', {
            'fields': ('user_link', 'subscription_link')
        }),
        ('Ödeme Detayları', {
            'fields': ('amount', 'currency', 'status', 'payment_date')
        }),
        ('İşlem Linkleri', {
            'fields': ('view_invoice_link', 'view_receipt_link')
        }),
        ('Lemon Squeezy ID\'leri', {
            'fields': ('lemon_squeezy_order_id', 'lemon_squeezy_order_item_id')
        }),
    )

    def has_add_permission(self, request):
        return False # Admin üzerinden yeni ödeme oluşturmayı engeller

    def has_change_permission(self, request, obj=None):
        return False # Mevcut ödemeleri düzenlemeyi engeller

    def has_delete_permission(self, request, obj=None):
        return True # Silme yetkisi kalabilir

    # Tıklanabilir linkler için özel methodlar
    def user_link(self, obj):
        link = reverse("admin:users_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', link, obj.user.email)
    user_link.short_description = 'Kullanıcı'

    def subscription_link(self, obj):
        if obj.subscription:
            link = reverse("admin:payments_subscription_change", args=[obj.subscription.id])
            return format_html('<a href="{}">{}</a>', link, obj.subscription.lemon_squeezy_subscription_id)
        return "-"
    subscription_link.short_description = 'Abonelik'

    def view_receipt_link(self, obj):
        if obj.receipt_url:
            return format_html('<a href="{}" target="_blank">Makbuzu Görüntüle</a>', obj.receipt_url)
        return "Link Yok"
    view_receipt_link.short_description = "Makbuz Linki"
    
    def view_invoice_link(self, obj):
        if obj.invoice_url:
            return format_html('<a href="{}" target="_blank">Faturayı Görüntüle</a>', obj.invoice_url)
        return "Link Yok"
    view_invoice_link.short_description = "Fatura Linki"