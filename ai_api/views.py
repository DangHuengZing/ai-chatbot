import json
import logging
import requests
import uuid
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from .models import ChatMessage

logger = logging.getLogger(__name__)

def login_user(request):
    """处理用户登录和渲染登录页面"""
    if request.method == 'GET':
        logger.info("Rendering login.html")
        return render(request, 'ai_api/login.html')
    
    if request.method == 'POST':
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

def logout_user(request):
    """用户登出"""
    if request.method == 'GET':
        logout(request)
        logger.info("User logged out")
        return JsonResponse({'success': True}, status=200)
    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required
def stream_chat_page(request, conversation_id=None):
    """返回聊天页面，并显示历史记录"""
    logger.info(f"Rendering stream_chat.html for user {request.user.username}")

    if conversation_id:
        chat_history = ChatMessage.objects.filter(user=request.user, conversation_id=conversation_id).order_by('timestamp')
    else:
        chat_history = ChatMessage.objects.filter(user=request.user).order_by('timestamp')[:50]

    # Fetch distinct conversations and their first messages
    conversations = ChatMessage.objects.filter(user=request.user).values('conversation_id').distinct()
    conversation_list = []
    for conv in conversations:
        first_message = ChatMessage.objects.filter(
            user=request.user, conversation_id=conv['conversation_id']
        ).order_by('timestamp').first()
        if first_message:  # Only include valid conversations
            conversation_list.append({
                'id': str(conv['conversation_id']),
                'title': first_message.title if first_message.title else first_message.content[:30] or '未命名对话'
            })

    return render(request, 'ai_api/stream_chat.html', {
        'username': request.user.username,
        'chat_history': chat_history,
        'conversations': conversation_list,
        'current_conversation_id': str(conversation_id) if conversation_id else ''
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
        conversation_id = body.get('conversation_id')

        logger.info(f"Received conversation_id: {conversation_id}")

        # Validate or generate conversation_id
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            logger.info(f"Generated new conversation_id: {conversation_id}")
        else:
            try:
                uuid.UUID(conversation_id)
            except ValueError:
                logger.warning(f"Invalid conversation_id received: {conversation_id}")
                conversation_id = str(uuid.uuid4())
                logger.info(f"Generated new conversation_id: {conversation_id}")

        # Check if conversation already exists to prevent duplicates
        existing_conversation = ChatMessage.objects.filter(
            user=request.user, conversation_id=conversation_id
        ).exists()
        if not existing_conversation:
            ChatMessage.objects.create(
                user=request.user,
                conversation_id=conversation_id,
                model_type=model,
                role='user',
                content=question,
                is_stream=True,
                title=question[:30]  # Set title to first 30 chars of question
            )

        if not hasattr(settings, 'DEEPSEEK_API_KEY'):
            logger.error("DeepSeek API key not configured")
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': 'API key not configured'})}\n\n"]),
                content_type="text/event-stream"
            )

        history = ChatMessage.objects.filter(
            user=request.user, conversation_id=conversation_id
        ).order_by('timestamp').values('role', 'content')[:10]
        messages = [
            {'role': 'assistant' if msg['role'] == 'ai' else msg['role'], 'content': msg['content']}
            for msg in history
        ]
        messages.append({'role': 'user', 'content': question})

        api_model = "deepseek-chat" if model == "v3" else "deepseek-coder"
        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': api_model,
            'messages': messages,
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
            full_content = ''
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    raw_data = line.removeprefix("data: ").strip()
                    if raw_data == '[DONE]':
                        if full_content:
                            ChatMessage.objects.create(
                                user=request.user,
                                conversation_id=conversation_id,
                                model_type=model,
                                role='ai',
                                content=full_content,
                                is_stream=True
                            )
                        yield 'data: [DONE]\n\n'
                        break
                    try:
                        parsed = json.loads(raw_data)
                        delta = parsed['choices'][0]['delta'].get('content', '')
                        if delta:
                            full_content += delta
                            yield f"data: {json.dumps({'content': delta, 'conversation_id': conversation_id})}\n\n"
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

@login_required
def get_conversations(request):
    """返回用户的对话列表"""
    conversations = ChatMessage.objects.filter(user=request.user).values('conversation_id').distinct()
    conversation_list = []
    for conv in conversations:
        first_message = ChatMessage.objects.filter(
            user=request.user, conversation_id=conv['conversation_id']
        ).order_by('timestamp').first()
        if first_message:
            conversation_list.append({
                'id': str(conv['conversation_id']),
                'title': first_message.title if first_message.title else first_message.content[:30] or '未命名对话'
            })
    return JsonResponse({'conversations': conversation_list})

@login_required
@csrf_exempt
def delete_conversation(request, conversation_id):
    """删除指定会话的所有消息"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)
    
    try:
        ChatMessage.objects.filter(user=request.user, conversation_id=conversation_id).delete()
        logger.info(f"Conversation {conversation_id} deleted for user {request.user.username}")
        return JsonResponse({'success': True})
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        return JsonResponse({'error': str(e)}, status=500)
