from django.contrib import admin
from .models import InternshipPeriod, InternshipRequest, Placement

admin.site.register(InternshipPeriod)
admin.site.register(InternshipRequest)
admin.site.register(Placement)
