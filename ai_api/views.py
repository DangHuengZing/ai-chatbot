# ai_api/views.py

import json
import logging
import requests
import uuid
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
# from django.views.decorators.csrf import csrf_exempt # 考虑移除，如果前端正确发送 CSRF token
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
    if request.method == 'GET': 
        logout(request)
        return JsonResponse({'success': True}, status=200)
    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required
def stream_chat_page(request, conversation_id=None):
    """返回聊天页面"""
    # 初始消息将由前端通过API加载
    return render(request, 'ai_api/stream_chat.html', {
        'username': request.user.username,
        'current_conversation_id': str(conversation_id) if conversation_id else ''
    })


@login_required
# @csrf_exempt # 考虑移除，如果前端正确发送 CSRF token
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model_choice = body.get('model', 'v3') # 从前端获取模型选择
        conversation_id_str = body.get('conversation_id')

        is_new_conversation = False
        if not conversation_id_str or conversation_id_str.lower() == 'null' or conversation_id_str.lower() == 'undefined':
            conversation_id = uuid.uuid4()
            is_new_conversation = True
            logger.info(f"New conversation started with ID: {conversation_id} for user {request.user.username}, model: {model_choice}")
        else:
            try:
                conversation_id = uuid.UUID(conversation_id_str)
                logger.info(f"Continuing conversation ID: {conversation_id} for user {request.user.username}, model: {model_choice}")
            except ValueError:
                logger.warning(f"Invalid conversation_id format: {conversation_id_str}. Starting new for user {request.user.username}, model: {model_choice}.")
                conversation_id = uuid.uuid4()
                is_new_conversation = True
        
        ChatMessage.objects.create(
            user=request.user,
            conversation_id=conversation_id, 
            model_type=model_choice, # 保存选择的模型
            role='user',
            content=question,
            is_stream=True 
        )

        if not hasattr(settings, 'DEEPSEEK_API_KEY') or not settings.DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API_KEY not configured.")
            # 确保即使出错也发送 [DONE] 信号
            def error_stream_key():
                yield f"data: {json.dumps({'error': 'API key not configured'})}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_key(), content_type="text/event-stream")

        # 获取最近的10条历史消息（不包括当前用户刚发送的这条）
        history_qs = ChatMessage.objects.filter(
            user=request.user, 
            conversation_id=conversation_id
        ).exclude(pk=ChatMessage.objects.filter(user=request.user, conversation_id=conversation_id, role='user', content=question).latest('timestamp').pk).order_by('-timestamp')[:10]
        
        messages_for_api = [{'role': 'assistant' if msg.role == 'ai' else msg.role, 'content': msg.content} for msg in reversed(history_qs)] 
        messages_for_api.append({'role': 'user', 'content': question})


        api_model_name = "deepseek-chat" if model_choice == "v3" else "deepseek-coder"
        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json',
            'Accept': 'application/json' # 有些API可能需要
        }
        payload = {
            'model': api_model_name,
            'messages': messages_for_api,
            'stream': True,
            # 'temperature': 0.7, # 可以根据需要调整参数
            # 'max_tokens': 2048,
        }
        
        logger.debug(f"Sending to DeepSeek API for conv {conversation_id} with model {api_model_name}: {json.dumps(payload, ensure_ascii=False)}")
        api_response = None 
        try:
            api_response = requests.post(
                settings.DEEPSEEK_API_URL if hasattr(settings, 'DEEPSEEK_API_URL') else "https://api.deepseek.com/v1/chat/completions", # 从settings读取URL
                headers=headers,
                json=payload,
                stream=True,
                timeout= (15, 180) # (connect_timeout, read_timeout for each chunk)
                                  # read_timeout 应该大于 Gunicorn worker timeout / N (N是预期块数)
                                  # 或者简单地设置一个足够大的值，让Gunicorn的超时先生效
            )
            api_response.raise_for_status() 
        except requests.exceptions.Timeout:
            logger.error(f"DeepSeek API request timed out for conv {conversation_id}")
            if api_response: api_response.close()
            def error_stream_timeout():
                yield f"data: {json.dumps({'error': 'API request timed out'})}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_timeout(), content_type="text/event-stream")
        except requests.exceptions.RequestException as e:
            logger.error(f"DeepSeek API request failed for conv {conversation_id}: {e}")
            if api_response: api_response.close()
            def error_stream_req_exc():
                yield f"data: {json.dumps({'error': f'API request error: {e}'})}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_req_exc(), content_type="text/event-stream")

        def event_stream_generator():
            full_ai_content = ""
            # is_new_conversation (来自外部作用域)
            # conversation_id (来自外部作用域)
            # model_choice (来自外部作用域)
            sent_conversation_id_in_stream = False 
            try: 
                logger.debug(f"Starting event_stream_generator for conv {conversation_id}")
                for line_bytes in api_response.iter_lines(): 
                    if not line_bytes:
                        continue 
                    
                    line = line_bytes.decode('utf-8').strip()
                    
                    if not line.startswith("data:"):
                        continue 
                    
                    raw_data = line.removeprefix("data:").strip()
                    
                    if raw_data == '[DONE]':
                        logger.info(f"DeepSeek stream [DONE] received for conv {conversation_id}. Full AI content length: {len(full_ai_content)}")
                        if full_ai_content: 
                            ChatMessage.objects.create(
                                user=request.user,
                                conversation_id=conversation_id,
                                model_type=model_choice, # 使用正确的模型类型
                                role='ai',
                                content=full_ai_content,
                                is_stream=True # 标记这是流式交互的AI回复
                            )
                        yield 'data: [DONE]\n\n'
                        break 
                    
                    try:
                        parsed_chunk = json.loads(raw_data)
                        # DeepSeek API 结构: choices -> 0 -> delta -> content
                        delta_content = parsed_chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                        
                        if delta_content:
                            full_ai_content += delta_content
                            data_to_send = {'content': delta_content}
                            if is_new_conversation and not sent_conversation_id_in_stream:
                                data_to_send['conversation_id'] = str(conversation_id)
                                sent_conversation_id_in_stream = True
                                logger.info(f"Sent new conversation_id {conversation_id} in stream for user {request.user.username}.")
                            yield f"data: {json.dumps(data_to_send)}\n\n"

                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in stream for conv {conversation_id}: {raw_data}")
                        yield f"data: {json.dumps({'error': 'Invalid JSON chunk in stream'})}\n\n" 
                        continue 
                    except Exception as e_inner: 
                        logger.error(f"Error processing DeepSeek stream chunk for conv {conversation_id}: {e_inner}", exc_info=True)
                        yield f"data: {json.dumps({'error': f'Error processing stream chunk: {e_inner}'})}\n\n"
                        break
            except requests.exceptions.ChunkedEncodingError as e_chunk:
                logger.error(f"ChunkedEncodingError during stream for conv {conversation_id}: {e_chunk}", exc_info=True)
                yield f"data: {json.dumps({'error': f'Stream chunk error: {e_chunk}'})}\n\n"
                yield 'data: [DONE]\n\n'
            except Exception as e_outer: 
                 logger.error(f"Error during event_stream_generator iteration for conv {conversation_id}: {e_outer}", exc_info=True)
                 yield f"data: {json.dumps({'error': f'Stream iteration error: {e_outer}'})}\n\n"
                 yield 'data: [DONE]\n\n' 
            finally:
                if api_response: 
                    api_response.close() 
                logger.debug(f"Finished event_stream_generator and closed API response for conv {conversation_id}")
        
        return StreamingHttpResponse(event_stream_generator(), content_type="text/event-stream")

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body for stream_chat", exc_info=True)
        def error_stream_json():
            yield f"data: {json.dumps({'error': '无效的请求数据'})}\n\n"
            yield 'data: [DONE]\n\n'
        return StreamingHttpResponse(error_stream_json(), content_type="text/event-stream")
    except Exception as e:
        logger.error(f"Unhandled error in stream_chat: {e}", exc_info=True)
        def error_stream_unhandled():
            yield f"data: {json.dumps({'error': f'服务器内部错误: {e}'})}\n\n"
            yield 'data: [DONE]\n\n'
        return StreamingHttpResponse(error_stream_unhandled(), content_type="text/event-stream")

