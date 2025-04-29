# ai_api/views.py

from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import requests
import json
import logging

logger = logging.getLogger(__name__)

@login_required
def stream_chat_page(request):
    """返回聊天页面"""
    return render(request, 'ai_api/stream_chat.html')  # ✅ 注意路径是 templates/ai_api/stream_chat.html

@csrf_exempt
@login_required
def stream_chat(request):
    """处理流式聊天请求"""
    try:
        body = json.loads(request.body)
        message = body.get('question', '')
        model_key = body.get('model', 'v3')  # 默认v3

        model_mapping = {
            'v3': 'deepseek-chat',    # 通用聊天模型
            'r1': 'deepseek-coder',   # 编码助手模型
        }
        model = model_mapping.get(model_key, 'deepseek-chat')  # 映射真实API模型名

        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'
        }
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': message}],
            'stream': True
        }

        def event_stream():
            try:
                with requests.post(
                    'https://api.deepseek.com/v1/chat/completions',
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=60
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
                                if delta:
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                logger.warning('Invalid JSON: %s', decoded_line)
            except Exception as e:
                logger.error(f"Stream error: {str(e)}")
                yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Error in stream_chat')
        return JsonResponse({'error': str(e)}, status=500)
