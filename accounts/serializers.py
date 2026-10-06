from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenBlacklistSerializer,
    TokenRefreshSerializer,
)

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "password",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        validate_password(
            attrs["password"],
            user=User(
                email=attrs.get("email", ""),
                first_name=attrs.get("first_name", ""),
                last_name=attrs.get("last_name", ""),
            ),
        )
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
        )
        read_only_fields = fields


class AccountRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        from django.db import transaction
        from rest_framework.exceptions import AuthenticationFailed
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.utils import get_md5_hash_password

        # Serialize rotation per user so two requests cannot both consume one token.
        token = self.token_class(attrs["refresh"])
        with transaction.atomic():
            try:
                user = User.objects.select_for_update().get(
                    pk=token[api_settings.USER_ID_CLAIM]
                )
            except (User.DoesNotExist, KeyError, ValueError, TypeError) as exc:
                raise AuthenticationFailed("No active account found.") from exc
            if not user.is_active or token.get(
                api_settings.REVOKE_TOKEN_CLAIM
            ) != get_md5_hash_password(user.password):
                raise AuthenticationFailed(
                    "This session is no longer valid. Sign in again."
                )
            # Reparse after locking: a concurrent refresh/logout may have revoked it.
            return super().validate(attrs)


class AccountLogoutSerializer(TokenBlacklistSerializer):
    def validate(self, attrs):
        from django.db import transaction
        from rest_framework_simplejwt.settings import api_settings

        token = self.token_class(attrs["refresh"])
        with transaction.atomic():
            User.objects.select_for_update().filter(
                pk=token.get(api_settings.USER_ID_CLAIM)
            ).first()
            return super().validate(attrs)
