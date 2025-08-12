# chatbot/views.py
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.conf import settings
import time
import traceback
import json
import re
from datetime import datetime, timedelta

from ..models import ChatSession, ChatMessage, UserChatSettings, ChatFeedback, ChatUsageStats
from .serializers import (
    ChatSessionSerializer, 
    ChatMessageSerializer, 
    CreateChatSessionSerializer,
    SendMessageSerializer,
    UserChatSettingsSerializer,
    ChatFeedbackSerializer
)

# RAG sistemi import (mevcut RAG kodunuzdan)
import sys
import os

# RAG sistemini import et ve initialize et
try:
    # Proje kök dizininden RAG dosyasını import et
    rag_path = settings.BASE_DIR  # Django proje kök dizini
    if rag_path not in sys.path:
        sys.path.append(str(rag_path))
    
    from .advanced_rag import AdvancedRAG  # RAG kodunuzdaki sınıf
    
    # RAG sistemini initialize et
    rag_system = AdvancedRAG()
    RAG_AVAILABLE = True
    print("✅ RAG System loaded successfully")
    
except Exception as e:
    print(f"⚠️ RAG System could not be loaded: {e}")
    RAG_AVAILABLE = False
    rag_system = None

class ChatSessionListCreateView(generics.ListCreateAPIView):
    """
    Chat oturumlarını listele ve yeni oturum oluştur
    GET: Kullanıcının aktif chat oturumlarını döndürür
    POST: Yeni chat oturumu oluşturur
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CreateChatSessionSerializer
        return ChatSessionSerializer
    
    def get_queryset(self):
        return ChatSession.objects.filter(
            user=self.request.user,
            is_active=True
        ).order_by('-updated_at')[:50]  # Son 50 oturum
    
    def perform_create(self, serializer):
        # Kullanım istatistiklerini al veya oluştur
        stats, created = ChatUsageStats.objects.get_or_create(user=self.request.user)
        
        # Aylık limit kontrolü yap
        if not stats.check_monthly_limits():
            user_subscription = self.request.user.subscription_type
            if user_subscription == 'free':
                limit = 50
            elif user_subscription == 'basic':
                limit = 500
            else:
                limit = "unlimited"
            
            from rest_framework import serializers
            raise serializers.ValidationError(
                f"Bu ay için chat limitinize ulaştınız. "
                f"Mevcut planınız ({user_subscription}): {limit} mesaj/ay. "
                f"Lütfen planınızı yükseltin."
            )
        
        # Session'ı oluştur ve istatistikleri güncelle
        session = serializer.save(user=self.request.user)
        stats.increment_session_count()

class ChatSessionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Belirli bir chat oturumunu görüntüle, güncelle veya sil
    GET: Session detaylarını döndürür
    PUT/PATCH: Session bilgilerini günceller (başlık vb.)
    DELETE: Session'ı soft delete yapar
    """
    serializer_class = ChatSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user)
    
    def perform_destroy(self, instance):
        # Hard delete yerine soft delete yap
        instance.is_active = False
        instance.save()

