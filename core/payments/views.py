import json
import hmac
import hashlib
import logging
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
import requests 
from .models import Subscription, Payment
from .serializers import SubscriptionSerializer, PaymentSerializer, SubscriptionDetailSerializer
from users.models import User

# Logger'ı yapılandır
logger = logging.getLogger(__name__)

# --- Mevcut API View'larınız ---
class SubscriptionDetailView(APIView):
    """Kullanıcının abonelik bilgilerini döndürür"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Mevcut ücretli aboneliği bul
            subscription = Subscription.objects.get(user=request.user)
            serializer = SubscriptionDetailSerializer(subscription)
            data = serializer.data
            


        except Subscription.DoesNotExist:
            # Kullanıcının ücretli aboneliği yoksa (free plan), yükseltme yapabilmesi için checkout URL'lerini gönder.
            data = {
                'status': None,
                'checkout_urls': {
                    'basic': settings.LEMON_SQUEEZY_CHECKOUT_URL_BASIC,
                    'premium': settings.LEMON_SQUEEZY_CHECKOUT_URL_PREMIUM
                }
            }
        
        # Her durumda bu genel bilgileri ekle
        data['subscription_type'] = request.user.subscription_type
        data['is_basic'] = request.user.subscription_type == 'basic'
        data['is_premium'] = request.user.subscription_type == 'premium'
        data['is_free'] = request.user.subscription_type == 'free'
        data['plan_limits'] = self._get_plan_limits(request.user.subscription_type)
        
        return Response(data)
    
    def _get_plan_limits(self, subscription_type):
        """Plan limitlerini döndürür"""
        limits = {
            'free': {'websites': 2},
            'basic': {'websites': 5},
            'premium': {'websites': 20}
        }
        return limits.get(subscription_type, limits['free'])

class PaymentHistoryView(APIView):
    """Kullanıcının ödeme geçmişini döndürür. BU VIEW OLDUĞU GİBİ KALIYOR."""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        payments = Payment.objects.filter(user=request.user).order_by('-payment_date')
        serializer = PaymentSerializer(payments, many=True)
        return Response(serializer.data)

class CancelSubscriptionView(APIView):
    """Kullanıcının mevcut aktif aboneliğini iptal eder."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            subscription = Subscription.objects.get(user=request.user, status='active')
            sub_id = subscription.lemon_squeezy_subscription_id
            
            headers = {
                'Authorization': f'Bearer {settings.LEMON_SQUEEZY_API_KEY}',
                'Accept': 'application/vnd.api+json',
                'Content-Type': 'application/vnd.api+json'
            }
            payload = {"data": {"type": "subscriptions", "id": str(sub_id), "attributes": {"cancelled": True}}}
            
            response = requests.patch(f'https://api.lemonsqueezy.com/v1/subscriptions/{sub_id}', json=payload, headers=headers)
            response.raise_for_status()

            updated_data = response.json()['data']['attributes']
            subscription.status = 'cancelled'
            subscription.ends_at = parse_datetime(updated_data['ends_at'])
            subscription.save()
            
            return Response({'message': 'Subscription cancelled successfully.'}, status=status.HTTP_200_OK)
        except Subscription.DoesNotExist:
            return Response({'error': 'No active subscription found.'}, status=status.HTTP_404_NOT_FOUND)
        except requests.RequestException as e:
            logger.error(f"Lemon Squeezy API error while cancelling: {e}")
            return Response({'error': 'Could not cancel subscription due to a provider issue.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ChangePlanView(APIView):
    """Kullanıcının abonelik planını değiştirir (upgrade/downgrade)."""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        new_variant_id = request.data.get('new_variant_id')
        if not new_variant_id:
            return Response({'error': 'New plan variant ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            subscription = Subscription.objects.get(user=request.user, status='active')
            sub_id = subscription.lemon_squeezy_subscription_id
            
            headers = {
                'Authorization': f'Bearer {settings.LEMON_SQUEEZY_API_KEY}',
                'Accept': 'application/vnd.api+json',
                'Content-Type': 'application/vnd.api+json'
            }
            payload = {"data": {"type": "subscriptions", "id": str(sub_id), "attributes": {"variant_id": str(new_variant_id)}}}
            
            response = requests.patch(f'https://api.lemonsqueezy.com/v1/subscriptions/{sub_id}', json=payload, headers=headers)
            response.raise_for_status()
            
            # Webhook zaten veritabanını güncelleyecek. Başarılı mesajı dönmemiz yeterli.
            return Response({'message': 'Plan changed successfully! The changes will be reflected shortly.'}, status=status.HTTP_200_OK)
        except Subscription.DoesNotExist:
            return Response({'error': 'No active subscription found.'}, status=status.HTTP_404_NOT_FOUND)
        except requests.RequestException as e:
            logger.error(f"Lemon Squeezy API error while changing plan: {e}")
            return Response({'error': 'Could not change plan due to a provider issue.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# --- Webhook Ana Fonksiyonu (Tüm Olaylarla Güncellendi) ---
@csrf_exempt
@require_POST
def lemon_squeezy_webhook(request):
    """Lemon Squeezy webhook endpoint'i"""
    webhook_secret = settings.LEMON_SQUEEZY_WEBHOOK_SECRET
    if not webhook_secret:
        logger.error("LEMON_SQUEEZY_WEBHOOK_SECRET is not configured.")
        return HttpResponse(status=500)

    signature = request.headers.get('X-Signature')
    if not signature:
        logger.warning("Webhook signature missing.")
        return HttpResponse(status=400)

    payload = request.body
    computed_signature = hmac.new(webhook_secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(signature, computed_signature):
        logger.error("Webhook signature verification failed.")
        return HttpResponse(status=401)
    
    try:
        event_data = json.loads(payload.decode('utf-8'))
        event_name = event_data.get('meta', {}).get('event_name')
        logger.info(f"Received webhook event: {event_name}")
        
        # Olay (Event) Yönlendiricisi Haritası
        handler_map = {
            'subscription_created': handle_subscription_created,
            'subscription_updated': handle_subscription_updated,
            'subscription_cancelled': handle_subscription_cancelled,
            'subscription_expired': handle_subscription_expired,
            'subscription_resumed': handle_subscription_resumed,
            'subscription_paused': handle_subscription_paused,
            'subscription_unpaused': handle_subscription_unpaused,
            'subscription_payment_success': handle_subscription_payment_success,
            'subscription_payment_failed': handle_subscription_payment_failed,
            'subscription_plan_changed': handle_subscription_plan_changed,
            'subscription_payment_refunded': handle_subscription_payment_refunded,
            'order_created': handle_order_created,
            'order_refunded': handle_order_refunded,
        }

        handler = handler_map.get(event_name)
        if handler:
            handler(event_data)
        else:
            logger.info(f"No handler for event: {event_name}")
            
        return HttpResponse(status=200)

    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload.")
        return HttpResponse(status=400)
    except Exception as e:
        logger.exception(f"Error processing webhook: {str(e)}")
        return HttpResponse(status=500)

# --- Yardımcı Fonksiyonlar (Hata Düzeltmeleriyle Güncellendi) ---
def determine_subscription_type(product_id_str):
    """Product ID'ye göre abonelik tipini belirler (String olarak karşılaştırır)"""
    # Environment'tan gelen ID'ler string olabileceğinden, string olarak karşılaştırmak daha güvenli
    basic_product_id = str(settings.LEMON_SQUEEZY_BASIC_PRODUCT_ID)
    premium_product_id = str(settings.LEMON_SQUEEZY_PREMIUM_PRODUCT_ID)
    
    if str(product_id_str) == basic_product_id:
        return 'basic'
    elif str(product_id_str) == premium_product_id:
        return 'premium'
    else:
        # ** GÜVENLİK DÜZELTMESİ **
        # Bilinmeyen ID gelirse, 'premium' yerine 'free' yap ve kritik hata logla.
        logger.error(f"Unknown product ID received: {product_id_str}. Defaulting user to 'free' plan.")
        return 'free'

def parse_datetime(date_str):
    """ISO format tarih string'ini datetime objesine çevirir"""
    if not date_str: return None
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except (ValueError, TypeError): return None

# --- Olay (Event) Yöneticisi Fonksiyonları ---

@transaction.atomic
def handle_subscription_created(event_data: dict):
    """
    Yeni bir abonelik oluşturulduğunda gelen webhook'u işler.
    Bu fonksiyon tüm verileri eksiksiz bir şekilde veritabanına kaydeder.
    """
    try:
        data = event_data['data']['attributes']
        user_email = data.get('user_email')

        if not user_email:
            logger.error("'subscription_created' webhook'unda 'user_email' bulunamadı.")
            return

        # İlgili kullanıcıyı e-posta ile bul
        user = User.objects.get(email=user_email)
        
        # Gerekli tüm verileri webhook'tan al
        lemon_subscription_id = event_data['data']['id']
        lemon_product_id = data.get('product_id')
        subscription_type = determine_subscription_type(lemon_product_id)
        
        urls = data.get('urls', {})
        customer_portal_url = urls.get('customer_portal')
        update_payment_url = urls.get('update_payment_method')

        # Aboneliği oluştur veya mevcutsa güncelle (idempotency için)
        # Bu, aynı webhook'un tekrar gelmesi durumunda sisteminizi korur.
        subscription, created = Subscription.objects.update_or_create(
            user=user,
            defaults={
                'lemon_squeezy_subscription_id': lemon_subscription_id,
                'lemon_squeezy_customer_id': data.get('customer_id'),
                'lemon_squeezy_order_id': data.get('order_id'),
                'lemon_squeezy_product_id': lemon_product_id,
                'lemon_squeezy_variant_id': data.get('variant_id'),
                'status': data.get('status'),
                'is_trial': bool(data.get('trial_ends_at')),
                'trial_ends_at': parse_datetime(data.get('trial_ends_at')),
                'renews_at': parse_datetime(data.get('renews_at')),
                'ends_at': parse_datetime(data.get('ends_at')),
                'card_brand': data.get('card_brand'),
                'card_last_four': data.get('card_last_four'),
                'update_payment_url': update_payment_url,
                'customer_portal_url': customer_portal_url, # EN ÖNEMLİ ALAN
            }
        )
        
        # Kullanıcı modelindeki ilgili alanları güncelle
        user.subscription_type = subscription_type
        # Abonelik bitiş tarihi "ends_at" veya bir sonraki yenilenme "renews_at" olabilir.
        user.subscription_expiry = subscription.ends_at or subscription.renews_at
        user.save(update_fields=['subscription_type', 'subscription_expiry'])
        
        log_action = "oluşturuldu" if created else "güncellendi"
        logger.info(f"Abonelik {user.email} için başarıyla {log_action}. Plan: {subscription_type}")

    except User.DoesNotExist:
        logger.error(f"'subscription_created': {user_email} e-postasına sahip kullanıcı bulunamadı.")
    except KeyError as e:
        logger.error(f"'subscription_created' webhook verisinde eksik anahtar: {e}")
    except Exception as e:
        logger.exception(f"'handle_subscription_created' fonksiyonunda beklenmedik bir hata oluştu: {e}")


@transaction.atomic
def handle_subscription_updated(event_data: dict):
    """
    Mevcut bir abonelik güncellendiğinde gelen webhook'u işler.
    Plan değişikliği, duraklatma, devam etme gibi durumları kapsar.
    """
    try:
        lemon_subscription_id = event_data['data']['id']
        
        if not lemon_subscription_id:
            logger.error("'subscription_updated' webhook'unda 'id' bulunamadı.")
            return

        # İlgili aboneliği ve kullanıcıyı veritabanından bul
        # `select_related` ile fazladan veritabanı sorgusunu engelle
        subscription = Subscription.objects.select_related('user').get(lemon_squeezy_subscription_id=lemon_subscription_id)
        user = subscription.user
        
        data = event_data['data']['attributes']

        # Gerekli tüm güncel verileri webhook'tan al
        lemon_product_id = data.get('product_id', subscription.lemon_squeezy_product_id)
        subscription_type = determine_subscription_type(lemon_product_id)

        urls = data.get('urls', {})
        
        # Abonelik nesnesini yeni verilerle güncelle
        subscription.lemon_squeezy_product_id = lemon_product_id
        subscription.lemon_squeezy_variant_id = data.get('variant_id', subscription.lemon_squeezy_variant_id)
        subscription.status = data.get('status', subscription.status)
        subscription.is_trial = bool(data.get('trial_ends_at'))
        subscription.trial_ends_at = parse_datetime(data.get('trial_ends_at'))
        subscription.renews_at = parse_datetime(data.get('renews_at'))
        subscription.ends_at = parse_datetime(data.get('ends_at'))
        subscription.card_brand = data.get('card_brand', subscription.card_brand)
        subscription.card_last_four = data.get('card_last_four', subscription.card_last_four)
        
        # URL'leri güncelle (eğer webhook'ta gelmişse)
        if 'customer_portal' in urls:
            subscription.customer_portal_url = urls['customer_portal']
        if 'update_payment_method' in urls:
            subscription.update_payment_url = urls['update_payment_method']
        
        # Tüm değişiklikleri veritabanına kaydet
        subscription.save()
        
        # Kullanıcı modelindeki ilgili alanları güncelle
        # Eğer abonelik aktif ise planını ve bitiş tarihini güncelle
        if subscription.status in ['active', 'on_trial']:
            user.subscription_type = subscription_type
            user.subscription_expiry = subscription.ends_at or subscription.renews_at
        else:
            # Eğer abonelik iptal edilmiş veya süresi dolmuşsa, kullanıcının erişimi
            # ödediği son tarihe kadar devam eder, ancak plan tipi 'free' olarak ayarlanabilir.
            # Bu kısım iş mantığınıza göre değişebilir. Mevcut mantık, erişim sonuna kadar planı korumak.
            # Eğer abonelik bittiğinde anında 'free' olmasını isterseniz aşağıdaki satırı aktif edin.
            # user.subscription_type = 'free'
            user.subscription_expiry = subscription.ends_at
        
        user.save(update_fields=['subscription_type', 'subscription_expiry'])

        logger.info(f"Abonelik {user.email} için başarıyla güncellendi. Yeni durum: {subscription.status}, Plan: {subscription_type}")

    except Subscription.DoesNotExist:
        logger.error(f"'subscription_updated': {lemon_subscription_id} ID'li abonelik bulunamadı.")
    except KeyError as e:
        logger.error(f"'subscription_updated' webhook verisinde eksik anahtar: {e}")
    except Exception as e:
        logger.exception(f"'handle_subscription_updated' fonksiyonunda beklenmedik bir hata oluştu: {e}")

@transaction.atomic
def handle_subscription_cancelled(event_data):
    """Abonelik iptal edildiğinde çağrılır"""
    lemon_subscription_id = event_data.get('data', {}).get('id')
    if not lemon_subscription_id: return logger.error("No ID in subscription_cancelled webhook")

    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        data = event_data.get('data', {}).get('attributes', {})
        
        subscription.status = 'cancelled'
        subscription.ends_at = parse_datetime(data.get('ends_at'))
        subscription.save()

        subscription.user.subscription_expiry = subscription.ends_at
        subscription.user.save(update_fields=['subscription_expiry'])
        logger.info(f"Subscription cancelled for {subscription.user.email}, access ends at: {subscription.ends_at}")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_cancelled: {str(e)}")

@transaction.atomic
def handle_subscription_expired(event_data):
    """Abonelik süresi dolduğunda çağrılır"""
    lemon_subscription_id = event_data.get('data', {}).get('id')
    if not lemon_subscription_id: return logger.error("No ID in subscription_expired webhook")

    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        user = subscription.user
        
        subscription.status = 'expired'
        subscription.save()
        
        user.subscription_type = 'free'
        user.subscription_expiry = None
        user.save(update_fields=['subscription_type', 'subscription_expiry'])
        logger.info(f"Subscription expired for {user.email}, downgraded to free.")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_expired: {str(e)}")

@transaction.atomic
def handle_subscription_resumed(event_data):
    """İptal edilmiş abonelik devam ettirildiğinde çağrılır"""
    lemon_subscription_id = event_data.get('data', {}).get('id')
    if not lemon_subscription_id: return logger.error("No ID in subscription_resumed webhook")

    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        user = subscription.user
        data = event_data.get('data', {}).get('attributes', {})
        subscription_type = determine_subscription_type(subscription.lemon_squeezy_product_id)
        
        renews_at = parse_datetime(data.get('renews_at'))
        ends_at = parse_datetime(data.get('ends_at'))
        
        subscription.status = 'active'
        subscription.renews_at = renews_at
        subscription.ends_at = ends_at
        subscription.save()
        
        user.subscription_type = subscription_type
        user.subscription_expiry = ends_at or renews_at
        user.save(update_fields=['subscription_type', 'subscription_expiry'])
        logger.info(f"Subscription resumed for {user.email}, type: {subscription_type}")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_resumed: {str(e)}")

@transaction.atomic
def handle_subscription_paused(event_data):
    """Abonelik duraklatıldığında çağrılır"""
    lemon_subscription_id = event_data.get('data', {}).get('id')
    if not lemon_subscription_id: return logger.error("No ID in subscription_paused webhook")

    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        subscription.status = 'paused'
        subscription.save()
        logger.info(f"Subscription paused for user: {subscription.user.email}")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_paused: {str(e)}")

@transaction.atomic
def handle_subscription_unpaused(event_data):
    """Abonelik duraklatması kaldırıldığında çağrılır"""
    lemon_subscription_id = event_data.get('data', {}).get('id')
    if not lemon_subscription_id: return logger.error("No ID in subscription_unpaused webhook")

    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        subscription.status = 'active'
        subscription.save()
        logger.info(f"Subscription unpaused for user: {subscription.user.email}")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_unpaused: {str(e)}")

@transaction.atomic
def handle_subscription_payment_success(event_data):
    """Yenileme ödemesi başarılı olduğunda"""
    data = event_data.get('data', {}).get('attributes', {})
    lemon_subscription_id = data.get('subscription_id')
    if not lemon_subscription_id: return logger.error("No subscription_id in payment_success webhook")
    
    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        user = subscription.user
        
        subscription.status = 'active'
        subscription.renews_at = parse_datetime(data.get('renews_at'))
        subscription.ends_at = None
        subscription.save()
        
        user.subscription_expiry = subscription.renews_at
        user.save(update_fields=['subscription_expiry'])
        
        Payment.objects.create(
            user=user,
            subscription=subscription,
            lemon_squeezy_order_id=data.get('order_id'),
            amount=Decimal(data.get('total', 0)) / 100,
            currency=data.get('currency', 'USD'),
            status='completed',
            payment_date=timezone.now()
        )
        logger.info(f"Subscription payment success for {user.email}. Next renewal: {subscription.renews_at}")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_payment_success: {str(e)}")

@transaction.atomic
def handle_subscription_payment_failed(event_data):
    """Yenileme ödemesi başarısız olduğunda"""
    data = event_data.get('data', {}).get('attributes', {})
    lemon_subscription_id = data.get('subscription_id')
    if not lemon_subscription_id: return logger.error("No subscription_id in payment_failed webhook")
    
    try:
        subscription = Subscription.objects.get(lemon_squeezy_subscription_id=lemon_subscription_id)
        subscription.status = 'past_due'
        subscription.save()
        logger.warning(f"Subscription payment failed for {subscription.user.email}. Status set to past_due.")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription not found for ID: {lemon_subscription_id}")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_payment_failed: {str(e)}")

def handle_subscription_plan_changed(event_data):
    """Kullanıcı plan değiştirdiğinde. Bu genellikle `subscription_updated` ile aynıdır."""
    logger.info("Handling 'subscription_plan_changed' by calling 'handle_subscription_updated'.")
    return handle_subscription_updated(event_data)

@transaction.atomic
def handle_subscription_payment_refunded(event_data):
    """Bir yenileme ödemesi iade edildiğinde"""
    data = event_data.get('data', {}).get('attributes', {})
    order_id = data.get('order_id')
    if not order_id: return logger.error("No order_id in payment_refunded webhook")

    try:
        payment = Payment.objects.get(lemon_squeezy_order_id=order_id)
        payment.status = 'refunded'
        payment.save()
        logger.info(f"Payment for order {order_id} refunded for user {payment.user.email}.")

        if payment.subscription:
            subscription = payment.subscription
            user = subscription.user
            subscription.status = 'cancelled'
            subscription.save()
            user.subscription_type = 'free'
            user.subscription_expiry = None
            user.save(update_fields=['subscription_type', 'subscription_expiry'])
            logger.warning(f"User {user.email} downgraded to free due to refund.")

    except Payment.DoesNotExist:
        logger.error(f"Payment with order ID {order_id} not found for refund.")
    except Exception as e:
        logger.exception(f"Error in handle_subscription_payment_refunded: {str(e)}")

@transaction.atomic
def handle_order_created(event_data):
    """Yeni bir sipariş oluşturulduğunda çağrılır (idempotent hale getirildi)"""
    data = event_data.get('data', {}).get('attributes', {})
    user_email = data.get('user_email')
    if not user_email: return logger.error("No email in order_created webhook")
    
    try:
        user = User.objects.get(email=user_email)
        lemon_order_id = event_data.get('data', {}).get('id')
        
        payment, created = Payment.objects.get_or_create(
            lemon_squeezy_order_id=lemon_order_id,
            defaults={
                'user': user,
                'amount': Decimal(data.get('total', 0)) / 100,
                'currency': data.get('currency', 'USD'),
                'status': 'completed',
                'receipt_url': data.get('urls', {}).get('receipt'),
                'payment_date': timezone.now()
            }
        )
        
        if created:
            if hasattr(user, 'subscription'):
                payment.subscription = user.subscription
                payment.save()
            logger.info(f"Order created for {user.email}, amount: {payment.amount} {payment.currency}")
        else:
            logger.info(f"Duplicate order_created event for order ID {lemon_order_id}. Ignored.")
            
    except User.DoesNotExist:
        logger.error(f"User not found for email: {user_email}")
    except Exception as e:
        logger.exception(f"Error in handle_order_created: {str(e)}")

@transaction.atomic
def handle_order_refunded(event_data):
    """Sipariş iade edildiğinde çağrılır"""
    lemon_order_id = event_data.get('data', {}).get('id')
    if not lemon_order_id: return logger.error("No order ID in order_refunded webhook")

    try:
        payment = Payment.objects.get(lemon_squeezy_order_id=lemon_order_id)
        payment.status = 'refunded'
        payment.save()
        logger.info(f"Order refunded for {payment.user.email}, order ID: {lemon_order_id}")
    except Payment.DoesNotExist:
        logger.error(f"Payment not found for order ID: {lemon_order_id}")
    except Exception as e:
        logger.exception(f"Error in handle_order_refunded: {str(e)}")
