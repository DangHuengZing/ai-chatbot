# ai_api/urls.py
from django.urls import path, include
from . import views

urlpatterns = [
    path('stream_chat/', views.stream_chat_page, name='stream_chat_page'),  # 页面
    path('chat/stream/', views.stream_chat, name='stream_chat'),             # 流式聊天接口
    path('accounts/', include('django.contrib.auth.urls')),                  # 登录登出
]