@login_required
def get_conversations(request):
    """返回用户的对话列表，确保标题的获取是高效的"""
    # 获取用户所有不同的 conversation_id，并按每个对话的最新消息时间降序排列
    # 这需要更复杂的查询，或者在 ChatMessage 模型中增加一个 last_updated_at 字段来代表对话的最后活动时间
    # 简单版本：仍然按ID获取，然后可以在前端排序或后端基于第一条消息的时间排序（如果需要）
    
    # 获取所有不同的 conversation_id
    # 使用 .distinct('conversation_id') 配合 .order_by('conversation_id', '-timestamp') 
    # 来获取每个对话的最新时间戳，但这需要数据库支持 distinct on fields (如 PostgreSQL)
    # 更通用的方法是先获取 distinct ids，再为每个id获取标题和时间
    
    conversation_ids_qs = ChatMessage.objects.filter(user=request.user).values_list('conversation_id', flat=True).distinct()
    
    conversation_list = []
    for conv_id_uuid in conversation_ids_qs:
        # 获取每个对话的第一条用户消息作为标题（如果存在），否则用AI的第一条
        # 或者，可以考虑为对话单独建一个 Conversation 模型来存储标题和最后更新时间
        first_user_message = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid, role='user').order_by('timestamp').first()
        title_message = first_user_message
        
        if not title_message: # 如果没有用户消息，尝试找AI消息
            title_message = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid).order_by('timestamp').first()

        if title_message:
            title = title_message.content[:30] 
            if len(title_message.content) > 30:
                title += "..."
            
            # 获取该对话的最后一条消息的时间戳，用于排序
            last_msg_timestamp = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid).latest('timestamp').timestamp

            conversation_list.append({
                'id': str(conv_id_uuid),
                'title': title,
                'last_updated': last_msg_timestamp 
            })
            
    # 按最后更新时间降序排序
    conversation_list.sort(key=lambda x: x.get('last_updated'), reverse=True)
            
    return JsonResponse({'conversations': conversation_list}, encoder=DjangoJSONEncoder)


