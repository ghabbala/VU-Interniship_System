from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import InternshipPeriod, InternshipRequest, Placement, RecommendationLetterSettings
from .forms import InternshipPeriodForm, InternshipRequestForm, RecommendationLetterSettingsForm

from django.contrib.auth.models import Group
from django.http import HttpResponseForbidden
from django.db import transaction

from .forms import RecommendationLetterForm, AcceptanceLetterUploadForm, VerifyAcceptanceAssignSupervisorForm
from companies.models import Company
from .models import Placement
from accounts.models import StaffProfile

from .models import InternshipRequest
from django.http import FileResponse, Http404, HttpResponseForbidden

from django.core.files.storage import default_storage
from tracking.utils.recommendation_letter import generate_recommendation_letter_pdf
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone





def is_coordinator(user):
    return user.is_superuser or user.groups.filter(name__in=["Coordinator", "Admin"]).exists()


def is_vu_coordinator(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_coordinator")
    )



@login_required
def my_request(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    student = request.user.student_profile
    period = InternshipPeriod.objects.filter(is_active=True).first()
    if not period:
        return render(request, "placements/no_active_period.html")

    req, _ = InternshipRequest.objects.get_or_create(
        student=student,
        period=period,
        defaults={"status": "draft", "request_source": "student_selected"},
    )

    if request.method == "POST":
        form = InternshipRequestForm(request.POST, request.FILES, instance=req)
        if form.is_valid():
            req = form.save(commit=False)

            # set request_source correctly
            if req.preferred_company:
                req.request_source = "student_selected"
            else:
                req.request_source = "student_proposed"

            action = request.POST.get("action", "save")

            if action == "submit":
                # Prevent re-submitting if already moved onward
                if req.status in [
                    "submitted",
                    "under_review",
                    "recommendation_pending",
                    "recommended",
                    "acceptance_uploaded",
                    "acceptance_verified",
                ]:
                    req.save()
                    return redirect("my_request")

                # Must pick or propose a company before submitting
                if not req.preferred_company and not (req.proposed_company_name or "").strip():
                    form.add_error(None, "Please select an approved company or propose a company before submitting.")
                    return render(
                        request,
                        "placements/my_request.html",
                        {"form": form, "req": req, "period": period},
                    )

                # ✅ mark submitted
                req.status = "submitted"
                req.submitted_at = timezone.now()

                # ✅ auto-generate recommendation letter as DRAFT (not issued to student)
                if not req.recommendation_letter:
                    # coordinator_user can be None; function will handle it if you updated it
                    filename, content = generate_recommendation_letter_pdf(req, coordinator_user=None)
                    req.recommendation_letter.save(filename, content, save=False)

                # ✅ keep locked until coordinator approves
                req.recommendation_approved = False
                req.recommendation_approved_at = None
                req.recommendation_approved_by = None

                # ✅ move to "pending approval" state (clearer than staying "submitted")
                req.status = "recommendation_pending"

            else:
                # Save draft
                if req.status not in ["returned_for_edit"]:
                    req.status = "draft"

            req.save()
            return redirect("my_request")
    else:
        form = InternshipRequestForm(instance=req)

    return render(request, "placements/my_request.html", {"form": form, "req": req, "period": period})

@login_required
def submit_request(request):
    # ✅ If someone opens this URL directly, send them back to the form
    if request.method == "GET":
        return redirect("my_request")

    if request.method != "POST":
        return HttpResponseForbidden("Method not allowed.")

    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    student = request.user.student_profile
    period = InternshipPeriod.objects.filter(is_active=True).first()
    if not period:
        return redirect("my_request")

    req, _ = InternshipRequest.objects.get_or_create(
        student=student,
        period=period,
        defaults={"request_source": "student_selected", "status": "draft"},
    )

    # Must pick or propose a company before submitting
    if not req.preferred_company and not (req.proposed_company_name or "").strip():
        return redirect("my_request")

    req.status = "submitted"
    req.submitted_at = timezone.now()
    req.save()
    return redirect("my_request")


@login_required
def coordinator_queue(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    qs = (
        InternshipRequest.objects
        .select_related("student", "student__user", "preferred_company", "period")
        .filter(status__in=["submitted", "under_review", "recommendation_pending"])
        .order_by("-submitted_at")
    )

    return render(request, "placements/coordinator_queue.html", {"requests": qs})


@login_required
def coordinator_periods(request):
    if not is_vu_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")

    periods = (
        InternshipPeriod.objects
        .annotate(request_count=Count("internshiprequest"))
        .order_by("-is_active", "-start_date")
    )
    active_period = periods.filter(is_active=True).first()

    return render(request, "placements/coordinator_periods.html", {
        "periods": periods,
        "active_period": active_period,
    })


@login_required
def coordinator_period_create(request):
    if not is_vu_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")

    if request.method == "POST":
        form = InternshipPeriodForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Internship period created.")
            return redirect("coordinator_periods")
    else:
        form = InternshipPeriodForm()

    return render(request, "placements/coordinator_period_form.html", {
        "form": form,
        "period": None,
        "title": "Create Internship Period",
    })


@login_required
def coordinator_period_edit(request, period_id):
    if not is_vu_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")

    period = get_object_or_404(InternshipPeriod, id=period_id)
    if request.method == "POST":
        form = InternshipPeriodForm(request.POST, instance=period)
        if form.is_valid():
            form.save()
            messages.success(request, "Internship period updated.")
            return redirect("coordinator_periods")
    else:
        form = InternshipPeriodForm(instance=period)

    return render(request, "placements/coordinator_period_form.html", {
        "form": form,
        "period": period,
        "title": "Edit Internship Period",
    })


@login_required
def coordinator_period_activate(request, period_id):
    if not is_vu_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")

    period = get_object_or_404(InternshipPeriod, id=period_id)
    period.is_active = True
    period.save(update_fields=["is_active"])
    messages.success(request, f"{period.name} is now the active internship period.")
    return redirect("coordinator_periods")


@login_required
def coordinator_recommendation_settings(request):
    if not is_vu_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")

    settings_obj = RecommendationLetterSettings.current()

    if request.method == "POST":
        form = RecommendationLetterSettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            letter_settings = form.save(commit=False)
            letter_settings.updated_by = request.user
            letter_settings.save()
            messages.success(request, "Recommendation letter settings updated. Regenerate any existing letters that should use the new stamp.")
            return redirect("coordinator_recommendation_settings")
    else:
        form = RecommendationLetterSettingsForm(instance=settings_obj)

    return render(request, "placements/coordinator_recommendation_settings.html", {
        "form": form,
        "settings_obj": settings_obj,
    })


@login_required
def coordinator_review(request, request_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    req = get_object_or_404(InternshipRequest, id=request_id)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "mark_under_review":
            req.status = "under_review"
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        elif action == "reject":
            req.status = "rejected"
            req.review_notes = request.POST.get("review_notes", "")
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save(update_fields=["status", "review_notes", "reviewed_by", "reviewed_at"])

        elif action == "approve_and_create_placement":
            # 1) Ensure company exists (create if student proposed)
            company = req.preferred_company
            if not company:
                proposed_name = (req.proposed_company_name or "").strip()
                if not proposed_name:
                    return HttpResponseForbidden("No company provided for this request.")

                company, _ = Company.objects.get_or_create(
                    name=proposed_name,
                    defaults={
                        "district": req.proposed_company_district,
                        "address": req.proposed_company_address,
                        "status": "approved",  # change to "pending_verification" if needed
                    },
                )

            # 2) Generate the official PDF with the current stamp/settings
            filename, content = generate_recommendation_letter_pdf(req, request.user)
            req.recommendation_letter.save(filename, content, save=False)

            # 3) ✅ Issue to student immediately (so student can download)
            req.recommendation_approved = True
            req.recommendation_approved_at = timezone.now()
            req.recommendation_approved_by = request.user
            req.recommendation_issued_at = timezone.now()

            # ✅ Set status to "recommended" (matches student download + acceptance upload gate)
            req.status = "recommended"

            # review metadata
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()

            req.save(update_fields=[
                "recommendation_letter",
                "recommendation_approved",
                "recommendation_approved_at",
                "recommendation_approved_by",
                "recommendation_issued_at",
                "status",
                "reviewed_by",
                "reviewed_at",
            ])

            # 4) Optional early placement (won't be active until acceptance is verified in your flow)
            Placement.objects.get_or_create(
                request=req,
                defaults={
                    "company": company,
                    "start_date": req.period.start_date,
                    "end_date": req.period.end_date,
                    "status": "pending_student_ack",
                },
            )

        return redirect("coordinator_review", request_id=req.id)

    return render(request, "placements/coordinator_review.html", {"req": req})




@login_required
def coordinator_issue_recommendation(request, request_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    req = get_object_or_404(InternshipRequest, id=request_id)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        # -----------------------------
        # 1) Generate / Regenerate PDF
        # -----------------------------
        if action in ["generate", "regenerate"]:
            # Always regenerate so stamp/signature updates reflect in the PDF
            filename, content = generate_recommendation_letter_pdf(req, request.user)

            # Save/overwrite file (new filename each time)
            req.recommendation_letter.save(filename, content, save=False)

            # Generation does NOT mean issued to student
            req.recommendation_approved = False
            req.recommendation_approved_at = None
            req.recommendation_approved_by = None

            # Optional: keep it pending until approved
            if req.status not in ["acceptance_uploaded", "acceptance_verified", "recommended"]:
                req.status = "recommendation_pending"

            req.save(update_fields=[
                "recommendation_letter",
                "recommendation_approved",
                "recommendation_approved_at",
                "recommendation_approved_by",
                "status",
            ])
            return redirect("coordinator_issue_recommendation", request_id=req.id)

        # -----------------------------
        # 2) Approve / Issue to student
        # -----------------------------
        if action == "approve":
            # Generate the official PDF with the current stamp/settings before release.
            filename, content = generate_recommendation_letter_pdf(req, request.user)
            req.recommendation_letter.save(filename, content, save=False)

            req.recommendation_approved = True
            req.recommendation_approved_at = timezone.now()
            req.recommendation_approved_by = request.user

            # "Issued" time (when it becomes visible to student)
            req.recommendation_issued_at = timezone.now()

            # Update status
            req.status = "recommended"

            req.save(update_fields=[
                "recommendation_letter",
                "recommendation_approved",
                "recommendation_approved_at",
                "recommendation_approved_by",
                "recommendation_issued_at",
                "status",
            ])
            return redirect("coordinator_issue_recommendation", request_id=req.id)

    return render(request, "placements/coordinator_issue_recommendation.html", {"req": req})





# ✅ Adjust this import to your actual Notification model location
from tracking.models import Notification  # e.g. tracking.models import Notification

User = get_user_model()


def _get_coordinator_users():
    """
    Returns queryset of all users who are coordinators using permission-based role checks.
    Works whether permission is granted directly OR via group.
    """
    ct = ContentType.objects.get(app_label="accounts", model="user")
    return User.objects.filter(
        is_active=True
    ).filter(
        Q(is_superuser=True)
        |
        Q(
            user_permissions__codename="role_coordinator",
            user_permissions__content_type=ct,
        )
        |
        Q(
            groups__permissions__codename="role_coordinator",
            groups__permissions__content_type=ct,
        )
    ).distinct()


def _notify_coordinators_acceptance_uploaded(req, by_user, is_reupload=False):
    """
    Creates Notification entries for all coordinators.
    """
    coordinators = _get_coordinator_users()
    if not coordinators.exists():
        return

    action_url = reverse("coordinator_acceptance_queue")

    student_name = getattr(by_user, "display_name", None) or by_user.get_full_name() or by_user.email
    reg_no = getattr(req.student, "reg_no", None) or "—"

    title = "Acceptance letter re-uploaded" if is_reupload else "Acceptance letter uploaded"
    msg = (
        f"{student_name} (Reg No: {reg_no}) uploaded an acceptance letter.\n"
        f"Please verify and assign a University Supervisor."
    )

    # If your Notification model uses choices, keep to values you support.
    # Common values: info, success, warning, danger
    level = "warning"

    Notification.objects.bulk_create([
        Notification(
            user=u,
            title=title,
            message=msg,
            level=level,
            action_url=action_url,
            action_text="Open Acceptance Queue",
            is_read=False,
        )
        for u in coordinators
    ])

@login_required
def student_upload_acceptance(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    student = request.user.student_profile
    period = InternshipPeriod.objects.filter(is_active=True).first()
    if not period:
        return render(request, "placements/no_active_period.html")

    req = get_object_or_404(InternshipRequest, student=student, period=period)

    # Block if verified
    if req.status == "acceptance_verified":
        return render(request, "placements/acceptance_not_allowed.html", {"req": req})

    # Allow upload + re-upload
    if req.status not in ["recommended", "returned_for_acceptance", "acceptance_uploaded"]:
        return render(request, "placements/acceptance_not_allowed.html", {"req": req})

    if request.method == "POST":
        old_name = req.acceptance_letter.name if req.acceptance_letter else None
        was_reupload = (req.status == "acceptance_uploaded")

        form = AcceptanceLetterUploadForm(request.POST, request.FILES, instance=req)

        if not request.FILES.get("acceptance_letter"):
            form.add_error("acceptance_letter", "Please attach the acceptance letter before submitting.")
            return render(request, "placements/student_upload_acceptance.html", {"req": req, "form": form})

        if form.is_valid():
            req = form.save(commit=False)
            req.status = "acceptance_uploaded"
            req.acceptance_uploaded_at = timezone.now()
            req.acceptance_verified = False
            req.acceptance_verified_at = None
            req.save()

            # Delete old file safely (optional)
            if old_name and old_name != req.acceptance_letter.name and default_storage.exists(old_name):
                default_storage.delete(old_name)

            # ✅ Notify all coordinators
            coordinators = get_coordinator_users()
            action_url = reverse("coordinator_acceptance_queue")

            student_name = request.user.display_name
            reg_no = getattr(student, "reg_no", "—")

            title = "Acceptance letter re-uploaded" if was_reupload else "Acceptance letter uploaded"
            message = (
                f"{student_name} (Reg No: {reg_no}) uploaded an acceptance letter.\n"
                f"Please verify the acceptance letter and assign a University Supervisor."
            )

            Notification.objects.bulk_create([
                Notification(
                    user=u,
                    title=title,
                    message=message,
                    level="warning",
                    action_url=action_url,
                    action_text="Open Acceptance Queue",
                    is_read=False,
                )
                for u in coordinators
            ])

            return redirect("my_request")
    else:
        form = AcceptanceLetterUploadForm(instance=req)

    return render(request, "placements/student_upload_acceptance.html", {"req": req, "form": form})



@login_required
@transaction.atomic
def coordinator_verify_acceptance_and_assign(request, request_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    req = get_object_or_404(InternshipRequest, id=request_id)

    if req.status != "acceptance_uploaded":
        return render(request, "placements/verify_not_allowed.html", {"req": req})

    if request.method == "POST":
        form = VerifyAcceptanceAssignSupervisorForm(request.POST, request_period=req.period)
        if form.is_valid():
            supervisor = form.cleaned_data["university_supervisor"]
            start_date = form.cleaned_data["placement_start_date"]
            end_date = form.cleaned_data["placement_end_date"]

            # ensure company exists
            company = req.preferred_company
            if not company:
                return HttpResponseForbidden("No company attached to this request.")

            # mark verified
            req.acceptance_verified = True
            req.acceptance_verified_at = timezone.now()
            req.status = "acceptance_verified"
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

            # create placement now
            placement, _ = Placement.objects.get_or_create(
                request=req,
                defaults={
                    "company": company,
                    "university_supervisor": supervisor,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "active",
                },
            )

            # if existed, update supervisor + activate
            placement.company = company
            placement.university_supervisor = supervisor
            placement.start_date = start_date
            placement.end_date = end_date
            placement.status = "active"
            placement.save()

            return redirect("coordinator_acceptance_queue")
    else:
        form = VerifyAcceptanceAssignSupervisorForm(request_period=req.period)

    return render(request, "placements/coordinator_verify_acceptance.html", {"req": req, "form": form})


@login_required
def coordinator_acceptance_queue(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    qs = InternshipRequest.objects.filter(status="acceptance_uploaded").order_by("-acceptance_uploaded_at")
    return render(request, "placements/coordinator_acceptance_queue.html", {"requests": qs})


from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify

from .models import InternshipRequest  # adjust import if needed


@login_required
def download_recommendation_letter(request, request_id):
    # ✅ Students only
    student = getattr(request.user, "student_profile", None)
    if not student:
        return render(request, "placements/recommendation_letter_page.html", {
            "error_title": "Access denied",
            "error_message": "Students only.",
        }, status=403)

    # ✅ Must belong to this student
    req = get_object_or_404(InternshipRequest, id=request_id, student=student)

    # ✅ Must exist
    if not req.recommendation_letter:
        return render(request, "placements/recommendation_letter_page.html", {
            "req": req,
            "error_title": "Not found",
            "error_message": "No recommendation letter has been uploaded/issued yet.",
        }, status=404)

    # ✅ Must be approved
    if not getattr(req, "recommendation_approved", False):
        return render(request, "placements/recommendation_letter_page.html", {
            "req": req,
            "blocked": True,
            "blocked_reason": "Recommendation letter is awaiting coordinator approval.",
        }, status=403)

    # ✅ If user clicked download -> serve file
    if request.GET.get("download") == "1":
        # nice filename e.g. Recommendation_Letter-john-doe.pdf
        display_name = (request.user.get_full_name() or request.user.username or "student").strip()
        safe_name = slugify(display_name) or "student"
        filename = f"Recommendation_Letter-{safe_name}.pdf"

        return FileResponse(
            req.recommendation_letter.open("rb"),
            as_attachment=True,
            filename=filename,
        )

    # Otherwise render the page with a download button
    return render(request, "placements/recommendation_letter_page.html", {
        "req": req,
        "file_url": f"?download=1",
    })

from .models import InternshipRequest
from .forms import CoordinatorAcceptanceCommentForm

@login_required
def coordinator_return_for_acceptance(request, request_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    req = get_object_or_404(InternshipRequest, id=request_id)

    # Only do this after recommendation has been issued (or already returned)
    if req.status not in ["recommended", "returned_for_acceptance"]:
        return redirect("coordinator_acceptance_queue")

    # If student already uploaded acceptance, no need to return
    if req.acceptance_letter:
        return redirect("coordinator_acceptance_queue")

    if request.method == "POST":
        form = CoordinatorAcceptanceCommentForm(request.POST)
        if form.is_valid():
            req.coordinator_comment = form.cleaned_data["coordinator_comment"]
            req.coordinator_commented_at = timezone.now()
            req.status = "returned_for_acceptance"
            req.save()
            return redirect("coordinator_waiting_acceptance_queue")
    else:
        form = CoordinatorAcceptanceCommentForm(initial={"coordinator_comment": req.coordinator_comment})

    return render(request, "placements/coordinator_return_for_acceptance.html", {"req": req, "form": form})


@login_required
def coordinator_waiting_acceptance_queue(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    qs = InternshipRequest.objects.filter(
        status__in=["recommended", "returned_for_acceptance"],
        acceptance_letter__isnull=True,
    ).order_by("-recommendation_issued_at")

    return render(request, "placements/coordinator_waiting_acceptance_queue.html", {"requests": qs})

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

User = get_user_model()

def get_coordinator_users():
    """
    Find all coordinator users using permission-based role checking.
    Works whether permission is assigned directly OR via group.
    """
    ct = ContentType.objects.get(app_label="accounts", model="user")

    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True)
        |
        Q(user_permissions__codename="role_coordinator", user_permissions__content_type=ct)
        |
        Q(groups__permissions__codename="role_coordinator", groups__permissions__content_type=ct)
    ).distinct()

@login_required
def recommendation_letter_page(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    student = request.user.student_profile

    # ✅ Always pick the latest request for this student
    req = (
        InternshipRequest.objects
        .filter(student=student)
        .order_by("-id")
        .first()
    )

    if not req:
        return render(request, "placements/recommendation_letter_page.html", {
            "error_title": "No internship request found",
            "error_message": "Please submit an internship request first.",
        })

    blocked = True
    blocked_reason = "Recommendation letter is not available yet."
    file_url = None

    # ✅ If not generated yet
    if not req.recommendation_letter:
        blocked = True
        blocked_reason = "Recommendation letter has not been generated yet. Please check again later."

    # ✅ Generated but not approved (pending)
    elif req.recommendation_letter and not req.recommendation_approved:
        blocked = True
        blocked_reason = "Recommendation letter is awaiting coordinator approval."

    # ✅ Approved & issued (student can download)
    elif req.recommendation_letter and req.recommendation_approved:
        blocked = False
        file_url = req.recommendation_letter.url

    return render(request, "placements/recommendation_letter_page.html", {
        "req": req,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "file_url": file_url,
    })
