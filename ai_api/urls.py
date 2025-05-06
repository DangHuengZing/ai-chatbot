from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_user, name='login'),
    path('stream_chat/', views.stream_chat_page, name='stream_chat_page'),
    path('chat/stream/', views.stream_chat, name='stream_chat'),
]
