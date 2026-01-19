from django.db import models

class Faculty(models.Model):
    name = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return self.name

class Department(models.Model):
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name="departments")
    name = models.CharField(max_length=150)

    class Meta:
        unique_together = [("faculty", "name")]

    def __str__(self):
        return f"{self.name} ({self.faculty.name})"

class Program(models.Model):
    AWARD_LEVEL = [
        ("degree", "Degree"),
        ("diploma", "Diploma"),
        ("certificate", "Certificate"),
    ]
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="programs")
    name = models.CharField(max_length=160)
    award_level = models.CharField(max_length=20, choices=AWARD_LEVEL, default="degree")

    class Meta:
        unique_together = [("department", "name", "award_level")]

    def __str__(self):
        return f"{self.name} ({self.get_award_level_display()})"
