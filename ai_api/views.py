# ai_api/views.py
from django.conf import settings  # 添加这一行
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
import json
import logging
import requests

logger = logging.getLogger(__name__)

@login_required
def stream_response(request):
    """处理流式聊天响应的视图函数"""
    try:
        # 解析请求中的参数
        body = json.loads(request.body)
        message = body.get('message', '')
        
        # 调用 DeepSeek API（你可以根据实际情况调整）
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
        logger.exception('Error in stream_response')
        return JsonResponse({'error': str(e)}, status=500)
