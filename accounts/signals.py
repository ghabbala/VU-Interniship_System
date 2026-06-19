from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    if sender.label != "accounts":
        return

    group_permissions = {
        "Student": [],
        "Coordinator": ["role_coordinator"],
        "UniversitySupervisor": ["role_university_supervisor"],
        "IndustrySupervisor": ["role_industry_supervisor"],
        "SystemAdmin": ["role_system_admin"],
        "Admin": ["role_system_admin"],
    }

    for name, codenames in group_permissions.items():
        Group.objects.get_or_create(name=name)
        group = Group.objects.get(name=name)
        for codename in codenames:
            permission = Permission.objects.filter(
                content_type__app_label="accounts",
                codename=codename,
            ).first()
            if permission:
                group.permissions.add(permission)
