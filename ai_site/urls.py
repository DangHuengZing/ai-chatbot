# ai_site/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('ai_api.urls')),  # 包含 ai_api 的 urls
]
