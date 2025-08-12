# users/api/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
import uuid

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    """
    Kullanıcı bilgilerinin okunması ve güncellenmesi için kullanılan serializer.
    Kullanıcının şifre durumu ve sosyal giriş bilgisini hesaplayarak döndürür.
    Bu sayede frontend'de kullanıcıya gösterilecek seçenekleri dinamik olarak belirleyebiliriz.
    """
    has_password = serializers.SerializerMethodField()
    has_social_login = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'surname', 'phone_number', 'date_joined', 
                 'email_verified', 'social_provider', 'has_password', 'has_social_login','subscription_type', 'subscription_expiry']
        read_only_fields = ['id', 'date_joined', 'email_verified', 'has_password', 'has_social_login']
    
    def get_has_password(self, obj):
        return obj.has_usable_password()
        
    def get_has_social_login(self, obj):
        return bool(obj.social_provider)

class RegisterSerializer(serializers.ModelSerializer):
    """
    Kullanıcı kayıt işlemlerini yöneten serializer. 
    E-posta benzersizliğini kontrol eder, şifre doğrulaması yapar ve kayıt sonrası
    e-posta doğrulama token'ı oluşturarak kullanıcıya doğrulama e-postası gönderir.
    Kullanıcı deneyimini geliştirmek için farklı hata durumlarını özel mesajlarla ele alır.
    """
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = User
        fields = ['email', 'name', 'surname', 'password', 'password2']
        extra_kwargs = {
            'name': {'required': True},  # name alanını zorunlu yap
        }
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        
        # Email alanını normalize et
        attrs['email'] = attrs['email'].lower().strip()
        
        # Email'in benzersiz olduğunu kontrol et
        if User.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
            
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password2')
        
        # Generate verification token
        token = str(uuid.uuid4())
        
        try:
            user = User.objects.create_user(
                email=validated_data['email'],
                name=validated_data.get('name', ''),
                surname=validated_data.get('surname', ''),
                password=validated_data['password'],
                email_verification_token=token,
                email_verification_token_created=timezone.now()
            )
            
            # Send verification email
            self._send_verification_email(user, token)
            
            return user
        except Exception as e:
            # Log hatası ve daha iyi hata mesajı
            print(f"User creation error: {str(e)}")
            raise serializers.ValidationError({"error": str(e)})
    
    def _send_verification_email(self, user, token):
        try:
            verification_url = f"{settings.FRONTEND_URL}/verify-email/{token}"
            send_mail(
                subject="Verify your email address",
                message=f"Please click on the link below to verify your email address:\n\n{verification_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Email sending error: {str(e)}")
            # Email gönderimi hata verirse kullanıcıyı yine de oluştur

class VerifyEmailSerializer(serializers.Serializer):
    """
    E-posta doğrulama işlemlerini yöneten serializer.
    Kullanıcının kayıt sonrası aldığı doğrulama token'ının geçerliliğini kontrol eder.
    Token'ın 24 saat geçerlilik süresi vardır ve bu süre sonunda token geçersiz hale gelir.
    Bu sayede güvenlik riski azaltılmış ve kullanıcı deneyimi iyileştirilmiştir.
    """
    token = serializers.CharField()
    
    def validate_token(self, value):
        try:
            user = User.objects.get(email_verification_token=value, email_verified=False)
            
            # Check if token is expired (24 hours)
            if user.email_verification_token_created:
                expiration_time = user.email_verification_token_created + timezone.timedelta(hours=24)
                if timezone.now() > expiration_time:
                    user.email_verification_token = None
                    user.save()
                    raise serializers.ValidationError("Verification token has expired.")
                
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid verification token.")

