# ai_api/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.chat, name='chat'),  # 普通聊天页面
    path("stream_chat/", views.stream_chat, name="stream_chat"),  # 流式聊天
    path("stream_chat/stream/", views.stream_response, name="stream_response"),  # 流式聊天响应
    path("stream_chat/clear/", views.clear_stream_history, name="clear_stream_history"),  # 清空流历史
]
