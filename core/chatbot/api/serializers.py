# chatbot/serializers.py
from rest_framework import serializers
from django.utils import timezone
from ..models import ChatSession, ChatMessage, UserChatSettings, ChatFeedback, ChatUsageStats

class ChatMessageSerializer(serializers.ModelSerializer):
    """
    Chat mesajları için serializer
    """
    formatted_timestamp = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatMessage
        fields = [
            'id', 'content', 'is_user', 'timestamp', 'formatted_timestamp',
            'response_time', 'context_used'
        ]
        read_only_fields = ['id', 'timestamp', 'response_time', 'context_used']
    
    def get_formatted_timestamp(self, obj):
        """
        Timestamp'i kullanıcı dostu formatta döndür
        """
        return obj.timestamp.strftime('%H:%M')

class ChatSessionSerializer(serializers.ModelSerializer):
    """
    Chat oturumları için serializer
    """
    message_count = serializers.ReadOnlyField()
    last_message_preview = serializers.SerializerMethodField()
    formatted_created_at = serializers.SerializerMethodField()
    formatted_updated_at = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = [
            'id', 'title', 'created_at', 'updated_at', 'is_active',
            'message_count', 'last_message_preview', 'formatted_created_at',
            'formatted_updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'message_count']
    
    def get_last_message_preview(self, obj):
        """
        Son mesajın önizlemesini döndür
        """
        last_message = obj.messages.order_by('-timestamp').first()
        if last_message:
            preview = last_message.content[:60]
            if len(last_message.content) > 60:
                preview += "..."
            return {
                'content': preview,
                'is_user': last_message.is_user,
                'timestamp': last_message.timestamp
            }
        return None
    
    def get_formatted_created_at(self, obj):
        """
        Oluşturulma tarihini formatla
        """
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff.days == 0:
            return "Bugün"
        elif diff.days == 1:
            return "Dün"
        elif diff.days < 7:
            return f"{diff.days} gün önce"
        else:
            return obj.created_at.strftime('%d/%m/%Y')
    
    def get_formatted_updated_at(self, obj):
        """
        Güncellenme tarihini formatla
        """
        return obj.updated_at.strftime('%H:%M')

class CreateChatSessionSerializer(serializers.ModelSerializer):
    """
    Yeni chat oturumu oluşturma serializer
    """
    class Meta:
        model = ChatSession
        fields = ['title']
    
    def validate_title(self, value):
        """
        Başlık validasyonu
        """
        if value and len(value.strip()) < 1:
            raise serializers.ValidationError("Başlık en az 1 karakter olmalıdır.")
        if value and len(value) > 255:
            raise serializers.ValidationError("Başlık en fazla 255 karakter olabilir.")
        return value.strip() if value else None

class SendMessageSerializer(serializers.Serializer):
    """
    Mesaj gönderme serializer
    """
    message = serializers.CharField(max_length=4000, allow_blank=False)
    
    def validate_message(self, value):
        """
        Mesaj validasyonu
        """
        if not value or not value.strip():
            raise serializers.ValidationError("Mesaj boş olamaz.")
        
        if len(value.strip()) < 1:
            raise serializers.ValidationError("Mesaj en az 1 karakter olmalıdır.")
        
        if len(value) > 4000:
            raise serializers.ValidationError("Mesaj en fazla 4000 karakter olabilir.")
        
        return value.strip()

class UserChatSettingsSerializer(serializers.ModelSerializer):
    """
    Kullanıcı chat ayarları serializer
    """
    class Meta:
        model = UserChatSettings
        fields = [
            'auto_title_generation', 'save_chat_history', 'max_stored_sessions',
            'context_length', 'response_style'
        ]
    
    def validate_context_length(self, value):
        """
        Context length validasyonu
        """
        if value < 1:
            raise serializers.ValidationError("Context length en az 1 olmalıdır.")
        if value > 20:
            raise serializers.ValidationError("Context length en fazla 20 olabilir.")
        return value
    
    def validate_max_stored_sessions(self, value):
        """
        Maksimum oturum sayısı validasyonu
        """
        if value < 1:
            raise serializers.ValidationError("Maksimum oturum sayısı en az 1 olmalıdır.")
        if value > 1000:
            raise serializers.ValidationError("Maksimum oturum sayısı en fazla 1000 olabilir.")
        return value

class ChatFeedbackSerializer(serializers.ModelSerializer):
    """
    Chat feedback serializer
    """
    message_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = ChatFeedback
        fields = ['id', 'message_id', 'rating', 'comment', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def validate_rating(self, value):
        """
        Rating validasyonu
        """
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating 1 ile 5 arasında olmalıdır.")
        return value
    
    def validate_message_id(self, value):
        """
        Mesaj ID validasyonu
        """
        try:
            message = ChatMessage.objects.get(id=value, is_user=False)
            return message
        except ChatMessage.DoesNotExist:
            raise serializers.ValidationError("Geçersiz mesaj ID'si.")
    
    def create(self, validated_data):
        """
        Feedback oluşturma
        """
        message = validated_data.pop('message_id')
        validated_data['message'] = message
        return super().create(validated_data)

class ChatUsageStatsSerializer(serializers.ModelSerializer):
    """
    Chat kullanım istatistikleri serializer
    """
    subscription_type = serializers.CharField(source='user.subscription_type', read_only=True)
    monthly_limit = serializers.SerializerMethodField()
    remaining_messages = serializers.SerializerMethodField()
    usage_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatUsageStats
        fields = [
            'total_messages_sent', 'total_sessions_created', 'monthly_messages_sent',
            'monthly_sessions_created', 'last_chat_date', 'subscription_type',
            'monthly_limit', 'remaining_messages', 'usage_percentage'
        ]
        read_only_fields = '__all__'
    
    def get_monthly_limit(self, obj):
        """
        Aylık limit hesaplama
        """
        subscription_type = obj.user.subscription_type
        if subscription_type == 'free':
            return 50
        elif subscription_type == 'basic':
            return 500
        else:  # premium
            return None  # Unlimited
    
    def get_remaining_messages(self, obj):
        """
        Kalan mesaj sayısı hesaplama
        """
        monthly_limit = self.get_monthly_limit(obj)
        if monthly_limit is None:
            return None  # Unlimited
        return max(0, monthly_limit - obj.monthly_messages_sent)
    
    def get_usage_percentage(self, obj):
        """
        Kullanım yüzdesi hesaplama
        """
        monthly_limit = self.get_monthly_limit(obj)
        if monthly_limit is None:
            return 0  # Unlimited için 0% göster
        if monthly_limit == 0:
            return 100
        return min(100, (obj.monthly_messages_sent / monthly_limit) * 100)

class ChatSessionDetailSerializer(ChatSessionSerializer):
    """
    Chat oturumu detay serializer (mesajlarla birlikte)
    """
    messages = ChatMessageSerializer(many=True, read_only=True)
    
    class Meta(ChatSessionSerializer.Meta):
        fields = ChatSessionSerializer.Meta.fields + ['messages']

class ChatSessionWithLastMessagesSerializer(ChatSessionSerializer):
    """
    Son birkaç mesajla birlikte chat oturumu serializer
    """
    recent_messages = serializers.SerializerMethodField()
    
    class Meta(ChatSessionSerializer.Meta):
        fields = ChatSessionSerializer.Meta.fields + ['recent_messages']
    
    def get_recent_messages(self, obj):
        """
        Son 5 mesajı döndür
        """
        recent_messages = obj.messages.order_by('-timestamp')[:5]
        return ChatMessageSerializer(recent_messages, many=True).data

class SimpleChatSessionSerializer(serializers.ModelSerializer):
    """
    Basit chat oturumu serializer (liste görünümü için)
    """
    preview = serializers.SerializerMethodField()
    time_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'preview', 'time_ago', 'updated_at']
    
    def get_preview(self, obj):
        """
        İlk kullanıcı mesajının önizlemesi
        """
        return obj.get_first_message_preview()
    
    def get_time_ago(self, obj):
        """
        Ne kadar süre önce güncellendi
        """
        now = timezone.now()
        diff = now - obj.updated_at
        
        if diff.total_seconds() < 60:
            return "Az önce"
        elif diff.total_seconds() < 3600:
            minutes = int(diff.total_seconds() / 60)
            return f"{minutes}dk önce"
        elif diff.days == 0:
            hours = int(diff.total_seconds() / 3600)
            return f"{hours}sa önce"
        elif diff.days == 1:
            return "Dün"
        elif diff.days < 7:
            return f"{diff.days} gün önce"
        elif diff.days < 30:
            weeks = diff.days // 7
            return f"{weeks} hafta önce"
        else:
            return obj.updated_at.strftime('%d/%m/%Y')