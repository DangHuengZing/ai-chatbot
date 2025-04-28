# ai_api/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path("chat/", views.chat_page, name="chat_page"),       # 返回聊天页面
    path("chat/stream/", views.stream_chat, name="stream_chat"),  # 流式输出
]
