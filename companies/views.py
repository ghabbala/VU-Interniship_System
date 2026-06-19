from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import redirect, render

from .forms import CoordinatorCompanyForm
from .models import Company


def _is_coordinator(user):
    return user.is_authenticated and (
        user.is_superuser
        or user.has_perm("accounts.role_coordinator")
        or user.has_perm("accounts.role_system_admin")
    )


@login_required
def coordinator_companies(request):
    if not _is_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")

    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    companies = Company.objects.annotate(contact_count=Count("contacts")).order_by("name")

    if query:
        companies = companies.filter(
            Q(name__icontains=query)
            | Q(industry__icontains=query)
            | Q(district__icontains=query)
            | Q(address__icontains=query)
            | Q(contacts__name__icontains=query)
            | Q(contacts__email__icontains=query)
        ).distinct()

    if status:
        companies = companies.filter(status=status)

    return render(request, "companies/coordinator_companies.html", {
        "companies": companies,
        "query": query,
        "status": status,
        "status_choices": Company.STATUS,
    })


@login_required
def coordinator_company_create(request):
    if not _is_coordinator(request.user):
        return HttpResponseForbidden("VU_Coordinators only.")

    request_id = request.POST.get("request_id") or request.GET.get("request_id")
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = ""

    if request.method == "POST":
        form = CoordinatorCompanyForm(request.POST)
        existing_company = Company.objects.filter(name__iexact=(request.POST.get("name") or "").strip()).first()
        if request_id and existing_company:
            from placements.models import InternshipRequest

            if existing_company.status != "approved":
                existing_company.status = "approved"
                existing_company.save(update_fields=["status"])

            InternshipRequest.objects.filter(id=request_id).update(preferred_company=existing_company)
            messages.success(request, f"{existing_company.name} is now linked to this internship request.")
            if next_url:
                return redirect(next_url)
            return redirect("coordinator_companies")

        if form.is_valid():
            company = form.save()
            if request_id:
                from placements.models import InternshipRequest

                InternshipRequest.objects.filter(id=request_id).update(preferred_company=company)
            messages.success(request, f"{company.name} has been added to the company list.")
            if next_url:
                return redirect(next_url)
            return redirect("coordinator_companies")
    else:
        initial = {
            "name": request.GET.get("name", ""),
            "district": request.GET.get("district", ""),
            "address": request.GET.get("address", ""),
            "status": request.GET.get("status", "approved"),
            "contact_phone": request.GET.get("contact_phone", ""),
        }
        form = CoordinatorCompanyForm(initial={key: value for key, value in initial.items() if value})

    return render(request, "companies/coordinator_company_form.html", {
        "form": form,
        "title": "Add Company",
        "next": next_url,
        "request_id": request_id or "",
    })
