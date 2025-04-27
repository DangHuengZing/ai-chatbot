# ai_api/models.py
from django.db import models
from django.contrib.auth.models import User
from .models import ChatMessage  # 从models导入而不是重新定义

    
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

# ai_api/views.py
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
import requests
import logging
from .models import ChatMessage

logger = logging.getLogger(__name__)

API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL_MAP = {
    'v3': {'name': 'deepseek-chat', 'desc': '通用聊天模型'},
    'r1': {'name': 'deepseek-coder', 'desc': '代码专用模型'}
}

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def stream_chat(request):
    """流式聊天核心逻辑"""
    try:
        # 解析请求参数
        body = json.loads(request.body)
        model_key = body.get('model', 'v3')
        question = body.get('question', '').strip()
        
        # 验证模型有效性
        if model_key not in MODEL_MAP:
            return JsonResponse({'error': '无效模型'}, status=400)
        
        # 保存用户提问
        ChatMessage.objects.create(
            user=request.user,
            model_type=model_key,
            role='user',
            content=question,
            is_stream=True
        )
        
        # 构建消息历史（最近5条）
        history_messages = ChatMessage.objects.filter(
            user=request.user,
            model_type=model_key
        ).order_by('-timestamp')[:5]
        
        messages = [
            {'role': msg.role, 'content': msg.content}
            for msg in history_messages
        ]
        messages.append({'role': 'user', 'content': question})

        def event_stream():
            """流式响应生成器"""
            headers = {
                'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            }
            payload = {
                'model': MODEL_MAP[model_key]['name'],
                'messages': messages,
                'stream': True,
                'temperature': 0.7
            }
            
            assistant_content = ""
            try:
                with requests.post(
                    API_URL,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=30
                ) as response:
                    response.raise_for_status()
                    
                    for line in response.iter_lines():
                        if line:
                            decoded_line = line.decode('utf-8').lstrip('data: ')
                            if decoded_line == '[DONE]':
                                break
                            
                            try:
                                data = json.loads(decoded_line)
                                delta = data['choices'][0]['delta'].get('content', '')
                                assistant_content += delta
                                yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                logger.warning('Invalid JSON data: %s', decoded_line)
                                
                # 保存完整回复
                ChatMessage.objects.create(
                    user=request.user,
                    model_type=model_key,
                    role='assistant',
                    content=assistant_content,
                    is_stream=True
                )
                
            except Exception as e:
                logger.error('Stream error: %s', str(e))
                yield f"data: {json.dumps({'error': '服务暂时不可用'})}\n\n"

        return StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        
    except Exception as e:
        logger.exception('Chat error')
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def chat_history(request):
    """获取聊天历史"""
    try:
        model_type = request.GET.get('model')
        messages = ChatMessage.objects.filter(
            user=request.user,
            model_type=model_type
        ).order_by('timestamp')[:50]
        
        return JsonResponse([
            {
                'id': msg.id,
                'role': msg.role,
                'content': msg.content,
                'timestamp': msg.timestamp.isoformat(),
                'model': msg.model_type
            }
            for msg in messages
        ], safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
@csrf_exempt
def clear_history(request):
    """清空指定模型的聊天历史"""
    if request.method == 'POST':
        model_type = json.loads(request.body).get('model')
        ChatMessage.objects.filter(
            user=request.user,
            model_type=model_type
        ).delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Method not allowed'}, status=405)
