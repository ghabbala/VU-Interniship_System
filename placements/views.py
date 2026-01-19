from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import InternshipPeriod, InternshipRequest, Placement
from .forms import InternshipRequestForm

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


def is_coordinator(user):
    return user.is_superuser or user.groups.filter(name__in=["Coordinator", "Admin"]).exists()

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
                # Prevent submitting if already submitted onward
                if req.status in ["submitted", "under_review", "recommended", "acceptance_uploaded", "acceptance_verified"]:
                    req.save()
                    return redirect("my_request")

                # Must pick or propose a company before submitting
                if not req.preferred_company and not (req.proposed_company_name or "").strip():
                    form.add_error(None, "Please select an approved company or propose a company before submitting.")
                    return render(request, "placements/my_request.html", {"form": form, "req": req, "period": period})

                req.status = "submitted"
                req.submitted_at = timezone.now()  # make sure this field exists in model
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
    if not is_coordinator(request.user):
        return redirect("dashboard")

    qs = InternshipRequest.objects.filter(status__in=["submitted", "under_review"]).order_by("-submitted_at")
    return render(request, "placements/coordinator_queue.html", {"requests": qs})

@login_required
def coordinator_review(request, request_id):
    if not is_coordinator(request.user):
        return redirect("dashboard")

    req = get_object_or_404(InternshipRequest, id=request_id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "mark_under_review":
            req.status = "under_review"
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

        elif action == "reject":
            req.status = "rejected"
            req.review_notes = request.POST.get("review_notes", "")
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

        elif action == "approve_and_create_placement":
            # if student proposed a company, create it (pending verification OR approved based on your policy)
            company = req.preferred_company
            if not company:
                company, _ = Company.objects.get_or_create(
                    name=req.proposed_company_name.strip(),
                    defaults={
                        "district": req.proposed_company_district,
                        "address": req.proposed_company_address,
                        "status": "approved",  # you can change to pending_verification if you want strict approval
                    },
                )

            # create placement (you can later add supervisor assignment UI)
            Placement.objects.get_or_create(
                request=req,
                defaults={
                    "company": company,
                    "start_date": req.period.start_date,
                    "end_date": req.period.end_date,
                    "status": "pending_student_ack",
                },
            )

            req.status = "approved"
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

        return redirect("coordinator_review", request_id=req.id)

    return render(request, "placements/coordinator_review.html", {"req": req})

@login_required
def coordinator_issue_recommendation(request, request_id):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    req = get_object_or_404(InternshipRequest, id=request_id)

    if request.method == "POST":
        form = RecommendationLetterForm(request.POST, request.FILES, instance=req)
        if form.is_valid():
            # If proposed company, ensure it exists (approved or pending based on your policy)
            if not req.preferred_company and req.proposed_company_name.strip():
                company, _ = Company.objects.get_or_create(
                    name=req.proposed_company_name.strip(),
                    defaults={
                        "district": req.proposed_company_district,
                        "address": req.proposed_company_address,
                        "status": "approved",  # change to pending_verification if you want strict vetting
                    },
                )
                req.preferred_company = company

            form.save()
            req.status = "recommended"
            req.recommendation_issued_at = timezone.now()
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

            return redirect("coordinator_queue")
    else:
        form = RecommendationLetterForm(instance=req)

    return render(request, "placements/coordinator_issue_recommendation.html", {"req": req, "form": form})



@login_required
def student_upload_acceptance(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    student = request.user.student_profile
    period = InternshipPeriod.objects.filter(is_active=True).first()
    if not period:
        return render(request, "placements/no_active_period.html")

    req = get_object_or_404(InternshipRequest, student=student, period=period)

    # Block if verified (recommended)
    if req.status == "acceptance_verified":
        return render(request, "placements/acceptance_not_allowed.html", {"req": req})

    # Allow upload + re-upload
    if req.status not in ["recommended", "returned_for_acceptance", "acceptance_uploaded"]:
        return render(request, "placements/acceptance_not_allowed.html", {"req": req})

    if request.method == "POST":
        # ✅ capture old file BEFORE form binds the new one
        old_name = req.acceptance_letter.name if req.acceptance_letter else None

        form = AcceptanceLetterUploadForm(request.POST, request.FILES, instance=req)

        if not request.FILES.get("acceptance_letter"):
            form.add_error("acceptance_letter", "Please attach the acceptance letter before submitting.")
            return render(request, "placements/student_upload_acceptance.html", {"req": req, "form": form})

        if form.is_valid():
            # ✅ save new file first (do NOT delete req.acceptance_letter here)
            req = form.save(commit=False)
            req.status = "acceptance_uploaded"
            req.acceptance_uploaded_at = timezone.now()
            req.acceptance_verified = False
            req.acceptance_verified_at = None
            req.save()

            # ✅ now delete the old file safely (optional)
            if old_name and old_name != req.acceptance_letter.name and default_storage.exists(old_name):
                default_storage.delete(old_name)

            return redirect("my_request")
    else:
        form = AcceptanceLetterUploadForm(instance=req)

    return render(request, "placements/student_upload_acceptance.html", {"req": req, "form": form})


@login_required
@transaction.atomic
def coordinator_verify_acceptance_and_assign(request, request_id):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    req = get_object_or_404(InternshipRequest, id=request_id)

    if req.status != "acceptance_uploaded":
        return render(request, "placements/verify_not_allowed.html", {"req": req})

    if request.method == "POST":
        form = VerifyAcceptanceAssignSupervisorForm(request.POST)
        if form.is_valid():
            supervisor = form.cleaned_data["university_supervisor"]

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
                    "start_date": req.period.start_date,
                    "end_date": req.period.end_date,
                    "status": "active",
                },
            )

            # if existed, update supervisor + activate
            placement.company = company
            placement.university_supervisor = supervisor
            placement.status = "active"
            placement.save()

            return redirect("coordinator_acceptance_queue")
    else:
        form = VerifyAcceptanceAssignSupervisorForm()

    return render(request, "placements/coordinator_verify_acceptance.html", {"req": req, "form": form})


@login_required
def coordinator_acceptance_queue(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    qs = InternshipRequest.objects.filter(status="acceptance_uploaded").order_by("-acceptance_uploaded_at")
    return render(request, "placements/coordinator_acceptance_queue.html", {"requests": qs})


@login_required
def download_recommendation_letter(request, request_id):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    req = get_object_or_404(
        InternshipRequest,
        id=request_id,
        student=request.user.student_profile,
    )

    if not req.recommendation_letter:
        raise Http404("No recommendation letter found.")

    return FileResponse(
        req.recommendation_letter.open("rb"),
        as_attachment=True,
        filename="Recommendation_Letter.pdf",
    )

from .models import InternshipRequest
from .forms import CoordinatorAcceptanceCommentForm

@login_required
def coordinator_return_for_acceptance(request, request_id):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

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
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    qs = InternshipRequest.objects.filter(
        status__in=["recommended", "returned_for_acceptance"],
        acceptance_letter__isnull=True,
    ).order_by("-recommendation_issued_at")

    return render(request, "placements/coordinator_waiting_acceptance_queue.html", {"requests": qs})

