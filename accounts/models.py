from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
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
    username = None  # remove username
    email = models.EmailField(_("email address"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def display_name(self):
        full = self.get_full_name().strip()  # uses first_name + last_name
        return full if full else self.email

    def __str__(self):
        return self.display_name
    

class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    reg_no = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    

    def __str__(self):
        return f"{self.reg_no} - {self.user.email}"


class StaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    staff_no = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return f"{self.staff_no} - {self.user.email}"

class IndustrySupervisorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="industry_profile")
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.user.email} - {self.company.name}"
