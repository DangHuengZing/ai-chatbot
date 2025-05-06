import json
import logging
import requests
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from ai_api.models import ChatMessage
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login

logger = logging.getLogger(__name__)

# 聊天页面视图（需要登录）
@login_required
def stream_chat_page(request):
    """返回聊天页面，并传递当前用户信息"""
    logger.info("Rendering stream_chat.html with updated content")  # 确认加载最新模板
    return render(request, "ai_api/stream_chat.html", {
        'username': request.user.username
    })

# 流式聊天的处理
@login_required
@csrf_exempt
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        # 从请求中获取问题和所选模型
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3')

        # 选择 DeepSeek 模型
        api_model = "deepseek-chat" if model == "v3" else "deepseek-reasoner"
        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': api_model,
            'messages': [{'role': 'user', 'content': question}],
            'stream': True
        }

        # 发送请求到 DeepSeek API
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            stream=True,
            timeout=60
        )

        # 检查 API 响应状态
        if response.status_code != 200:
            logger.error(f"DeepSeek API Error {response.status_code}: {response.text}")
            error_msg = f"DeepSeek API Error {response.status_code}: {response.text}"
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': error_msg})}\n\n"]),
                content_type="text/event-stream"
            )

        # 存储聊天记录的流式处理
        def event_stream():
            """流式读取 DeepSeek API 返回内容，并转发给前端"""
            try:
                # 获取 DeepSeek API 响应数据流
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue  # 忽略无关行
                    raw_data = line.removeprefix("data: ").strip()
                    if raw_data == '[DONE]':
                        break
                    try:
                        parsed = json.loads(raw_data)
                        delta = parsed['choices'][0]['delta'].get('content', '')
                        if delta:
                            # 保存聊天记录到数据库
                            user = User.objects.get(username=request.user.username)  # 获取当前登录的用户对象
                            # 保存用户消息
                            ChatMessage.objects.create(
                                user=user,
                                model_type=model,
                                role='user',
                                content=question,
                                is_stream=True
                            )
                            # 保存AI回应
                            ChatMessage.objects.create(
                                user=user,
                                model_type=model,
                                role='ai',
                                content=delta,
                                is_stream=True
                            )

                            yield f"data: {json.dumps({'content': delta})}\n\n"
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON: {raw_data}, Error: {e}")
                        yield f"data: {json.dumps({'error': 'Invalid JSON received from API'})}\n\n"
                        break
            except Exception as e:
                logger.error(f"Stream error: {e}")
                yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")

    except Exception as e:
        logger.exception("Unexpected server error")
        return StreamingHttpResponse(
            iter([f"data: {json.dumps({'error': str(e)})}\n\n"]),
            content_type="text/event-stream"
        )

# 用户登录视图
@csrf_exempt
def login_user(request):
    """处理用户登录"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)

    try:
        body = json.loads(request.body)
        username = body.get('username')
        password = body.get('password')

        # 验证用户
        user = authenticate(request, username=username, password=password)
        if user is not None:
            # 登录成功
            login(request, user)
            return JsonResponse({'message': 'Login successful'}, status=200)
        else:
            # 用户名或密码错误
            return JsonResponse({'error': '用户名或密码错误，请重新尝试'}, status=400)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
