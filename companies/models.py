from django.db import models

class Company(models.Model):
    STATUS = [
        ("pending_verification", "Pending verification"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("inactive", "Inactive"),
    ]
    name = models.CharField(max_length=200, unique=True)
    industry = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    address = models.CharField(max_length=255, blank=True)

    status = models.CharField(max_length=30, choices=STATUS, default="pending_verification")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class CompanyContact(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=120)
    title = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return f"{self.name} - {self.company.name}"
