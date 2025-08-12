
# users/api/views.py
from rest_framework import status, generics, permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from  rest_framework import serializers
from django.utils import timezone
from rest_framework.permissions import AllowAny
import requests
import json
from .serializers import (
    UserSerializer,
    RegisterSerializer,
    VerifyEmailSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer,
    UpdateProfileSerializer,
    SendVerificationEmailSerializer,
    CreatePasswordSerializer,
)

User = get_user_model()



class RegisterView(generics.CreateAPIView):
    """
    Kullanıcı kayıt işlemlerini gerçekleştiren view.
    REST framework'ün CreateAPIView sınıfını kullanarak otomatik olarak POST işlemlerini yönetir.
    Herhangi bir kimlik doğrulama olmadan erişilebilir, böylece yeni kullanıcılar sisteme kaydolabilir.
    RegisterSerializer sınıfını kullanarak veri doğrulama, şifre hashleme ve e-posta doğrulama token'ı gönderme işlemlerini gerçekleştirir.
    """
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

class GoogleLoginView(APIView):
    """
    Google ile sosyal giriş işlemlerini yöneten view.
    Google'dan gelen ID token'ı doğrular ve bu bilgilere dayanarak sisteme giriş yapar veya yeni hesap oluşturur.
    Token doğrulama için Google API'lerine bağlanır ve dönen bilgilere göre kullanıcı oluşturur veya günceller.
    Sosyal giriş ile gelen kullanıcılar için e-posta otomatik doğrulanmış kabul edilir ve JWT token oluşturularak dönülür.
    """
    authentication_classes = []  # Kimlik doğrulama gerekmez
    permission_classes = [permissions.AllowAny]  # İzin sınıfını ayarla
    
    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Google'ın ID token'ını doğrula
            # @react-oauth/google, id_token gönderiyor, access_token değil
            google_response = requests.get(
                'https://oauth2.googleapis.com/tokeninfo',
                params={'id_token': token}
            )
            
            if not google_response.ok:
                return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)
            
            google_data = google_response.json()
            
            # Token doğruysa, kullanıcı email'inden bul veya oluştur
            email = google_data.get('email')
            if not email:
                return Response({"error": "Email not provided by Google"}, status=status.HTTP_400_BAD_REQUEST)
            
            # Bu kullanıcı zaten var mı diye kontrol et
            user = None
            try:
                user = User.objects.get(email=email)
                # Kullanıcı varsa, sosyal hesap olarak güncelle
                user.is_social_account = True
                user.social_provider = 'google'
                user.save(update_fields=['social_provider'])
            except User.DoesNotExist:
                # Kullanıcı yoksa yeni oluştur
                name_parts = google_data.get('name', '').split(' ', 1)
                first_name = name_parts[0] if name_parts else ''
                last_name = name_parts[1] if len(name_parts) > 1 else ''
                
                user = User.objects.create(
                    email=email,
                    name=first_name,
                    surname=last_name,
                    email_verified=True,  # Google ile doğrulandı
                    social_provider='google',
                    is_active=True
                )
                # Kullanıcı sosyal girişle geldiği için password yok
                user.set_unusable_password()
                user.save()
            
            # JWT token'ları oluştur
            refresh = RefreshToken.for_user(user)
            
            # Kullanıcı verilerini hazırla
            user_data = UserSerializer(user).data
            user_data['access'] = str(refresh.access_token)
            user_data['refresh'] = str(refresh)
            
            return Response(user_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class VerifyEmailView(APIView):
    """
    E-posta doğrulama işlemini gerçekleştiren view.
    Kullanıcıya gönderilen doğrulama e-postasındaki URL'den gelen token'ı kontrol eder.
    Token geçerliyse ve süresi dolmamışsa kullanıcının e-posta adresini doğrulanmış olarak işaretler.
    Kimlik doğrulama gerektirmez çünkü kullanıcı henüz giriş yapmamış olabilir.
    Token'ın süresi dolduysa veya geçersizse uygun hata mesajları döndürür.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        if serializer.is_valid():
            token = serializer.validated_data['token']
            try:
                # Serializer'da zaten token kontrolü yapıldığı için, burada user'ı bulabilmemiz gerekiyor
                user = User.objects.get(email_verification_token=token, email_verified=False)
                
                # Token süresi kontrolü
                if user.email_verification_token_created:
                    expiration_time = user.email_verification_token_created + timezone.timedelta(hours=24)
                    if timezone.now() > expiration_time:
                        return Response({"error": "Verification token has expired."}, status=status.HTTP_400_BAD_REQUEST)
                
                # Kullanıcı email doğrulama
                user.email_verified = True
                user.email_verification_token = None
                user.save(update_fields=['email_verified', 'email_verification_token'])  # Sadece değiştirilen alanları kaydet
                
                return Response({"message": "Email successfully verified."}, status=status.HTTP_200_OK)
            except User.DoesNotExist:
                return Response({"error": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SendVerificationEmailView(APIView):
    """
    Doğrulama e-postasını yeniden gönderen view.
    Kimlik doğrulaması gerektirir, çünkü sadece giriş yapmış ve e-postası henüz doğrulanmamış kullanıcılar
    doğrulama e-postasını tekrar talep edebilir.
    Yeni bir doğrulama token'ı oluşturur ve kullanıcının e-posta adresine doğrulama bağlantısı içeren bir e-posta gönderir.
    Kullanıcının e-postası zaten doğrulanmışsa uygun hata mesajı döndürür.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = SendVerificationEmailSerializer(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response({"message": "Verification email sent successfully."}, status=status.HTTP_200_OK)
        except serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserLoginView(TokenObtainPairView):
    """
    Kullanıcı giriş işlemini gerçekleştiren view.
    JWT tabanlı kimlik doğrulama için TokenObtainPairView'ı genişletir.
    Başarılı girişte hem Access hem de Refresh token'ları oluşturur ve güvenli HTTP-only çerezlere kaydeder.
    Kullanıcı bilgilerini de response içinde döndürerek frontend'in kullanıcı bilgilerini hemen gösterebilmesini sağlar.
    Token'ların çerezlere kaydedilmesi, XSS saldırılarına karşı koruma sağlar.
    """
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == status.HTTP_200_OK:
            access_token = response.data.get('access')
            refresh_token = response.data.get('refresh')
            
            # Set httpOnly cookies
            response.set_cookie(
                'access_token',
                access_token,
                httponly=True,
                max_age=60 * 60,  # 1 hour
                samesite='Lax'
            )
            response.set_cookie(
                'refresh_token',
                refresh_token,
                httponly=True,
                max_age=24 * 60 * 60,  # 1 day
                samesite='Lax'
            )
            
            # Kullanıcı bilgilerini al
            from rest_framework_simplejwt.tokens import AccessToken
            token_obj = AccessToken(access_token)
            user_id = token_obj.payload.get('user_id')
            
            try:
                user = User.objects.get(id=user_id)
                serializer = UserSerializer(user)
                response.data = serializer.data
            except User.DoesNotExist:
                response.data = {"error": "User not found"}
                
        return response

class UserLogoutView(APIView):
    """
    Kullanıcı çıkış işlemini gerçekleştiren view.
    Kimlik doğrulaması gerektirir çünkü sadece giriş yapmış kullanıcılar çıkış yapabilir.
    Çıkış işlemi, HTTP-only çerezlerde saklanan Access ve Refresh token'larını silerek gerçekleştirilir.
    Çerezlerin silinmesi ile kullanıcı oturumu sonlandırılmış olur.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        response = Response({"message": "Successfully logged out."}, status=status.HTTP_200_OK)
        response.delete_cookie('access_token')
        response.delete_cookie('refresh_token')
        return response

class ForgotPasswordView(APIView):
    """
    Şifremi unuttum işlemini başlatan view.
    Kimlik doğrulaması gerektirmez çünkü kullanıcı şifresini unuttuğu için giriş yapamıyor olabilir.
    Kullanıcının e-posta adresini alır, kullanıcıyı veritabanında kontrol eder ve e-postası doğruysa şifre sıfırlama bağlantısı gönderir.
    Sosyal giriş kullanan ancak henüz şifre oluşturmamış kullanıcılar için özel kontroller içerir.
    Şifre sıfırlama token'ı oluşturur ve bu token'ı içeren bir e-posta gönderir.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Password reset link has been sent to your email."},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResetPasswordView(APIView):
    """
    Şifre sıfırlama işlemini tamamlayan view.
    Şifremi unuttum e-postasındaki bağlantıdan gelen token'ı ve kullanıcının yeni şifresini alır.
    Kimlik doğrulaması gerektirmez çünkü kullanıcı şifresini sıfırlamak için bu view'i kullanıyor.
    Token'ın geçerliliğini ve süresini kontrol eder, şifrelerin eşleşip eşleşmediğini doğrular.
    Şifre güvenlik kriterlerini kontrol eder ve uygun olması durumunda kullanıcının şifresini güvenli bir şekilde değiştirir.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Password has been reset successfully."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    """
    Şifre değiştirme işlemini gerçekleştiren view.
    Kimlik doğrulaması gerektirir çünkü kullanıcının şifresini değiştirebilmesi için giriş yapmış olması gerekir.
    Kullanıcının mevcut şifresini doğrular ve eğer doğruysa yeni şifreyi güvenli bir şekilde ayarlar.
    Şifresi olmayan (sosyal giriş kullanıcıları) için özel kontroller içerir ve bu durumda CreatePasswordView'e yönlendirir.
    Şifrelerin eşleşip eşleşmediğini ve güvenlik kriterlerine uyup uymadığını kontrol eder.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        user = request.user
        
        # Şifresi olmayan kullanıcılar şifre değiştiremez
        if not user.has_usable_password():
            return Response({
                "error": "You don't have a password yet. Use create password option first."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Password changed successfully."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CreatePasswordView(APIView):
    """
    Şifre oluşturma işlemini gerçekleştiren view.
    Sosyal giriş yapan ve henüz şifresi olmayan kullanıcıların şifre oluşturmasını sağlar.
    Kimlik doğrulaması gerektirir çünkü kullanıcının şifre oluşturabilmesi için giriş yapmış olması gerekir.
    Kullanıcının zaten bir şifresi varsa ChangePasswordView'e yönlendirir.
    Yeni şifrelerin eşleşip eşleşmediğini ve güvenlik kriterlerine uyup uymadığını kontrol eder.
    Böylece sosyal giriş yapan kullanıcılar normal giriş yöntemiyle de giriş yapabilir hale gelir.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        user = request.user
        
        # Sadece şifreyi olmayan kullanıcılar şifre oluşturabilir
        if user.has_usable_password():
            return Response({
                "error": "You already have a password. Use the change password option instead."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = CreatePasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Password created successfully."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Kullanıcı profil bilgilerini görüntüleme ve güncelleme işlemlerini gerçekleştiren view.
    REST framework'ün RetrieveUpdateAPIView sınıfını kullanarak otomatik olarak GET ve PUT işlemlerini yönetir.
    Kimlik doğrulaması gerektirir çünkü kullanıcı ancak kendi profilini görüntüleyebilir ve güncelleyebilir.
    GET istekleri için UserSerializer'ı, PUT/PATCH istekleri için UpdateProfileSerializer'ı kullanır.
    Bu sayede kullanıcı profil bilgilerini görüntüleyebilir ve güncelleyebilir.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UpdateProfileSerializer
    
    def get_object(self):
        return self.request.user
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return UserSerializer
        return UpdateProfileSerializer

class UserInfoView(APIView):
    """
    Giriş yapmış kullanıcının bilgilerini döndüren view.
    Kimlik doğrulaması gerektirir çünkü kullanıcı bilgilerini sadece giriş yapmış kullanıcılara gösteriyoruz.
    UserSerializer'ı kullanarak kullanıcı bilgilerini döndürür.
    Frontend'in kullanıcı oturumunu kontrol etmesi ve kullanıcı bilgilerini göstermesi için kullanılır.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

class CustomTokenRefreshView(APIView):
    """
    Token yenileme işlemini gerçekleştiren view.
    Standart TokenRefreshView yerine kullanılır ve HTTP-only çerezleri destekler.
    Kimlik doğrulaması gerektirmez çünkü token yenileme için zaten refresh token gerekiyor.
    Çerezlerden refresh token'ı alır, geçerliyse yeni bir access token oluşturur ve bunu yine çerezlere kaydeder.
    Bu sayede kullanıcının oturumu güvenli bir şekilde devam eder ve token'lar tarayıcı tarafından JavaScript ile erişilemez.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get('refresh_token')
        
        if refresh_token:
            try:
                refresh = RefreshToken(refresh_token)
                access_token = str(refresh.access_token)
                
                response = Response({"access": access_token})
                response.set_cookie('access_token', access_token, httponly=True, max_age=3600)
                return response
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({"error": "No refresh token found"}, status=status.HTTP_400_BAD_REQUEST)