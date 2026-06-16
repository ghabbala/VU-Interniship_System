from django.db import models
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(_("email address"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        permissions = [
            ("role_university_supervisor", "Role: VU_UniversitySupervisor"),
            ("role_industry_supervisor", "Role: IndustrySupervisor"),
            ("role_coordinator", "Role: VU_Coordinator"),
        ]

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full if full else self.email

    def __str__(self):
        return self.display_name



class StudentProfile(models.Model):
    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="student_profile")
    reg_no = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=30, blank=True)

    # ✅ NEW: link to academics.Program
    program = models.ForeignKey(
        "academics.Program",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="students",
    )

    def __str__(self):
        return f"{self.reg_no} - {self.user.email}"


class StaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    staff_no = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f"{self.staff_no} - {self.user.email}"

class IndustrySupervisorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="industry_profile")
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)

    def has_current_placement_access(self):
        from placements.models import Placement

        today = timezone.localdate()
        return Placement.objects.filter(
            company=self.company,
            status__in=["pending_student_ack", "active", "on_hold"],
            end_date__gte=today,
        ).exists()

    def __str__(self):
        return f"{self.user.email} - {self.company.name}"


class PasswordResetOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_otps")
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def create_for_user(cls, user, code, expires_at):
        cls.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
        return cls.objects.create(
            user=user,
            code_hash=make_password(code),
            expires_at=expires_at,
        )

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    def check_code(self, code):
        return check_password(code, self.code_hash)

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])
