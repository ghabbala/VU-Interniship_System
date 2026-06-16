import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def test_login_page_has_forgot_password_link(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, reverse("password_reset"))
        self.assertContains(response, "Forgot password?")

    def test_password_reset_sends_otp_email_for_existing_user(self):
        user = User.objects.create_user(
            email="student@vu.ac.ug",
            password="InitialPass123",
            first_name="Test",
            last_name="Student",
        )

        response = self.client.post(
            reverse("password_reset"),
            {"email": "student@vu.ac.ug"},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("OTP", mail.outbox[0].subject)
        self.assertRegex(mail.outbox[0].body, r"\b\d{6}\b")
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        self.assertIn("Use this OTP", mail.outbox[0].alternatives[0][0])

        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group(0)
        response = self.client.post(
            reverse("password_reset_verify"),
            {
                "otp": code,
                "new_password1": "NewPassword123",
                "new_password2": "NewPassword123",
            },
        )

        self.assertRedirects(response, reverse("password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPassword123"))