class SendVerificationEmailSerializer(serializers.Serializer):
    """
    Doğrulama e-postasını yeniden gönderme işlemlerini yöneten serializer.
    Henüz e-postasını doğrulamamış kullanıcılar için yeni bir doğrulama token'ı oluşturur.
    Detaylı hata ayıklama bilgileri içerir ve token süreçlerini yönetir.
    Kullanıcı deneyimini geliştirmek için oluşabilecek hataları özel mesajlarla ele alır.
    """
    email = serializers.EmailField(required=False)  # İsteğe bağlı alan ekleyin (kullanılmasa bile)
    
    def validate(self, attrs):
        # Kullanıcının kimliğini doğrulayın
        user = self.context['request'].user
        if not user or not user.is_authenticated:
            raise serializers.ValidationError({"error": "Authentication required"})
        return attrs
    
    def save(self, **kwargs):
        user = self.context['request'].user
        print(f"[DEBUG] Sending verification email to user: {user.email}")
        
        if user.email_verified:
            print(f"[DEBUG] Email is already verified for user: {user.email}")
            raise serializers.ValidationError({"email": "Email is already verified."})
        
        # Generate new verification token
        token = str(uuid.uuid4())
        print(f"[DEBUG] New token generated: {token}")
        
        # Update user with new token
        user.email_verification_token = token
        user.email_verification_token_created = timezone.now()
        user.save(update_fields=['email_verification_token', 'email_verification_token_created'])
        print(f"[DEBUG] User updated with new token")
        
        try:
            # Get frontend URL from settings
            frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
            verification_url = f"{frontend_url}/verify-email/{token}"
            print(f"[DEBUG] Verification URL: {verification_url}")
            
            # Send verification email
            send_mail(
                subject="Verify your email address",
                message=f"Please click on the link below to verify your email address:\n\n{verification_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            print(f"[DEBUG] Verification email sent to: {user.email}")
            return {"message": "Verification email sent successfully."}
        except Exception as e:
            print(f"[DEBUG] Error sending verification email: {str(e)}")
            # Token kaydedildi, ancak e-posta gönderilemedi
            raise serializers.ValidationError({"email": f"Failed to send verification email: {str(e)}"})




class ForgotPasswordSerializer(serializers.Serializer):
    """
    Şifremi unuttum işlemlerini yöneten serializer.
    Kullanıcının e-posta adresinin sistemde kayıtlı olup olmadığını kontrol eder.
    Sosyal giriş yapan kullanıcılar için özel kontroller içerir ve bu durumda
    şifre sıfırlama işlemi yerine sosyal giriş yapmaları için yönlendirir.
    Bu sayede kullanıcı deneyimi iyileştirilmiştir.
    """
    email = serializers.EmailField()
    
    def validate_email(self, value):
        try:
            user = User.objects.get(email=value)
            
            # Kullanıcının şifresi yoksa ve sadece sosyal giriş varsa
            if not user.has_usable_password() and user.has_social_login():
                provider = user.social_provider
                raise serializers.ValidationError(
                    f"Bu hesap yalnızca {provider} ile giriş yapabilir. Şifre oluşturmak için önce {provider} ile giriş yapın."
                )
                
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("Bu e-posta ile kayıtlı hesap bulunamadı.")
    
    def save(self):
        email = self.validated_data['email']
        user = User.objects.get(email=email)
        
        # Sosyal hesap kontrolü (validation'da yapıldığı için burada geçilmesi beklenir)
        if user.has_social_login() and not user.has_usable_password():
            return
        
        # Generate reset token
        token = str(uuid.uuid4())
        user.password_reset_token = token
        user.password_reset_token_created = timezone.now()
        user.save()
        
        # Send reset email
        reset_url = f"{settings.FRONTEND_URL}/reset-password/{token}"
        send_mail(
            subject="Reset your password",
            message=f"Please click on the link below to reset your password:\n\n{reset_url}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
class ResetPasswordSerializer(serializers.Serializer):
    """
    Şifre sıfırlama işlemlerini yöneten serializer.
    Şifre sıfırlama token'ının geçerliliğini ve sona erme süresini kontrol eder.
    Kullanıcının yeni şifresini güvenlik kontrollerinden geçirir ve şifreleri eşleştirir.
    Sosyal giriş yapan kullanıcılar için ek güvenlik kontrolleri içerir, böylece hesap güvenliği sağlanır.
    """
    token = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])
    confirm_password = serializers.CharField()
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        
        try:
            user = User.objects.get(password_reset_token=attrs['token'])
            
            # Sosyal hesap kontrolü - sadece sosyal hesap varsa ve şifre yoksa
            if user.has_social_login() and not user.has_usable_password():
                provider = user.social_provider or "sosyal medya"
                raise serializers.ValidationError({"token": f"Bu hesap {provider} ile bağlı. Şifrenizi değiştirmek için {provider} hesabınıza gidin."})
            
            # Check if token is expired (24 hours)
            if user.password_reset_token_created:
                expiration_time = user.password_reset_token_created + timezone.timedelta(hours=24)
                if timezone.now() > expiration_time:
                    user.password_reset_token = None
                    user.save()
                    raise serializers.ValidationError({"token": "Password reset token has expired."})
            
            attrs['user'] = user
            return attrs
        except User.DoesNotExist:
            raise serializers.ValidationError({"token": "Invalid password reset token."})
    
    def save(self):
        user = self.validated_data['user']
        
        # Sosyal hesap kontrolü (validation'da yapıldığı için burada geçilmesi beklenir)
        if user.has_social_login() and not user.has_usable_password():
            return
            
        user.set_password(self.validated_data['new_password'])
        user.password_reset_token = None
        user.password_reset_token_created = None
        user.save()

class ChangePasswordSerializer(serializers.Serializer):
    """
    Şifre değiştirme işlemlerini yöneten serializer.
    Oturum açmış kullanıcının mevcut şifresini doğrular ve yeni şifresini güvenlik kontrollerinden geçirir.
    Yeni şifrelerin eşleştiğini kontrol ederek kullanıcı hatalarını önler.
    Böylece kullanıcının hesap güvenliğini bozmadan şifre değiştirmesi sağlanır.
    """
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    confirm_password = serializers.CharField(required=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value
    
    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()

class CreatePasswordSerializer(serializers.Serializer):
    """
    Şifre oluşturma işlemlerini yöneten serializer.
    Sosyal giriş yapan ancak henüz şifresi olmayan kullanıcıların şifre oluşturmasını sağlar.
    Şifrelerin eşleştiğini kontrol eder ve güvenlik kriterlerine uygunluğunu denetler.
    Bu sayede kullanıcı sosyal giriş yanında normal giriş yöntemi de kazanır.
    """
    new_password = serializers.CharField(required=True, validators=[validate_password])
    confirm_password = serializers.CharField(required=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        return attrs
    
    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()

class UpdateProfileSerializer(serializers.ModelSerializer):
    """
    Kullanıcı profil bilgilerinin güncellenmesini yöneten serializer.
    İsim, soyisim ve telefon numarası gibi temel bilgilerin güncellenmesini sağlar.
    Bu işlem için e-posta doğrulaması veya şifre gerekmez, sadece kimlik doğrulaması yeterlidir.
    Böylece kullanıcı deneyimi kolaylaştırılmıştır.
    """
    class Meta:
        model = User
        fields = ['name', 'surname', 'phone_number']