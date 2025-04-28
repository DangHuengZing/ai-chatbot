# ai_api/views.py
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
import json
import logging
import requests

logger = logging.getLogger(__name__)

@login_required
def stream_chat(request):
    """处理流式聊天请求的视图函数"""
    try:
        # 解析请求中的参数
        body = json.loads(request.body)
        message = body.get('message', '')
        
        # 调用 DeepSeek API（根据实际需求调整）
        headers = {'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'}
        payload = {
            'model': 'deepseek-chat',
            'messages': [{'role': 'user', 'content': message}],
            'stream': True
        }
        
        def event_stream():
            """流式响应生成器"""
            try:
                with requests.post(
                    'https://api.deepseek.com/v1/chat/completions', 
                    headers=headers, 
                    json=payload, 
                    stream=True, 
                    timeout=30
                ) as response:
                    response.raise_for_status()

                    # 处理每一行流式响应
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
                                logger.warning('Invalid JSON data: %s', decoded_line)

            except Exception as e:
                logger.error('Stream error: %s', str(e))
                yield f"data: {json.dumps({'error': '服务暂时不可用'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    except Exception as e:
        logger.exception('Error in stream_chat')
        return JsonResponse({'error': str(e)}, status=500)

from django.http import StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
import json

@csrf_exempt
def stream_response(request):
    """
    流式聊天响应视图，处理用户输入并返回流式输出。
    """
    def generate_response():
        # 示例：模拟流式响应
        messages = ["Hello", " ", "from", " ", "AI", "!"]
        for msg in messages:
            yield json.dumps({"message": msg}) + "\n"
    
    return StreamingHttpResponse(generate_response(), content_type="application/json")
from django.http import HttpResponse

def clear_stream_history(request):
    # 这里实现清空流历史的逻辑，例如清空 session 或数据库记录
    return HttpResponse("Stream history cleared")


