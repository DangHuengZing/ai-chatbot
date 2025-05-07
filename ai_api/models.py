from django.db import models
from django.contrib.auth.models import User
import uuid

class ChatMessage(models.Model):
    MODEL_CHOICES = [
        ('v3', 'DeepSeek Chat'),
        ('r1', 'DeepSeek Coder'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    conversation_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    model_type = models.CharField(max_length=2, choices=MODEL_CHOICES)
    role = models.CharField(max_length=20)  # 'user' or 'ai'
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_stream = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'model_type']),
            models.Index(fields=['user', 'conversation_id', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.timestamp} - {self.model_type}"

    @property
    def title(self):
        # 返回前20个字符作为对话标题，可以根据需要优化
        return self.content[:20]
