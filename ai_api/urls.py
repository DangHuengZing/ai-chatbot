from django.urls import path, include
from . import views

urlpatterns = [
    # 登录处理路由
    path('login/', views.login_user, name='login_user'),
    
    # 流式聊天页面和接口
    path('stream_chat/', views.stream_chat_page, name='stream_chat_page'),
    path('chat/stream/', views.stream_chat, name='stream_chat'),
    
    # 登录登出路由
    path('accounts/', include('django.contrib.auth.urls')),
]
