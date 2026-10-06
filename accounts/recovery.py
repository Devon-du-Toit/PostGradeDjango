"""Self-service recovery using trusted configured links and password-bound tokens."""

from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.exceptions import ValidationError

from accounts.models import PasswordResetRequest

INVALID_LINK = "This reset link is invalid or expired. Request a new link."


def recovery_enabled():
    try:
        parts = urlsplit(settings.PASSWORD_RESET_FRONTEND_URL)
        if not parts.hostname or parts.port == 0:
            return False
    except ValueError:
        return False
    trusted = parts.scheme == "https" or (
        settings.DEBUG
        and parts.scheme == "http"
        and parts.hostname in {"localhost", "127.0.0.1"}
    )
    return bool(
        settings.ALLOW_PASSWORD_RECOVERY
        and trusted
        and parts.netloc
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
    )


def request_recovery(email):
    # Queue all addresses alike: SMTP timing and failure cannot reveal accounts.
    PasswordResetRequest.objects.create(email=email)


def deliver_recovery(email, requested_at):
    candidates = list(
        get_user_model()
        .objects.select_for_update()
        .filter(email__iexact=email, is_active=True)
        .exclude(password__startswith=UNUSABLE_PASSWORD_PREFIX)
        .order_by("pk")[:2]
    )
    if len(candidates) != 1:
        return
    user = candidates[0]
    if user.last_password_reset_at and requested_at <= user.last_password_reset_at:
        return
    query = urlencode(
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
        }
    )
    link = f"{settings.PASSWORD_RESET_FRONTEND_URL}#{query}"
    # Never vary the API response for unknown accounts or delivery failures.
    # SMTP exceptions may contain reset links, so do not log their contents.
    try:
        send_mail(
            "Reset your PostGrade password",
            f"Use this link to choose a new password:\n{link}\n\nThe link expires in one hour and can be used once. If you did not request it, ignore this email.",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception:
        return False
    return True


def confirm_recovery(uid, token, password):
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        with transaction.atomic():
            # Recheck under the same user lock used by refresh/logout so two
            # consumers cannot both succeed with the same password-bound token.
            user = (
                get_user_model()
                .objects.select_for_update()
                .get(pk=user_id, is_active=True)
            )
            if (
                not user.has_usable_password()
                or not default_token_generator.check_token(user, token)
            ):
                raise ValidationError({"detail": INVALID_LINK})
            validate_password(password, user=user)
            user.set_password(password)
            user.last_password_reset_at = timezone.now()
            user.save(update_fields=["password", "last_password_reset_at"])
    except (
        ValueError,
        TypeError,
        OverflowError,
        UnicodeDecodeError,
        get_user_model().DoesNotExist,
    ) as exc:
        raise ValidationError({"detail": INVALID_LINK}) from exc
