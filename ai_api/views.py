# ai_api/views.py
from django.shortcuts import render
from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import requests
import json
import logging

logger = logging.getLogger(__name__)

@login_required
def stream_chat_page(request):
    """返回聊天页面"""
    return render(request, 'ai_api/stream_chat.html')

@csrf_exempt
@login_required
def stream_chat(request):
    """处理流式聊天后端逻辑"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST is allowed'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3')

        headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'}
        payload = {
            'model': f'deepseek-chat-{model}',
            'messages': [{'role': 'user', 'content': question}],
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
                                    yield f'data: {json.dumps({"content": delta})}\n\n'
                            except json.JSONDecodeError:
                                logger.warning('Invalid JSON line: %s', decoded_line)

            except Exception as e:
                logger.error('Streaming error: %s', str(e))
                yield f'data: {json.dumps({"error": "出错了，请稍后再试。"})}\n\n'

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Stream Chat Error')
        return JsonResponse({'error': str(e)}, status=500)
