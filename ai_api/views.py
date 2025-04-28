# ai_api/views.py
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import ChatMessage
import json
import logging
import requests

logger = logging.getLogger(__name__)

# 普通聊天页面
@login_required
def chat(request):
    return JsonResponse({'message': 'Welcome to the chat!'})

# 流式聊天核心逻辑
@login_required
@csrf_exempt
@require_http_methods(["POST"])
def stream_chat(request):
    try:
        # 解析请求参数
        body = json.loads(request.body)
        model_key = body.get('model', 'v3')
        question = body.get('question', '').strip()

        # 验证模型有效性
        if model_key not in ['v3', 'r1']:
            return JsonResponse({'error': '无效模型'}, status=400)

        # 保存用户提问
        ChatMessage.objects.create(user=request.user, model_type=model_key, role='user', content=question, is_stream=True)

        # 构建消息历史
        history_messages = ChatMessage.objects.filter(user=request.user, model_type=model_key).order_by('-timestamp')[:5]
        messages = [{'role': msg.role, 'content': msg.content} for msg in history_messages]
        messages.append({'role': 'user', 'content': question})

        def event_stream():
            headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
            payload = {'model': model_key, 'messages': messages, 'stream': True}
            assistant_content = ""

            try:
                with requests.post('https://api.deepseek.com/v1/chat/completions', headers=headers, json=payload, stream=True) as response:
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
                ChatMessage.objects.create(user=request.user, model_type=model_key, role='assistant', content=assistant_content, is_stream=True)

            except Exception as e:
                logger.error('Stream error: %s', str(e))
                yield f"data: {json.dumps({'error': '服务暂时不可用'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Chat error')
        return JsonResponse({'error': str(e)}, status=500)

# 清空流历史
@login_required
@csrf_exempt
def clear_stream_history(request):
    if request.method == 'POST':
        model_type = json.loads(request.body).get('model')
        ChatMessage.objects.filter(user=request.user, model_type=model_type).delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Method not allowed'}, status=405)
