# users/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'name', 'surname', 'is_active', 'is_staff', 'email_verified', 'social_provider')
    list_filter = ('is_active', 'is_staff', 'email_verified')
    search_fields = ('email', 'name', 'surname')
    ordering = ('email',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('name', 'surname', 'phone_number')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Email Verification', {'fields': ('email_verified', 'email_verification_token', 'email_verification_token_created')}),
        ('Password Reset', {'fields': ('password_reset_token', 'password_reset_token_created')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'name', 'surname', 'password1', 'password2'),
        }),
    )

admin.site.register(User, UserAdmin)