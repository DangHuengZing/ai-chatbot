import json
import logging
import requests
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login

logger = logging.getLogger(__name__)

def login_user(request):
    """处理用户登录和渲染登录页面"""
    if request.method == 'GET':
        logger.info("Rendering login.html")
        return render(request, 'ai_api/login.html')
    
    if request.method != 'POST':
        logger.error(f"Invalid method: {request.method}")
        return JsonResponse({'error': 'Invalid method'}, status=405)

    try:
        body = json.loads(request.body)
        username = body.get('username')
        password = body.get('password')

        if not username or not password:
            logger.warning("Missing username or password")
            return JsonResponse({'error': '用户名和密码不能为空'}, status=400)

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            logger.info(f"User {username} logged in successfully")
            return JsonResponse({'success': True}, status=200)
        else:
            logger.warning(f"Authentication failed for username: {username}")
            return JsonResponse({'error': '用户名或密码错误'}, status=400)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return JsonResponse({'error': '无效的请求数据'}, status=400)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def stream_chat_page(request):
    """返回聊天页面"""
    logger.info(f"Rendering stream_chat.html for user {request.user.username}")
    return render(request, 'ai_api/stream_chat.html', {
        'username': request.user.username
    })

@login_required
@csrf_exempt
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        logger.error(f"Invalid method: {request.method}")
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3')

        if not question:
            logger.warning("Empty question received")
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': '问题不能为空'})}\n\n"]),
                content_type="text/event-stream"
            )

        if not hasattr(settings, 'DEEPSEEK_API_KEY'):
            logger.error("DeepSeek API key not configured")
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': 'API key not configured'})}\n\n"]),
                content_type="text/event-stream"
            )

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

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            stream=True,
            timeout=60
        )

        if response.status_code != 200:
            logger.error(f"DeepSeek API error {response.status_code}: {response.text}")
            error_msg = f"DeepSeek API error {response.status_code}: {response.text}"
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': error_msg})}\n\n"]),
                content_type="text/event-stream"
            )

        def event_stream():
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    raw_data = line.removeprefix("data: ").strip()
                    if raw_data == '[DONE]':
                        yield 'data: [DONE]\n\n'
                        break
                    try:
                        parsed = json.loads(raw_data)
                        delta = parsed['choices'][0]['delta'].get('content', '')
                        if delta:
                            yield f"data: {json.dumps({'content': delta})}\n\n"
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON: {raw_data}, Error: {e}")
                        yield f"data: {json.dumps({'error': 'Invalid JSON received'})}\n\n"
                        break
            except Exception as e:
                logger.error(f"Stream error: {e}")
                yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"
            finally:
                response.close()

        return StreamingHttpResponse(event_stream(), content_type="text/event-stream")

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return StreamingHttpResponse(
            iter([f"data: {json.dumps({'error': '无效的请求数据'})}\n\n"]),
            content_type="text/event-stream"
        )
    except Exception as e:
        logger.exception(f"Unexpected server error: {e}")
        return StreamingHttpResponse(
            iter([f"data: {json.dumps({'error': str(e)})}\n\n"]),
            content_type="text/event-stream"
        )
