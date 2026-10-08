from django.core.exceptions import ValidationError


class SpecialCharacterValidator:
    def validate(self, password, user=None):
        if not any(not char.isalnum() and not char.isspace() for char in password):
            raise ValidationError(
                self.get_help_text(), code="password_no_special_character"
            )

    def get_help_text(self):
        return "Your password must contain at least one special character, such as !, @ or #."
