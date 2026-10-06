from django.urls import path

from .views import (
    CurrentUserView,
    LoginView,
    LogoutView,
    RefreshView,
    RegisterView,
    RegistrationPolicyView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path(
        "registration-policy/",
        RegistrationPolicyView.as_view(),
        name="registration-policy",
    ),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", CurrentUserView.as_view(), name="current_user"),
]
