from django.urls import path, include
from . import views

urlpatterns = [
    # 登录处理路由
    path('login/', views.login_user, name='login_user'),
    
    # 流式聊天页面和接口
    path('stream_chat/', views.stream_chat_page, name='stream_chat_page'),  # 返回聊天页面，需要登录
    path('chat/stream/', views.stream_chat, name='stream_chat'),            # 处理流式聊天请求
    
    # 登录登出路由（包括登录页面和注销）
    path('accounts/', include('django.contrib.auth.urls')),  # 包含 Django 的登录、注销、密码管理功能
]
