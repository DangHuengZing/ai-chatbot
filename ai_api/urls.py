# ai_api/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('chat/stream/', views.stream_chat, name='stream_chat'),  # 流式聊天API
]
