from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    # ensures groups exist after migrations
    for name in ["Student", "Coordinator", "UniversitySupervisor", "IndustrySupervisor", "Admin"]:
        Group.objects.get_or_create(name=name)
