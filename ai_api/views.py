# ai_api/views.py
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import StreamingHttpResponse, JsonResponse
import requests
import json
import logging

logger = logging.getLogger(__name__)

def stream_chat_page(request):
    """渲染聊天页面"""
    return render(request, 'ai_api/stream_chat.html')  # 确保路径是 ai_api/stream_chat.html

@csrf_exempt
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3')

        if not question:
            return JsonResponse({'error': 'Question is required'}, status=400)

        headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'}
        payload = {
            'model': model,
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
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if line:
                            decoded = line.decode('utf-8').lstrip('data: ')
                            if decoded == '[DONE]':
                                break
                            try:
                                data = json.loads(decoded)
                                delta = data['choices'][0]['delta'].get('content', '')
                                if delta:
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                logger.warning(f"Invalid JSON: {decoded}")
            except Exception as e:
                logger.error(f"Stream error: {str(e)}")
                yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Error in stream_chat')
        return JsonResponse({'error': str(e)}, status=500)
