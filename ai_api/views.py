import json
import logging
import requests
import uuid
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt # csrf_exempt 应该谨慎使用，确保了解其含义
from django.contrib.auth import authenticate, login, logout
from .models import ChatMessage
from django.core.serializers.json import DjangoJSONEncoder # 用于处理 datetime 对象序列化

logger = logging.getLogger(__name__)

def login_user(request):
    """处理用户登录和渲染登录页面"""
    if request.method == 'GET':
        return render(request, 'ai_api/login.html')
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            username = body.get('username')
            password = body.get('password')
            if not username or not password:
                return JsonResponse({'error': '用户名和密码不能为空'}, status=400)
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return JsonResponse({'success': True}, status=200)
            return JsonResponse({'error': '用户名或密码错误'}, status=400)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的请求数据'}, status=400)
        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)

def logout_user(request):
    """用户登出"""
    if request.method == 'GET': # 通常登出是POST请求以防止CSRF，但此处按原样保留GET
        logout(request)
        return JsonResponse({'success': True}, status=200)
    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required
def stream_chat_page(request, conversation_id=None):
    """返回聊天页面"""
    # 注意：chat_history 不再在此处主要用于初始渲染，前端将通过API获取
    # 但可以保留用于非JS环境或快速预览（如果模板支持）
    # initial_messages = []
    # if conversation_id:
    #     try:
    #         conv_id_uuid = uuid.UUID(str(conversation_id)) # Ensure it's a UUID object for query
    #         message_qs = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid).order_by('timestamp')
    #         initial_messages = [
    #             {
    #                 'sender': 'ai' if msg.role == 'ai' else 'user',
    #                 'content': msg.content,
    #                 'timestamp': msg.timestamp.isoformat()
    #             } for msg in message_qs
    #         ]
    #     except ValueError: # Invalid UUID
    #         conversation_id = None # Treat as new chat if ID is invalid
    #     except Exception as e:
    #         logger.error(f"Error fetching initial messages for {conversation_id}: {e}")
    #         conversation_id = None


    return render(request, 'ai_api/stream_chat.html', {
        'username': request.user.username,
        # 'initial_messages_json': json.dumps(initial_messages, cls=DjangoJSONEncoder), # 可以选择传递JSON供前端使用
        'current_conversation_id': str(conversation_id) if conversation_id else ''
    })

# csrf_exempt 通常用于外部API回调，对于session认证的内部API，应使用Django的CSRF保护机制
# 如果前端总是通过 AJAX 发送 CSRF token，则可以移除 @csrf_exempt 并确保前端发送
@login_required
# @csrf_exempt # 考虑移除，如果前端正确发送 CSRF token
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model = body.get('model', 'v3') # 默认 v3
        conversation_id_str = body.get('conversation_id') # 可能为 null 或空字符串

        is_new_conversation = False
        if not conversation_id_str or conversation_id_str == 'null': # 前端可能发送 'null' 字符串
            conversation_id = uuid.uuid4()
            is_new_conversation = True
            logger.info(f"New conversation started with ID: {conversation_id}")
        else:
            try:
                conversation_id = uuid.UUID(conversation_id_str) # 验证并转换为UUID对象
            except ValueError:
                logger.warning(f"Invalid conversation_id format received: {conversation_id_str}. Starting new conversation.")
                conversation_id = uuid.uuid4()
                is_new_conversation = True
        
        # 保存用户消息
        ChatMessage.objects.create(
            user=request.user,
            conversation_id=conversation_id, # 使用UUID对象
            model_type=model,
            role='user',
            content=question,
            is_stream=True # 标记这是流式交互的一部分
        )

        if not hasattr(settings, 'DEEPSEEK_API_KEY') or not settings.DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API_KEY not configured.")
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': 'API key not configured'})}\n\n", "data: [DONE]\n\n"]),
                content_type="text/event-stream"
            )

        # 准备发送给DeepSeek API的消息历史
        # 注意：这里限制了历史消息数量，可以调整
        history_qs = ChatMessage.objects.filter(
            user=request.user, 
            conversation_id=conversation_id
        ).exclude(role='user', content=question).order_by('-timestamp')[:10] # 取最近的10条（不包括当前问题）
        
        messages_for_api = [{'role': 'assistant' if msg.role == 'ai' else msg.role, 'content': msg.content} for msg in reversed(history_qs)] # API需要正序
        messages_for_api.append({'role': 'user', 'content': question})


        api_model = "deepseek-chat" if model == "v3" else "deepseek-coder"
        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': api_model,
            'messages': messages_for_api,
            'stream': True
        }
        
        logger.debug(f"Sending to DeepSeek API: {payload}")

        try:
            api_response = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                stream=True,
                timeout=60 # 增加超时
            )
            api_response.raise_for_status() # 如果状态码是 4xx 或 5xx，则抛出 HTTPError
        except requests.exceptions.RequestException as e:
            logger.error(f"DeepSeek API request failed: {e}")
            return StreamingHttpResponse(
                iter([f"data: {json.dumps({'error': f'API request error: {e}'})}\n\n", "data: [DONE]\n\n"]),
                content_type="text/event-stream"
            )

        def event_stream_generator():
            full_ai_content = ""
            sent_conversation_id_in_stream = False # 标志是否已在流中发送过ID
            try:
                for line_bytes in api_response.iter_lines(): # iter_lines 返回字节串
                    if not line_bytes:
                        continue
                    
                    line = line_bytes.decode('utf-8').strip() # 解码并去除空白
                    
                    if not line.startswith("data:"):
                        continue
                    
                    raw_data = line.removeprefix("data:").strip()
                    
                    if raw_data == '[DONE]':
                        logger.info(f"DeepSeek stream finished for conv {conversation_id}. Full AI content length: {len(full_ai_content)}")
                        if full_ai_content: # 只有当AI有实际内容时才保存
                            ChatMessage.objects.create(
                                user=request.user,
                                conversation_id=conversation_id, # 使用UUID对象
                                model_type=model,
                                role='ai',
                                content=full_ai_content,
                                is_stream=True
                            )
                        yield 'data: [DONE]\n\n'
                        break 
                    
                    try:
                        parsed_chunk = json.loads(raw_data)
                        delta_content = parsed_chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                        
                        if delta_content:
                            full_ai_content += delta_content
                            data_to_send = {'content': delta_content}
                            # 仅在第一次发送内容时，如果这是一个新对话，则附带 conversation_id
                            if is_new_conversation and not sent_conversation_id_in_stream:
                                data_to_send['conversation_id'] = str(conversation_id)
                                sent_conversation_id_in_stream = True
                            yield f"data: {json.dumps(data_to_send)}\n\n"

                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON received from DeepSeek stream: {raw_data}")
                        #可以选择性地向客户端发送错误，或者忽略这个损坏的块
                        # yield f"data: {json.dumps({'error': 'Invalid JSON chunk in stream'})}\n\n"
                        continue # 继续尝试处理流中的下一行
                    except Exception as e:
                        logger.error(f"Error processing DeepSeek stream chunk: {e}", exc_info=True)
                        yield f"data: {json.dumps({'error': f'Error processing stream: {e}'})}\n\n"
                        break
            finally:
                api_response.close() # 确保 response 被关闭
                logger.debug(f"Closed DeepSeek API response for conv {conversation_id}")
        
        # 对于 StreamingHttpResponse，通常不直接设置 headers 来传递 X-Conversation-Id
        # conversation_id 将在流的第一个数据块中传递（如果is_new_conversation）
        return StreamingHttpResponse(event_stream_generator(), content_type="text/event-stream")

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body for stream_chat", exc_info=True)
        return StreamingHttpResponse(
            iter([f"data: {json.dumps({'error': '无效的请求数据'})}\n\n", "data: [DONE]\n\n"]),
            content_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"Unhandled error in stream_chat: {e}", exc_info=True)
        return StreamingHttpResponse(
            iter([f"data: {json.dumps({'error': f'服务器内部错误: {e}'})}\n\n", "data: [DONE]\n\n"]),
            content_type="text/event-stream"
        )

