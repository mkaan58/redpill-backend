# core/settings/prod.py
from .base import *
import dj_database_url
import os

DEBUG = False

ALLOWED_HOSTS = [
    'my-backend-app-un2d.onrender.com',  # Gerçek backend domain
    '127.0.0.1',
    'localhost',
    '.onrender.com',
    'spa-front-o0yw.onrender.com',  # Frontend domain
    'www.rushy.app',
    'rushy.app',
]

# Database
DATABASES = {
    'default': dj_database_url.parse(
        os.environ.get('DATABASE_URL', 
         'postgresql://spa_ozqv_user:ylYFYpqwh9bbFTqOh5FjBVkAX2fB5KXi@dpg-d144tsu3jp1c73d9dcpg-a.oregon-postgres.render.com/spa_ozqv')
    )
}

# CORS settings - Tam URL'ler ile
CORS_ALLOWED_ORIGINS = [
    'https://rushy.app',
    'https://www.rushy.app',
    'https://spa-front-o0yw.onrender.com',
    'https://my-backend-app-un2d.onrender.com',

]
# CORS settings - Tam URL'ler ile
CSRF_TRUSTED_ORIGINS = [
    'https://rushy.app',
    'https://www.rushy.app',
    'https://spa-front-o0yw.onrender.com',
    'http://localhost:3000',
    'http://localhost:8000',
    'https://my-backend-app-un2d.onrender.com'

]
# Eğer environment variable'dan geliyorsa
if os.environ.get('CORS_ALLOWED_ORIGINS'):
    CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS').split(',')

CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_ALL_ORIGINS = False  # Production'da False olmalı

# HTTPS settings
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Render proxy desteği
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_SESSION_COOKIE_AGE = 1209600  # 2 hafta (saniye cinsinden)

# Frontend URL
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://rushy.app')

# Celery ayarları
CELERY_BROKER_URL = os.environ.get('REDIS_URL')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'


# API Keys
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')



# AWS S3 Ayarları
# Bu bilgileri Render.com ortam değişkenleri olarak tanımlamalısınız!
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1') # S3 bucket'ınızın bölgesini buraya yazın, örn: 'eu-central-1'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com' # S3 URL'si

AWS_S3_USE_SSL = True
AWS_S3_VERIFY = True # SSL sertifikasını doğrula

# S3'e yüklenen MEDIA dosyaları için prefix
AWS_MEDIA_LOCATION = 'media'

# S3'e yüklenen STATIC dosyaları için prefix (Yeni ekledik!)
AWS_STATIC_LOCATION = 'static'

# STORAGES ayarları (Hem statik hem medya için S3)
STORAGES = {
    # Medya dosyaları için varsayılan depolama
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "location": AWS_MEDIA_LOCATION, # Medya dosyaları için 'media/' klasörüne yükle
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            "querystring_auth": False, # URL'de yetkilendirme parametreleri oluşturma
            "file_overwrite": False, # Aynı isimde dosya varsa üzerine yazma
            # "default_acl": "public-read", # Eğer bucket policy kullanmıyorsanız ve genel okuma izni vermek istiyorsanız
        }
    },
    # Statik dosyalar için depolama (Artık S3'i kullanıyoruz!)
    "staticfiles": {
        "BACKEND": "storages.backends.s3boto3.S3StaticStorage", # statik dosyalar için S3StaticStorage kullan
        "OPTIONS": {
            "location": AWS_STATIC_LOCATION, # Statik dosyalar için 'static/' klasörüne yükle
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            "querystring_auth": False,
            # "default_acl": "public-read", # Eğer bucket policy kullanmıyorsanız ve genel okuma izni vermek istiyorsanız
        }
    },
}

MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_MEDIA_LOCATION}/"

STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_STATIC_LOCATION}/"

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379'),
    }
}

LEMON_SQUEEZY_API_KEY = os.environ.get('LEMON_SQUEEZY_API_KEY')
LEMON_SQUEEZY_STORE_ID = os.environ.get('LEMON_SQUEEZY_STORE_ID')
LEMON_SQUEEZY_WEBHOOK_SECRET = os.environ.get('LEMON_SQUEEZY_WEBHOOK_SECRET')

LEMON_SQUEEZY_CHECKOUT_URL_BASIC = os.environ.get('LEMON_SQUEEZY_CHECKOUT_URL_BASIC')
LEMON_SQUEEZY_CHECKOUT_URL_PREMIUM = os.environ.get('LEMON_SQUEEZY_CHECKOUT_URL_PREMIUM')

# Product ID'leri - Bu değerleri Lemon Squeezy dashboard'unuzdan alıp .env dosyasına ekleyin
LEMON_SQUEEZY_BASIC_PRODUCT_ID = os.environ.get('LEMON_SQUEEZY_BASIC_PRODUCT_ID')
LEMON_SQUEEZY_PREMIUM_PRODUCT_ID = os.environ.get('LEMON_SQUEEZY_PREMIUM_PRODUCT_ID')
LEMON_SQUEEZY_BASIC_VARIANT_ID = os.environ.get('LEMON_SQUEEZY_BASIC_VARIANT_ID')
LEMON_SQUEEZY_PREMIUM_VARIANT_ID = os.environ.get('LEMON_SQUEEZY_PREMIUM_VARIANT_ID')  