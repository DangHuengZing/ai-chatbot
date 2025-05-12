from django.urls import path
from . import views

app_name = 'ai_api' # 保持 app_name 简洁

urlpatterns = [
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),

    # 为了区分，给 stream_chat_page 不同的名字，虽然它们指向同一个view
    # 但通常 Django 会根据参数来区分，所以原来的 'stream_chat_page' 和 'stream_chat_conversation' 也可以
    # 这里为了更清晰，稍微修改一下 name
    path('stream_chat/', views.stream_chat_page, name='stream_chat_new'), # 用于新建聊天
    path('stream_chat/<uuid:conversation_id>/', views.stream_chat_page, name='stream_chat_existing'), # 用于加载现有聊天

    path('chat/stream/', views.stream_chat, name='stream_chat_api'), # API 用于发送消息并获取流式响应
    path('chat/conversations/', views.get_conversations, name='get_conversations_api'), # API 获取对话列表
    path('chat/delete/<uuid:conversation_id>/', views.delete_conversation, name='delete_conversation_api'), # API 删除对话
    
    # 新增：API 用于获取特定对话的消息历史
    path('chat/messages/<uuid:conversation_id>/', views.get_conversation_messages, name='get_conversation_messages_api'),
]
