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
        ordering = ['timestamp']  # Oldest first for chronological display
        indexes = [
            models.Index(fields=['user', 'model_type']),
            models.Index(fields=['user', 'conversation_id', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.timestamp} - {self.model_type}"

    @property
    def title(self):
        # Consistent with get_conversations: 30 characters
        return self.content[:30]
