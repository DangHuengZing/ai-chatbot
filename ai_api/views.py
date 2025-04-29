# ai_api/views.py
import json
import logging
import requests
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

@login_required
def stream_chat_page(request):
    """返回聊天页面"""
    return render(request, "ai_api/stream_chat.html")

@csrf_exempt
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3')  # 默认为v3

        api_model = "deepseek-chat" if model == "v3" else "deepseek-coder"
        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': api_model,
            'messages': [{'role': 'user', 'content': question}],
            'stream': True
        }

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            stream=True,
            timeout=60
        )

        if response.status_code != 200:
            logger.error(f"DeepSeek API Error {response.status_code}: {response.text}")
            return JsonResponse({'error': f"DeepSeek API Error {response.status_code}"}, status=500)

        def event_stream():
            """流式读取返回内容"""
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue  # 🛡️ 忽略无关行
                    raw_data = line.removeprefix("data: ").strip()
                    if raw_data == '[DONE]':
                        break
                    try:
                        parsed = json.loads(raw_data)
                        delta = parsed['choices'][0]['delta'].get('content', '')
                        if delta:
                            yield f"data: {json.dumps({'content': delta})}\n\n"
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line: {raw_data} Error: {e}")
            except Exception as e:
                logger.error(f"Stream error: {e}")
                yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")

    except Exception as e:
        logger.exception(f"Unexpected server error: {e}")
        return JsonResponse({'error': str(e)}, status=500)
