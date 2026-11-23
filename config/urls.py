from django.conf import settings
from django.contrib import admin
from django.urls import include, path


urlpatterns = [path("", include("routes.urls"))]
if settings.ENABLE_ADMIN:
    urlpatterns.insert(0, path("admin/", admin.site.urls))
