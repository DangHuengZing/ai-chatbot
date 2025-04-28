# ai_api/views.py
from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
import logging
import requests

logger = logging.getLogger(__name__)

@csrf_exempt
@login_required
def stream_chat(request):
    """流式聊天视图"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question')
        model_key = body.get('model', 'v3')

        if not question:
            return JsonResponse({'error': '问题不能为空'}, status=400)

        headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'}
        payload = {
            'model': 'deepseek-chat' if model_key == 'v3' else 'deepseek-coder',
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
                                yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                logger.warning('Invalid JSON: %s', decoded_line)
            except Exception as e:
                logger.error('Streaming error: %s', str(e))
                yield f"data: {json.dumps({'error': '服务器错误'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Unexpected error')
        return JsonResponse({'error': str(e)}, status=500)
