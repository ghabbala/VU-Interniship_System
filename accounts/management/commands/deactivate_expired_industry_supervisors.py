from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import IndustrySupervisorProfile


class Command(BaseCommand):
    help = "Deactivate industry supervisor accounts whose company has no current internship placement."

    def handle(self, *args, **options):
        today = timezone.localdate()
        deactivated = 0

        profiles = IndustrySupervisorProfile.objects.select_related("user", "company").filter(user__is_active=True)
        for profile in profiles:
            if not profile.has_current_placement_access():
                profile.user.is_active = False
                profile.user.save(update_fields=["is_active"])
                deactivated += 1
                self.stdout.write(
                    f"Deactivated {profile.user.email} ({profile.company.name}) on {today}"
                )

        self.stdout.write(self.style.SUCCESS(f"Deactivated {deactivated} expired industry supervisor account(s)."))
