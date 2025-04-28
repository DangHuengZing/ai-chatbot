# ai_api/views.py
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
import json
import logging
import requests
from .models import ChatMessage  # 导入 ChatMessage 模型

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

# 处理流式响应：向 DeepSeek API 发送请求，获取流式输出
@csrf_exempt
def stream_response(request):
    """
    这个视图用于处理流式聊天响应，实际获取 DeepSeek API 响应并返回流式输出。
    """
    try:
        # 解析请求中的参数
        body = json.loads(request.body)
        message = body.get('message', '')
        
        # 调用 DeepSeek API 获取流式响应
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

        return StreamingHttpResponse(event_stream(), content_type="application/json")

    except Exception as e:
        logger.exception('Error in stream_response')
        return JsonResponse({'error': str(e)}, status=500)

# 清空流历史记录
def clear_stream_history(request):
    """清空指定用户的聊天历史"""
    try:
        # 删除用户与模型相关的聊天记录
        model_type = request.GET.get('model')  # 获取模型类型
        ChatMessage.objects.filter(user=request.user, model_type=model_type).delete()  # 删除历史记录

        return HttpResponse("Stream history cleared", status=200)
    
    except Exception as e:
        logger.error(f"Error clearing history: {str(e)}")
        return HttpResponse(f"Error clearing history: {str(e)}", status=500)
