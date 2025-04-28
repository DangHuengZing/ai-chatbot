# ai_api/views.py

from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
import json
import logging
import requests

logger = logging.getLogger(__name__)

@login_required
def chat_page(request):
    """返回聊天HTML页面"""
    return render(request, 'ai_api/stream_chat.html')

@login_required
def stream_chat(request):
    """处理流式聊天"""
    try:
        body = json.loads(request.body)
        message = body.get('question', '')
        model_type = body.get('model', 'v3')  # 默认使用 v3

        headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'}
        payload = {
            'model': 'deepseek-chat' if model_type == 'v3' else 'deepseek-coder',
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
                                if delta:
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                logger.warning('Invalid JSON data: %s', decoded_line)

            except Exception as e:
                logger.error('Stream error: %s', str(e))
                yield f"data: {json.dumps({'error': '服务暂时不可用'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Error in stream_chat')
        return JsonResponse({'error': str(e)}, status=500)
