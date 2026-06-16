from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from .forms import CoordinatorCompanyForm
from .models import Company


def _is_coordinator(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_coordinator")
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

    if request.method == "POST":
        form = CoordinatorCompanyForm(request.POST)
        if form.is_valid():
            company = form.save()
            messages.success(request, f"{company.name} has been added to the company list.")
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url:
                return redirect(next_url)
            return redirect("coordinator_companies")
    else:
        form = CoordinatorCompanyForm()

    return render(request, "companies/coordinator_company_form.html", {
        "form": form,
        "title": "Add Company",
        "next": request.GET.get("next", ""),
    })
