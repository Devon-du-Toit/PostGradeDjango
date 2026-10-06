from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from .recovery import confirm_recovery, recovery_enabled, request_recovery
from .serializers import (
    AccountLogoutSerializer,
    AccountRefreshSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .throttles import (
    LoginThrottle,
    LogoutThrottle,
    PasswordResetConfirmThrottle,
    PasswordResetEmailThrottle,
    PasswordResetThrottle,
    RefreshThrottle,
    RegisterThrottle,
)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [RegisterThrottle]

    def create(self, request, *args, **kwargs):
        if not settings.ALLOW_REGISTRATION:
            raise PermissionDenied(
                "Registration is closed. Contact an administrator for an account."
            )
        return super().create(request, *args, **kwargs)


class CurrentUserView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class RegistrationPolicyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(
            {
                "registration_open": settings.ALLOW_REGISTRATION,
                "password_recovery_available": recovery_enabled(),
            }
        )


class RecoveryRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class RecoveryConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=100)
    token = serializers.CharField(max_length=100)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128
    )


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetThrottle, PasswordResetEmailThrottle]

    def post(self, request):
        if not recovery_enabled():
            raise PermissionDenied(
                "Password recovery is unavailable. Contact an administrator."
            )
        payload = RecoveryRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        request_recovery(payload.validated_data["email"])
        return Response(
            {
                "detail": "If an active account matches that email, a password reset link will be sent."
            },
            status=202,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetConfirmThrottle]

    def post(self, request):
        if not recovery_enabled():
            raise PermissionDenied(
                "Password recovery is unavailable. Contact an administrator."
            )
        payload = RecoveryConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            confirm_recovery(**payload.validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return Response({"detail": "Password updated. Sign in with your new password."})


class LoginView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]


class RefreshView(TokenRefreshView):
    serializer_class = AccountRefreshSerializer
    throttle_classes = [RefreshThrottle]


class LogoutView(TokenBlacklistView):
    serializer_class = AccountLogoutSerializer
    throttle_classes = [LogoutThrottle]
