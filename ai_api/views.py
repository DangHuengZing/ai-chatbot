# ai_api/views.py

import json
import logging
import requests
import uuid
# import time # 注意：此版本未引入 time 模块，以下日志不使用时间戳函数
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
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

@login_required
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

        api_model_name = "deepseek-chat" if model_choice == "v3" else "deepseek-reasoner"
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
            logger.error(f"DeepSeek API request failed for conv {conversation_id}: {str(e)}", exc_info=True) # 使用 str(e)
            if api_response: api_response.close()
            def error_stream_req_exc():
                yield f"data: {json.dumps({'error': f'API request error: {str(e)}'})}\n\n" # 使用 str(e)
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_req_exc(), content_type="text/event-stream")

        def event_stream_generator():
            full_ai_content = ""
            sent_conversation_id_in_stream = False
            first_chunk_logged = False # 新增：用于标记第一个数据块是否已记录日志
            try:
                logger.info(f"Conv {conversation_id}: event_stream_generator started.") # 修改：更明确的开始日志
                for line_bytes in api_response.iter_lines():
                    if not first_chunk_logged: # 新增：记录第一个数据块到达
                        logger.info(f"Conv {conversation_id}: First chunk received from DeepSeek.")
                        first_chunk_logged = True

                    if not line_bytes:
                        continue

                    line = line_bytes.decode('utf-8').strip()

                    if not line.startswith("data:"):
                        continue

                    raw_data = line.removeprefix("data:").strip()

                    if raw_data == '[DONE]':
                        logger.info(f"Conv {conversation_id}: DeepSeek stream [DONE] received. Full AI content length: {len(full_ai_content)}")
                        if full_ai_content:
                            ChatMessage.objects.create(
                                user=request.user,
                                conversation_id=conversation_id,
                                model_type=model_choice,
                                role='ai',
                                content=full_ai_content,
                                is_stream=True
                            )
                        logger.info(f"Conv {conversation_id}: Yielding [DONE] to client.") # 修改：更明确的结束日志
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
                        logger.error(f"Error processing DeepSeek stream chunk for conv {conversation_id}: {str(e_inner)}", exc_info=True) # 使用 str(e_inner)
                        yield f"data: {json.dumps({'error': f'Error processing stream chunk: {str(e_inner)}'})}\n\n" # 使用 str(e_inner)
                        break
            except requests.exceptions.ChunkedEncodingError as e_chunk:
                logger.error(f"ChunkedEncodingError during stream for conv {conversation_id}: {str(e_chunk)}", exc_info=True) # 使用 str(e_chunk)
                yield f"data: {json.dumps({'error': f'Stream chunk error: {str(e_chunk)}'})}\n\n" # 使用 str(e_chunk)
                yield 'data: [DONE]\n\n'
            except Exception as e_outer:
                logger.error(f"Error during event_stream_generator iteration for conv {conversation_id}: {str(e_outer)}", exc_info=True) # 使用 str(e_outer)
                yield f"data: {json.dumps({'error': f'Stream iteration error: {str(e_outer)}'})}\n\n" # 使用 str(e_outer)
                yield 'data: [DONE]\n\n'
            finally:
                if api_response:
                    api_response.close()
                logger.info(f"Conv {conversation_id}: event_stream_generator finished.") # 修改：更明确的结束日志

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
            yield f"data: {json.dumps({'error': f'服务器内部错误: {str(e)}'})}\n\n" # 使用 str(e)
            yield 'data: [DONE]\n\n'
        return StreamingHttpResponse(error_stream_unhandled(), content_type="text/event-stream")

@login_required
def get_conversations(request):
    logger.info(f"get_conversations called by user: {request.user.username}")
    raw_conversations_data = ChatMessage.objects.filter(
        user=request.user
    ).values(
        'conversation_id'
    ).annotate(
        last_updated_ts=Max('timestamp')
    ).order_by('-last_updated_ts')

    logger.debug(f"Raw distinct conversation data from DB (should be unique by conversation_id): {list(raw_conversations_data)}")
    final_conversations_dict = {}
    for conv_data in raw_conversations_data:
        conv_id_uuid = conv_data['conversation_id']
        conv_id_str = str(conv_id_uuid)
        if conv_id_str in final_conversations_dict:
            logger.warning(f"Duplicate string conversation_id '{conv_id_str}' encountered after DB query in get_conversations. Skipping.")
            continue

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
            logger.warning(f"Conversation ID {conv_id_uuid} (str: {conv_id_str}) has no messages to derive a title. It will not be included in the list.")
    final_list = list(final_conversations_dict.values())

    logger.info(f"get_conversations for user {request.user.username} processed. Returning {len(final_list)} unique conversations.")
    logger.debug(f"Final unique conversation list being sent: {final_list}")

    return JsonResponse({'conversations': final_list}, encoder=DjangoJSONEncoder)

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
        return JsonResponse({'error': f'Error fetching messages: {str(e)}'}, status=500) # 使用 str(e)

@login_required
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
