from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),  # 引入 Django 自带的认证系统 URL
    path('', include('ai_api.urls')),  # 包含 ai_api 的 urls
]
