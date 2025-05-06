# ai_api/models.py

from django.db import models
from django.contrib.auth.models import User

class ChatMessage(models.Model):
    MODEL_CHOICES = [
        ('v3', 'DeepSeek Chat'),
        ('r1', 'DeepSeek Coder'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    model_type = models.CharField(max_length=2, choices=MODEL_CHOICES)
    role = models.CharField(max_length=20)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_stream = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'model_type']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.timestamp} - {self.model_type}"
