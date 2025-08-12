# users/api/urls.py
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView,
    VerifyEmailView,
    UserLoginView,
    UserLogoutView,
    ForgotPasswordView,
    ResetPasswordView,
    ChangePasswordView,
    UserProfileView,
    UserInfoView,
    CustomTokenRefreshView,  # Yeni eklenen view
    SendVerificationEmailView,
    GoogleLoginView,
    CreatePasswordView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('send-verification-email/', SendVerificationEmailView.as_view(), name='send-verification-email'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('google/', GoogleLoginView.as_view(), name='google-login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('create-password/', CreatePasswordView.as_view(), name='create_password'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('me/', UserInfoView.as_view(), name='user-info'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),

]