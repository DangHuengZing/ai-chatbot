from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.chat, name='chat'),
    path("stream_chat/", views.stream_chat, name="stream_chat"),
    path("stream_chat/stream/", views.stream_response, name="stream_response"),
    path("stream_chat/clear/", views.clear_stream_history, name="clear_stream_history"),  # 新增
    path("chat/", views.chat, name="chat"),  # 可选：保留普通聊天页面
]
