from django.conf import settings
from rest_framework import generics
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import RegisterSerializer, UserSerializer
from .throttles import AuthRateThrottle


class RegistrationOpen(BasePermission):
    message = "Registration is closed. Ask an administrator for an account."

    def has_permission(self, request, view):
        return settings.ALLOW_REGISTRATION


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    # No login involved, so a refusal is 403 (not 401 "log in first").
    authentication_classes = []
    permission_classes = [AllowAny, RegistrationOpen]
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "register"


class LoginView(TokenObtainPairView):
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "login"


class CurrentUserView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