@login_required
def get_conversations(request):
    """返回用户的对话列表，确保标题的获取是高效的"""
    # 获取所有不同的 conversation_id
    conversation_ids = ChatMessage.objects.filter(user=request.user).values_list('conversation_id', flat=True).distinct()
    
    conversation_list = []
    for conv_id in conversation_ids:
        # 获取每个对话的第一条消息作为标题
        first_message = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id).order_by('timestamp').first()
        if first_message:
            title = first_message.content[:30] # 取前30个字符
            if len(first_message.content) > 30:
                title += "..."
            conversation_list.append({
                'id': str(conv_id),
                'title': title
            })
        # else: # 如果一个对话ID存在但没有任何消息（理论上不应该），可以忽略或给默认标题
            # conversation_list.append({'id': str(conv_id), 'title': '空对话'})
            
    return JsonResponse({'conversations': sorted(conversation_list, key=lambda x: x.get('title', 'zzzz'))}) # 可选：按标题排序


@login_required
def get_conversation_messages(request, conversation_id): # 新增的 view
    """返回指定会话的所有消息"""
    if not conversation_id:
        return JsonResponse({'error': 'Conversation ID is required'}, status=400)
    
    try:
        # conversation_id 从URL传来的是字符串，如果模型字段是UUIDField，需要转换
        conv_id_uuid = uuid.UUID(str(conversation_id)) 
        messages_qs = ChatMessage.objects.filter(
            user=request.user, 
            conversation_id=conv_id_uuid
        ).order_by('timestamp').values('role', 'content', 'timestamp')

        messages_list = [
            {
                'sender': 'ai' if msg['role'] == 'ai' else 'user',
                'content': msg['content'],
                'timestamp': msg['timestamp'].isoformat() # 使用ISO格式方便前端解析
            } for msg in messages_qs
        ]
        # 使用 encoder 参数指定自定义的 JSON 编码器
        return JsonResponse({'messages': messages_list}, encoder=DjangoJSONEncoder) 
    except ValueError: # Handle invalid UUID format from URL
        logger.warning(f"Invalid UUID format for conversation_id: {conversation_id}")
        return JsonResponse({'error': 'Invalid Conversation ID format'}, status=400)
    except Exception as e:
        logger.error(f"Error fetching messages for conversation {conversation_id}: {e}", exc_info=True)
        return JsonResponse({'error': f'Error fetching messages: {e}'}, status=500)


@login_required
# @csrf_exempt # 同上，考虑移除
def delete_conversation(request, conversation_id):
    """删除指定会话的所有消息"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)
    
    try:
        conv_id_uuid = uuid.UUID(str(conversation_id)) # 转换为 UUID 对象
        count, _ = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid).delete()
        logger.info(f"Deleted {count} messages for conversation {conversation_id} for user {request.user.username}")
        return JsonResponse({'success': True})
    except ValueError:
        logger.warning(f"Invalid UUID format for deletion: {conversation_id}")
        return JsonResponse({'error': 'Invalid Conversation ID format for deletion'}, status=400)
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
