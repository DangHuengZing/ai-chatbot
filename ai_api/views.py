# ai_api/views.py
from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
import logging
import requests

logger = logging.getLogger(__name__)

@login_required
@csrf_exempt
def stream_chat(request):
    """处理流式聊天请求"""
    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3')

        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': 'deepseek-chat' if model == 'v3' else 'deepseek-coder',
            'messages': [{'role': 'user', 'content': question}],
            'stream': True,
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
                            decoded = line.decode('utf-8').lstrip('data: ')
                            if decoded == '[DONE]':
                                break
                            try:
                                data = json.loads(decoded)
                                delta = data['choices'][0]['delta'].get('content', '')
                                yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                logger.warning('Invalid JSON: %s', decoded)
            except Exception as e:
                logger.error('Stream error: %s', str(e))
                yield f"data: {json.dumps({'error': '流式请求失败'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Error in stream_chat')
        return JsonResponse({'error': str(e)}, status=500)

