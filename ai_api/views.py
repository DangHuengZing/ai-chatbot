# ai_api/views.py

import json
import logging
import requests
import uuid
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
# from django.views.decorators.csrf import csrf_exempt # 考虑移除
from django.contrib.auth import authenticate, login, logout
from .models import ChatMessage
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Max

logger = logging.getLogger(__name__)

# --- login_user, logout_user, stream_chat_page 保持不变 ---
def login_user(request):
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
    if request.method == 'GET': 
        logout(request)
        return JsonResponse({'success': True}, status=200)
    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required
def stream_chat_page(request, conversation_id=None):
    return render(request, 'ai_api/stream_chat.html', {
        'username': request.user.username,
        'current_conversation_id': str(conversation_id) if conversation_id else ''
    })

# --- stream_chat 保持不变 (使用您确认流式效果有所改善的版本) ---
@login_required
# @csrf_exempt 
def stream_chat(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)
    try:
        body = json.loads(request.body)
        question = body.get('question', '')
        model_choice = body.get('model', 'v3') 
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
            model_type=model_choice, 
            role='user',
            content=question,
            is_stream=True 
        )

        if not hasattr(settings, 'DEEPSEEK_API_KEY') or not settings.DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API_KEY not configured.")
            def error_stream_key():
                yield f"data: {json.dumps({'error': 'API key not configured'})}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_key(), content_type="text/event-stream")

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
            'Accept': 'application/json'
        }
        payload = {
            'model': api_model_name,
            'messages': messages_for_api,
            'stream': True,
        }
        
        logger.debug(f"Sending to DeepSeek API for conv {conversation_id} with model {api_model_name}: {json.dumps(payload, ensure_ascii=False)}")
        api_response = None 
        try:
            api_response = requests.post(
                settings.DEEPSEEK_API_URL if hasattr(settings, 'DEEPSEEK_API_URL') else "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                stream=True,
                timeout= (15, 180) 
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
                                model_type=model_choice, 
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
    """返回用户的对话列表，强制确保ID唯一，并按最后活动时间排序"""
    logger.info(f"get_conversations called by user: {request.user.username}")

    # 步骤1: 获取所有相关的对话数据，包括conversation_id和每个对话的最后时间戳
    # values('conversation_id') 和 annotate(Max('timestamp')) 会为每个唯一的 conversation_id 生成一行
    raw_conversations_data = ChatMessage.objects.filter(
        user=request.user
    ).values(
        'conversation_id' 
    ).annotate(
        last_updated_ts=Max('timestamp') 
    ).order_by('-last_updated_ts') # 初步排序

    logger.debug(f"Raw distinct conversation data from DB (should be unique by conversation_id): {list(raw_conversations_data)}")

    # 步骤2: 为每个唯一的 conversation_id 构建对话信息，并使用字典确保最终输出的 ID 字符串是唯一的
    # (这一步主要是为了应对如果DB层或ORM的 distinct/annotate 行为在某些边缘情况下不符合预期)
    final_conversations_dict = {}

    for conv_data in raw_conversations_data:
        conv_id_uuid = conv_data['conversation_id'] # 这是UUID对象
        conv_id_str = str(conv_id_uuid) # 转换为字符串，用作字典的键

        # 如果这个字符串ID已经处理过，则跳过 (理论上不应该发生，因为上一步查询应该已去重)
        if conv_id_str in final_conversations_dict:
            logger.warning(f"Duplicate string conversation_id '{conv_id_str}' encountered after DB query in get_conversations. Skipping.")
            continue
            
        # 获取该对话的第一条消息作为标题
        # 优先用户的第一条消息，其次是AI的第一条
        first_user_message = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid, role='user').order_by('timestamp').first()
        title_message = first_user_message
        if not title_message:
            title_message = ChatMessage.objects.filter(user=request.user, conversation_id=conv_id_uuid).order_by('timestamp').first()

        if title_message:
            title = title_message.content[:30]
            if len(title_message.content) > 30:
                title += "..."
            
            final_conversations_dict[conv_id_str] = {
                'id': conv_id_str,
                'title': title,
                'last_updated': conv_data['last_updated_ts'].isoformat() if conv_data['last_updated_ts'] else None 
            }
        else:
            # 如果一个对话ID存在但没有任何消息 (例如，用户消息保存了，但AI回复前出错了且未保存)
            # 我们可以选择不显示它，或者给一个默认标题
            logger.warning(f"Conversation ID {conv_id_uuid} (str: {conv_id_str}) has no messages to derive a title. It will not be included in the list.")
            # 或者，如果你想包含它：
            # final_conversations_dict[conv_id_str] = {
            #     'id': conv_id_str,
            #     'title': '对话无内容',
            #     'last_updated': conv_data['last_updated_ts'].isoformat() if conv_data['last_updated_ts'] else None
            # }

    # 从字典的值创建列表，它已经是按 last_updated_ts 降序的（因为原始查询已排序）
    # 如果需要再次排序（例如，如果字典的迭代顺序不保证），可以取消下面这行注释
    # final_list = sorted(list(final_conversations_dict.values()), key=lambda x: x.get('last_updated'), reverse=True)
    final_list = list(final_conversations_dict.values())


    logger.info(f"get_conversations for user {request.user.username} processed. Returning {len(final_list)} unique conversations.")
    logger.debug(f"Final unique conversation list being sent: {final_list}")
    
    return JsonResponse({'conversations': final_list}, encoder=DjangoJSONEncoder)


# --- get_conversation_messages 和 delete_conversation 保持不变 ---
@login_required
def get_conversation_messages(request, conversation_id):
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
# @csrf_exempt
def delete_conversation(request, conversation_id):
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