class ChatMessagesView(generics.ListAPIView):
    """
    Belirli bir chat oturumunun mesajlarını listele
    Session ID'ye göre o oturumdaki tüm mesajları kronolojik sırayla döndürür
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        session_id = self.kwargs['session_id']
        session = get_object_or_404(
            ChatSession, 
            id=session_id, 
            user=self.request.user,
            is_active=True
        )
        return ChatMessage.objects.filter(session=session).order_by('timestamp')

class SendMessageView(APIView):
    """
    Chat oturumuna mesaj gönder ve AI cevabını al
    Kullanıcı mesajını kaydeder, RAG sistemi ile cevap üretir ve AI cevabını da kaydeder
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, session_id):
        try:
            # Session kontrolü - aktif ve kullanıcıya ait olmalı
            session = get_object_or_404(
                ChatSession, 
                id=session_id, 
                user=request.user,
                is_active=True
            )
            
            # Kullanım limiti kontrolü
            stats, created = ChatUsageStats.objects.get_or_create(user=request.user)
            if not stats.check_monthly_limits():
                return Response({
                    'error': 'Bu ay için mesaj limitinize ulaştınız. Lütfen planınızı yükseltin.',
                    'error_code': 'MONTHLY_LIMIT_EXCEEDED'
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            # Request data validation
            serializer = SendMessageSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            user_message_content = serializer.validated_data['message']
            
            # Kullanıcı mesajını kaydet
            user_message = ChatMessage.objects.create(
                session=session,
                content=user_message_content,
                is_user=True,
                timestamp=timezone.now()
            )
            
            # Chat ayarlarını al
            chat_settings, _ = UserChatSettings.objects.get_or_create(user=request.user)
            
            # Session'daki mevcut mesajları al (memory için)
            session_messages = ChatMessage.objects.filter(session=session)
            
            # RAG ile AI cevabı üret
            start_time = time.time()
            ai_response, context_used = self.generate_ai_response(
                user_message_content, 
                chat_settings,
                session_messages
            )
            response_time = time.time() - start_time
            
            # AI cevabını kaydet
            ai_message = ChatMessage.objects.create(
                session=session,
                content=ai_response,
                is_user=False,
                timestamp=timezone.now(),
                context_used=context_used[:2000] if context_used else None,  # Context'i kısıt
                response_time=response_time
            )
            
            # Session'ı güncelle
            session.updated_at = timezone.now()
            
            # Eğer session'ın title'ı yoksa ve auto-title açıksa, title oluştur
            if not session.title and chat_settings.auto_title_generation:
                session.title = self.generate_session_title(user_message_content)
            
            session.save()
            
            # İstatistikleri güncelle
            stats.increment_message_count()
            
            # Response döndür
            return Response({
                'user_message': ChatMessageSerializer(user_message).data,
                'ai_message': ChatMessageSerializer(ai_message).data,
                'response_time': round(response_time, 2),
                'session': ChatSessionSerializer(session).data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print(f"❌ Chat error: {e}")
            print(traceback.format_exc())
            return Response({
                'error': 'Bir hata oluştu. Lütfen tekrar deneyin.',
                'error_code': 'INTERNAL_ERROR',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def generate_ai_response(self, user_message, chat_settings, session_messages=None):
        """
        RAG sistemini kullanarak AI cevabı oluştur
        """
        context_used = ""
        
        if not RAG_AVAILABLE or not rag_system:
            return "⚠️ AI sistemi şu anda kullanılamıyor. Lütfen daha sonra tekrar deneyin.", ""
        
        try:
            # Chat memory için son 15 mesajı ekle
            memory_context = ""
            if session_messages:
                recent_messages = session_messages.order_by('-timestamp')[:15]
                memory_parts = []
                for msg in reversed(recent_messages):  # Kronolojik sıra için ters çevir
                    role = "User" if msg.is_user else "Assistant"
                    memory_parts.append(f"{role}: {msg.content}")
                
                if memory_parts:
                    memory_context = f"\n\nÖnceki konuşma geçmişi:\n" + "\n".join(memory_parts[-14:])  # Son 14 mesaj (current hariç)
            
            # Enhanced prompt with memory
            enhanced_message = user_message + memory_context
            
            # RAG sisteminden cevap al
            print(f"🤖 Generating response for: {user_message[:50]}...")
            response = rag_system.answer(enhanced_message)
            
            # Cevabı formatla - Structured ve emoji'li format
            formatted_response = self.format_ai_response(response)
            
            # Context bilgisini al (eğer RAG sisteminde mevcutsa)
            if hasattr(rag_system, 'last_retrieved_context'):
                context_used = rag_system.last_retrieved_context
            elif hasattr(rag_system, 'last_context'):
                context_used = rag_system.last_context
            
            print(f"✅ Response generated successfully: {len(formatted_response)} chars")
            return formatted_response, context_used
            
        except Exception as e:
            print(f"❌ RAG Error: {e}")
            error_msg = f"❌ Cevap oluşturulurken bir hata oluştu. Lütfen sorunuzu yeniden ifade etmeyi deneyin."
            if settings.DEBUG:
                error_msg += f"\n\nDetay: {str(e)}"
            return error_msg, ""
    
    def format_ai_response(self, response):
        """
        AI cevabını ChatGPT tarzında structured format'a çevir
        """
        try:
            # Basit formatlama kuralları
            formatted = response
            
            # ** bold ** işaretlerini kaldır ve başlık yap
            formatted = re.sub(r'\*\*(.*?)\*\*', r'## 🎯 \1\n', formatted)
            
            # Numaralı listeler için emoji ekle
            formatted = re.sub(r'^(\d+)\.\s*(.+)$', r'✅ **\1.** \2', formatted, flags=re.MULTILINE)
            
            # Önemli noktaları vurgula
            formatted = re.sub(r'^-\s*(.+)$', r'🔸 \1', formatted, flags=re.MULTILINE)
            
            # Uyarılar için emoji
            formatted = re.sub(r'(Önemli|Dikkat|Uyarı|Not):', r'⚠️ **\1:**', formatted)
            
            # Olumlu ifadeler için emoji
            formatted = re.sub(r'(Sonuç|Tavsiye|Öneri):', r'💡 **\1:**', formatted)
            
            # Satır başlarında paragraf boşlukları ekle
            lines = formatted.split('\n')
            formatted_lines = []
            
            for i, line in enumerate(lines):
                if line.strip():
                    # Başlık sonrası boşluk
                    if line.startswith('##'):
                        if i > 0:
                            formatted_lines.append('')
                        formatted_lines.append(line)
                        formatted_lines.append('')
                    else:
                        formatted_lines.append(line)
                else:
                    formatted_lines.append(line)
            
            return '\n'.join(formatted_lines)
            
        except Exception as e:
            print(f"Formatting error: {e}")
            return response  # Formatlama başarısız olursa orijinal response'u döndür
    
    def generate_session_title(self, first_message):
        """
        İlk mesajdan session başlığı oluştur
        Gelecekte AI ile daha akıllı başlık üretimi yapılabilir
        """
        # Basit başlık oluşturma
        title = first_message.strip()
        
        # Uzun mesajları kısalt
        if len(title) > 50:
            title = title[:47] + "..."
        
        # Boş veya çok kısa mesajlar için default başlık
        if len(title.strip()) < 3:
            title = f"Chat {timezone.now().strftime('%d/%m %H:%M')}"
        
        return title

class UserChatSettingsView(generics.RetrieveUpdateAPIView):
    """
    Kullanıcının chat ayarlarını görüntüle ve güncelle
    GET: Mevcut ayarları döndürür
    PUT/PATCH: Ayarları günceller
    """
    serializer_class = UserChatSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        settings_obj, created = UserChatSettings.objects.get_or_create(user=self.request.user)
        return settings_obj

class ChatUsageStatsView(APIView):
    """
    Kullanıcının chat kullanım istatistiklerini görüntüle
    Aylık ve toplam kullanım bilgileri, kalan limit bilgileri döndürür
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        stats, created = ChatUsageStats.objects.get_or_create(user=request.user)
        
        # Ay başında istatistikleri sıfırla
        now = timezone.now().date()
        if stats.last_reset_date.month != now.month or stats.last_reset_date.year != now.year:
            stats.reset_monthly_stats()
        
        # Limit bilgilerini hesapla
        user_subscription = request.user.subscription_type
        if user_subscription == 'free':
            monthly_limit = 50
        elif user_subscription == 'basic':
            monthly_limit = 500
        else:
            monthly_limit = None  # Unlimited for premium
        
        # Remaining messages hesapla
        remaining_messages = None
        if monthly_limit:
            remaining_messages = max(0, monthly_limit - stats.monthly_messages_sent)
        
        return Response({
            'total_messages_sent': stats.total_messages_sent,
            'total_sessions_created': stats.total_sessions_created,
            'monthly_messages_sent': stats.monthly_messages_sent,
            'monthly_sessions_created': stats.monthly_sessions_created,
            'monthly_limit': monthly_limit,
            'remaining_messages': remaining_messages,
            'subscription_type': user_subscription,
            'last_chat_date': stats.last_chat_date,
            'is_limit_reached': not stats.check_monthly_limits()
        })

class ChatFeedbackView(APIView):
    """
    Chat mesajları için kullanıcı feedback'i toplama
    POST: Yeni feedback ekle veya mevcut feedback'i güncelle
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = ChatFeedbackSerializer(data=request.data)
        if serializer.is_valid():
            # Mesajın kullanıcıya ait olduğunu kontrol et
            message = serializer.validated_data['message']
            if message.session.user != request.user:
                return Response({
                    'error': 'Bu mesaja feedback veremezsiniz.',
                    'error_code': 'UNAUTHORIZED_FEEDBACK'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Feedback oluştur veya güncelle
            feedback, created = ChatFeedback.objects.update_or_create(
                user=request.user,
                message=message,
                defaults={
                    'rating': serializer.validated_data['rating'],
                    'comment': serializer.validated_data.get('comment', '')
                }
            )
            
            return Response({
                'message': 'Feedback kaydedildi.' if created else 'Feedback güncellendi.',
                'feedback': ChatFeedbackSerializer(feedback).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def clear_chat_history(request):
    """
    Kullanıcının tüm chat geçmişini temizle (soft delete)
    """
    try:
        # Tüm aktif session'ları soft delete yap
        updated_count = ChatSession.objects.filter(
            user=request.user, 
            is_active=True
        ).update(is_active=False)
        
        return Response({
            'message': f'{updated_count} chat oturumu silindi.',
            'cleared_sessions': updated_count
        })
        
    except Exception as e:
        return Response({
            'error': 'Chat geçmişi silinirken bir hata oluştu.',
            'detail': str(e) if settings.DEBUG else None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def chat_health_check(request):
    """
    Chat sisteminin durumunu kontrol et
    RAG sistemi durumu, kullanıcı limitleri vb.
    """
    try:
        # RAG sistemi durumu
        rag_status = "active" if RAG_AVAILABLE else "inactive"
        
        # Kullanıcı istatistikleri
        stats, _ = ChatUsageStats.objects.get_or_create(user=request.user)
        
        # Database durumu
        try:
            session_count = ChatSession.objects.filter(user=request.user, is_active=True).count()
            db_status = "active"
        except:
            session_count = 0
            db_status = "error"
        
        return Response({
            'status': 'healthy',
            'rag_system': rag_status,
            'database': db_status,
            'user_session_count': session_count,
            'monthly_messages_sent': stats.monthly_messages_sent,
            'limits_ok': stats.check_monthly_limits(),
            'timestamp': timezone.now()
        })
        
    except Exception as e:
        return Response({
            'status': 'error',
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def edit_message(request, message_id):
    """
    Kullanıcı mesajını düzenle ve yeni AI cevabı al
    """
    try:
        # Mesajı bul ve kontrol et
        user_message = get_object_or_404(
            ChatMessage,
            id=message_id,
            session__user=request.user,
            is_user=True  # Sadece kullanıcı mesajları düzenlenebilir
        )
        
        # Yeni mesaj içeriğini al
        new_content = request.data.get('message', '').strip()
        if not new_content:
            return Response({
                'error': 'Mesaj içeriği boş olamaz.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Bu mesajdan sonraki tüm mesajları sil (yeniden oluşturulacak)
        ChatMessage.objects.filter(
            session=user_message.session,
            timestamp__gt=user_message.timestamp
        ).delete()
        
        # Kullanıcı mesajını güncelle
        user_message.content = new_content
        user_message.timestamp = timezone.now()
        user_message.save()
        
        # Chat ayarlarını al
        chat_settings, _ = UserChatSettings.objects.get_or_create(user=request.user)
        
        # Session'daki mevcut mesajları al (memory için)
        session_messages = ChatMessage.objects.filter(session=user_message.session)
        
        # Yeni AI cevabı üret
        start_time = time.time()
        ai_response, context_used = SendMessageView().generate_ai_response(
            new_content,
            chat_settings,
            session_messages
        )
        response_time = time.time() - start_time
        
        # Yeni AI mesajı oluştur
        ai_message = ChatMessage.objects.create(
            session=user_message.session,
            content=ai_response,
            is_user=False,
            timestamp=timezone.now(),
            context_used=context_used[:2000] if context_used else None,
            response_time=response_time
        )
        
        # Session'ı güncelle
        user_message.session.updated_at = timezone.now()
        user_message.session.save()
        
        return Response({
            'message': 'Mesaj başarıyla güncellendi.',
            'user_message': ChatMessageSerializer(user_message).data,
            'ai_message': ChatMessageSerializer(ai_message).data,
            'response_time': round(response_time, 2)
        })
        
    except Exception as e:
        return Response({
            'error': 'Mesaj güncellenirken bir hata oluştu.',
            'detail': str(e) if settings.DEBUG else None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def regenerate_response(request, message_id):
    """
    AI cevabını yeniden üret
    """
    try:
        # Mesajı bul ve kontrol et
        ai_message = get_object_or_404(
            ChatMessage,
            id=message_id,
            session__user=request.user,
            is_user=False  # AI mesajı olmalı
        )
        
        # Son kullanıcı mesajını bul
        user_message = ChatMessage.objects.filter(
            session=ai_message.session,
            timestamp__lt=ai_message.timestamp,
            is_user=True
        ).order_by('-timestamp').first()
        
        if not user_message:
            return Response({
                'error': 'İlgili kullanıcı mesajı bulunamadı.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Chat ayarlarını al
        chat_settings, _ = UserChatSettings.objects.get_or_create(user=request.user)
        
        # Session'daki mevcut mesajları al (memory için)
        session_messages = ChatMessage.objects.filter(session=ai_message.session)
        
        # Yeni cevap üret
        start_time = time.time()
        new_response, context_used = SendMessageView().generate_ai_response(
            user_message.content,
            chat_settings,
            session_messages
        )
        response_time = time.time() - start_time
        
        # AI mesajını güncelle
        ai_message.content = new_response
        ai_message.context_used = context_used[:2000] if context_used else None
        ai_message.response_time = response_time
        ai_message.timestamp = timezone.now()
        ai_message.save()
        
        return Response({
            'message': 'Cevap yeniden oluşturuldu.',
            'ai_message': ChatMessageSerializer(ai_message).data,
            'response_time': round(response_time, 2)
        })
        
    except Exception as e:
        return Response({
            'error': 'Cevap yeniden oluşturulurken bir hata oluştu.',
            'detail': str(e) if settings.DEBUG else None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)