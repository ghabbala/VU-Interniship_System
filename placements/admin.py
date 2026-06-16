from django.contrib import admin
from .models import InternshipPeriod, InternshipRequest, Placement, RecommendationLetterSettings

admin.site.register(InternshipPeriod)
admin.site.register(InternshipRequest)
admin.site.register(Placement)
admin.site.register(RecommendationLetterSettings)
