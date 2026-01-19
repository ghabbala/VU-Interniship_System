import datetime
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from django.db.models import Q

from placements.models import Placement
from tracking.models import WeeklyLog

def week_bounds(today):
    start = today - datetime.timedelta(days=today.weekday())
    end = start + datetime.timedelta(days=6)
    return start, end

class Command(BaseCommand):
    help = "Send email reminders to students who have not submitted weekly logs for the current week."

    def handle(self, *args, **options):
        today = timezone.localdate()
        wk_start, wk_end = week_bounds(today)

        placements = (Placement.objects
            .exclude(status__in=["completed", "terminated"])
            .select_related("request", "request__student", "request__student__user", "company"))

        sent = 0
        for p in placements:
            student_user = p.request.student.user

            has_log = WeeklyLog.objects.filter(
                placement=p,
                status__in=["submitted", "approved_by_company"],
            ).filter(
                Q(from_date__lte=wk_end) & Q(to_date__gte=wk_start)
            ).exists()

            if has_log:
                continue

            if not student_user.email:
                continue

            subject = f"Reminder: Weekly internship log missing ({wk_start} to {wk_end})"
            message = (
                f"Hello {student_user.email},\n\n"
                f"Our records show you have not submitted your weekly internship log for the week "
                f"{wk_start} to {wk_end}.\n"
                f"Company: {p.company.name}\n\n"
                f"Please log in and submit your weekly log.\n"
                f"Thank you."
            )

            send_mail(subject, message, None, [student_user.email], fail_silently=True)
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Reminders sent: {sent}"))
