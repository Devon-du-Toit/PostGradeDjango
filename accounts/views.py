from django.conf import settings
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from .serializers import (
    AccountLogoutSerializer,
    AccountRefreshSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .throttles import LoginThrottle, LogoutThrottle, RefreshThrottle, RegisterThrottle


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
        return Response({"registration_open": settings.ALLOW_REGISTRATION})


class LoginView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]


class RefreshView(TokenRefreshView):
    serializer_class = AccountRefreshSerializer
    throttle_classes = [RefreshThrottle]


class LogoutView(TokenBlacklistView):
    serializer_class = AccountLogoutSerializer
    throttle_classes = [LogoutThrottle]
