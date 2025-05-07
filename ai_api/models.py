from django.db import models
from django.contrib.auth.models import User
import uuid

class ChatMessage(models.Model):
    # 定义模型选择项
    MODEL_CHOICES = [
        ('v3', 'DeepSeek Chat'),
        ('r1', 'DeepSeek Coder'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_messages')
    conversation_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)  # 会话ID
    model_type = models.CharField(max_length=2, choices=MODEL_CHOICES)  # 模型类型
    role = models.CharField(max_length=20)  # 角色：'user' 或 'ai'
    content = models.TextField()  # 消息内容
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)  # 消息时间戳
    is_stream = models.BooleanField(default=False)  # 是否为流式消息

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['user', 'conversation_id', 'timestamp']),  # 增加对 `conversation_id` 的索引
        ]

    def __str__(self):
        return f"{self.user.username} - {self.timestamp} - {self.model_type}"

