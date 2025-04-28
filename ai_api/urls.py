# ai_api/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("stream_chat/", views.stream_chat, name="stream_chat"),  # 流式聊天
    path("stream_chat/stream/", views.stream_response, name="stream_response"),  # 流式聊天响应
    path("stream_chat/clear/", views.clear_stream_history, name="clear_stream_history"),  # 清空流历史
]
# ai_site/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('ai_api.urls')),  # 包含 ai_api 的 urls
]
