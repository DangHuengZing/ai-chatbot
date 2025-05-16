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

        # 当 model_choice 为 "r1" 时，api_model_name 为 "deepseek-reasoner"
        # 当 model_choice 为 "v3" 时，api_model_name 为 "deepseek-chat"
        api_model_name = "deepseek-chat" if model_choice == "v3" else "deepseek-reasoner"
        logger.info(f"User {request.user.username} selected model_choice: '{model_choice}', mapped to api_model_name: '{api_model_name}' for conv {conversation_id}")


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
            # 在调用 raise_for_status() 之前，检查是否有错误并记录详细信息
            if api_response.status_code >= 400:
                error_text_from_api = api_response.text # 获取原始错误文本
                logger.error(
                    f"DeepSeek API returned an error for conv {conversation_id}. "
                    f"Model: {api_model_name}, Status: {api_response.status_code}, Response: {error_text_from_api}"
                )
            api_response.raise_for_status() # 如果状态码是 4xx 或 5xx，则会引发 HTTPError

        except requests.exceptions.Timeout:
            logger.error(f"DeepSeek API request timed out for conv {conversation_id}, model {api_model_name}")
            if api_response: api_response.close()
            def error_stream_timeout():
                yield f"data: {json.dumps({'error': 'API request timed out'})}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_timeout(), content_type="text/event-stream")

        except requests.exceptions.HTTPError as http_err: # 更具体地捕获 HTTPError
            # logger.error 调用已在上面 if api_response.status_code >= 400 块中记录了详细的 api_response.text
            logger.error(f"DeepSeek API HTTPError for conv {conversation_id}, model {api_model_name}: {str(http_err)}", exc_info=True)
            if api_response: api_response.close()
            def error_stream_http_err():
                # 向客户端发送一个更通用的错误，依赖服务器日志获取详细信息
                status_code = api_response.status_code if api_response else "Unknown"
                error_payload = {'error': f'API request failed with status {status_code}. Check server logs for details.'}
                yield f"data: {json.dumps(error_payload)}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_http_err(), content_type="text/event-stream")

        except requests.exceptions.RequestException as e: # 捕获其他请求相关的异常 (例如网络问题)
            logger.error(f"DeepSeek API RequestException for conv {conversation_id}, model {api_model_name}: {str(e)}", exc_info=True)
            if api_response: api_response.close()
            def error_stream_req_exc():
                error_payload = {'error': f'API connection error. Check server logs for details: {str(e)}'}
                yield f"data: {json.dumps(error_payload)}\n\n"
                yield 'data: [DONE]\n\n'
            return StreamingHttpResponse(error_stream_req_exc(), content_type="text/event-stream")

        def event_stream_generator():
            full_ai_content = ""
            sent_conversation_id_in_stream = False
            first_chunk_logged = False
            try:
                logger.info(f"Conv {conversation_id}, Model {api_model_name}: event_stream_generator started.")
                for line_bytes in api_response.iter_lines():
                    if not first_chunk_logged:
                        logger.info(f"Conv {conversation_id}, Model {api_model_name}: First chunk received from DeepSeek.")
                        first_chunk_logged = True

                    if not line_bytes:
                        continue

                    line = line_bytes.decode('utf-8').strip()

                    if not line.startswith("data:"):
                        continue

                    raw_data = line.removeprefix("data:").strip()

                    if raw_data == '[DONE]':
                        logger.info(f"Conv {conversation_id}, Model {api_model_name}: DeepSeek stream [DONE] received. Full AI content length: {len(full_ai_content)}")
                        if full_ai_content:
                            ChatMessage.objects.create(
                                user=request.user,
                                conversation_id=conversation_id,
                                model_type=model_choice, # 使用原始的 model_choice
                                role='ai',
                                content=full_ai_content,
                                is_stream=True
                            )
                        logger.info(f"Conv {conversation_id}, Model {api_model_name}: Yielding [DONE] to client.")
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
                        logger.warning(f"Invalid JSON in stream for conv {conversation_id}, Model {api_model_name}: {raw_data}")
                        # 即使JSON解析失败，也继续尝试处理流中的下一行，但向客户端发送一个错误块
                        yield f"data: {json.dumps({'error': 'Invalid JSON chunk in stream', 'details': raw_data})}\n\n"
                        continue
                    except Exception as e_inner:
                        logger.error(f"Error processing DeepSeek stream chunk for conv {conversation_id}, Model {api_model_name}: {str(e_inner)}", exc_info=True)
                        yield f"data: {json.dumps({'error': f'Error processing stream chunk: {str(e_inner)}'})}\n\n"
                        # 发生内部处理错误时，最好也发送[DONE]并中断
                        yield 'data: [DONE]\n\n'
                        break
            except requests.exceptions.ChunkedEncodingError as e_chunk: # 在迭代 api_response.iter_lines() 时可能发生
                logger.error(f"ChunkedEncodingError during stream for conv {conversation_id}, Model {api_model_name}: {str(e_chunk)}", exc_info=True)
                yield f"data: {json.dumps({'error': f'Stream chunk error: {str(e_chunk)}'})}\n\n"
                yield 'data: [DONE]\n\n'
            except Exception as e_outer: # 捕获生成器中的其他意外错误
                logger.error(f"Error during event_stream_generator iteration for conv {conversation_id}, Model {api_model_name}: {str(e_outer)}", exc_info=True)
                yield f"data: {json.dumps({'error': f'Stream iteration error: {str(e_outer)}'})}\n\n"
                yield 'data: [DONE]\n\n'
            finally:
                if api_response:
                    api_response.close()
                logger.info(f"Conv {conversation_id}, Model {api_model_name}: event_stream_generator finished.")

        return StreamingHttpResponse(event_stream_generator(), content_type="text/event-stream")

    except json.JSONDecodeError: # 请求体JSON解析错误
        logger.error("Invalid JSON in request body for stream_chat", exc_info=True)
        def error_stream_json_body():
            yield f"data: {json.dumps({'error': '无效的请求数据 (Invalid request body JSON)'})}\n\n"
            yield 'data: [DONE]\n\n'
        return StreamingHttpResponse(error_stream_json_body(), content_type="text/event-stream")
    except Exception as e: # stream_chat 函数级别的其他未捕获错误
        logger.error(f"Unhandled error in stream_chat view for conv {conversation_id if 'conversation_id' in locals() else 'Unknown'}: {str(e)}", exc_info=True)
        def error_stream_unhandled_view():
            error_msg = f'服务器内部错误，请检查日志 (Unhandled server error. Conversation ID: {str(conversation_id) if "conversation_id" in locals() else "N/A"})'
            yield f"data: {json.dumps({'error': error_msg})}\n\n"
            yield 'data: [DONE]\n\n'
        return StreamingHttpResponse(error_stream_unhandled_view(), content_type="text/event-stream")

# --- get_conversations, get_conversation_messages, delete_conversation 保持不变 ---
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
        return JsonResponse({'error': f'Error fetching messages: {str(e)}'}, status=500)

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