@login_required
def get_conversation_messages(request, conversation_id):
    """返回指定会话的所有消息"""
    if not conversation_id:
        return JsonResponse({'error': 'Conversation ID is required'}, status=400)
    
    try:
        conv_id_uuid = uuid.UUID(str(conversation_id)) 
        messages_qs = ChatMessage.objects.filter(
            user=request.user, 
            conversation_id=conv_id_uuid
        ).order_by('timestamp').values('role', 'content', 'timestamp')

        messages_list = [
            {
                'sender': 'ai' if msg['role'] == 'ai' else 'user',
                'content': msg['content'],
                'timestamp': msg['timestamp'].isoformat() 
            } for msg in messages_qs
        ]
        return JsonResponse({'messages': messages_list}, encoder=DjangoJSONEncoder) 
    except ValueError: 
        logger.warning(f"Invalid UUID format for conversation_id in get_conversation_messages: {conversation_id}")
        return JsonResponse({'error': 'Invalid Conversation ID format'}, status=400)
    except Exception as e:
        logger.error(f"Error fetching messages for conversation {conversation_id}: {e}", exc_info=True)
        return JsonResponse({'error': f'Error fetching messages: {e}'}, status=500)


@login_required
# @csrf_exempt # 考虑移除
def delete_conversation(request, conversation_id):
    """删除指定会话的所有消息"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)
    
    try:
        conv_id_uuid = uuid.UUID(str(conversation_id)) 
        count, _ = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid).delete()
        logger.info(f"Deleted {count} messages for conversation {conversation_id} for user {request.user.username}")
        return JsonResponse({'success': True})
    except ValueError:
        logger.warning(f"Invalid UUID format for deletion: {conversation_id}")
        return JsonResponse({'error': 'Invalid Conversation ID format for deletion'}, status=400)
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
