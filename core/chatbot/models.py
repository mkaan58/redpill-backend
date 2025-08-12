# chatbot/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()

class ChatSession(models.Model):
    """
    Kullanıcının chat oturumlarını temsil eden model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'
    
    def __str__(self):
        return f"{self.user.email} - {self.title or 'Untitled Chat'}"
    
    @property
    def message_count(self):
        return self.messages.count()
    
    def get_first_message_preview(self):
        """İlk kullanıcı mesajının önizlemesini döndürür"""
        first_message = self.messages.filter(is_user=True).first()
        if first_message:
            return first_message.content[:50] + ('...' if len(first_message.content) > 50 else '')
        return "New Chat"

class ChatMessage(models.Model):
    """
    Chat mesajlarını temsil eden model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField()
    is_user = models.BooleanField(default=True)  # True: kullanıcı mesajı, False: AI cevabı
    timestamp = models.DateTimeField(default=timezone.now)
    
    # RAG ile ilgili ek bilgiler
    context_used = models.TextField(blank=True, null=True)  # Kullanılan RAG context
    response_time = models.FloatField(blank=True, null=True)  # Cevap süresi (saniye)
    
    class Meta:
        ordering = ['timestamp']
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'
    
    def __str__(self):
        message_type = "User" if self.is_user else "AI"
        preview = self.content[:30] + ('...' if len(self.content) > 30 else '')
        return f"{message_type}: {preview}"

class UserChatSettings(models.Model):
    """
    Kullanıcının chat ayarlarını temsil eden model
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='chat_settings')
    
    # Chat tercihleri
    auto_title_generation = models.BooleanField(default=True)  # Otomatik başlık oluşturma
    save_chat_history = models.BooleanField(default=True)  # Chat geçmişini kaydetme
    max_stored_sessions = models.IntegerField(default=50)  # Maksimum kaydedilen oturum sayısı
    
    # RAG ayarları
    context_length = models.IntegerField(default=6)  # Kullanılacak döküman sayısı
    response_style = models.CharField(
        max_length=20,
        choices=[
            ('direct', 'Direkt'),
            ('detailed', 'Detaylı'), 
            ('balanced', 'Dengeli'),
        ],
        default='balanced'
    )
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'User Chat Settings'
        verbose_name_plural = 'User Chat Settings'
    
    def __str__(self):
        return f"Chat Settings - {self.user.email}"

class ChatFeedback(models.Model):
    """
    Kullanıcı geri bildirimlerini temsil eden model
    """
    RATING_CHOICES = [
        (1, 'Çok Kötü'),
        (2, 'Kötü'),
        (3, 'Orta'),
        (4, 'İyi'),
        (5, 'Mükemmel'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_feedbacks')
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name='feedbacks')
    rating = models.IntegerField(choices=RATING_CHOICES)
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        verbose_name = 'Chat Feedback'
        verbose_name_plural = 'Chat Feedbacks'
        unique_together = ['user', 'message']  # Her mesaj için bir kullanıcı sadece bir kez feedback verebilir
    
    def __str__(self):
        return f"Feedback: {self.rating}/5 - {self.user.email}"

class ChatUsageStats(models.Model):
    """
    Kullanıcının chat kullanım istatistiklerini temsil eden model
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='chat_stats')
    
    # Kullanım istatistikleri
    total_messages_sent = models.IntegerField(default=0)
    total_sessions_created = models.IntegerField(default=0)
    total_chat_time_minutes = models.IntegerField(default=0)
    
    # Bu ay ki kullanım (abonelik kontrolü için)
    monthly_messages_sent = models.IntegerField(default=0)
    monthly_sessions_created = models.IntegerField(default=0)
    last_reset_date = models.DateField(default=timezone.now)
    
    # En son aktivite
    last_chat_date = models.DateTimeField(blank=True, null=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Chat Usage Stats'
        verbose_name_plural = 'Chat Usage Stats'
    
    def __str__(self):
        return f"Stats - {self.user.email}: {self.total_messages_sent} messages"
    
    def reset_monthly_stats(self):
        """Aylık istatistikleri sıfırla"""
        self.monthly_messages_sent = 0
        self.monthly_sessions_created = 0
        self.last_reset_date = timezone.now().date()
        self.save()
    
    def increment_message_count(self):
        """Mesaj sayısını artır"""
        self.total_messages_sent += 1
        self.monthly_messages_sent += 1
        self.last_chat_date = timezone.now()
        self.save()
    
    def increment_session_count(self):
        """Oturum sayısını artır"""
        self.total_sessions_created += 1
        self.monthly_sessions_created += 1
        self.save()
    
    def check_monthly_limits(self):
        """Aylık limitleri kontrol et"""
        # Bu fonksiyon abonelik tipine göre limit kontrolü yapabilir
        user_subscription = self.user.subscription_type
        
        if user_subscription == 'free':
            return self.monthly_messages_sent < 50  # Free kullanıcılar için 50 mesaj
        elif user_subscription == 'basic':
            return self.monthly_messages_sent < 500  # Basic kullanıcılar için 500 mesaj
        elif user_subscription == 'premium':
            return True  # Premium kullanıcılar için sınırsız
        
        return False