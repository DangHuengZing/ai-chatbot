from ai_api.models import ChatMessage
from django.contrib.auth.models import User

@csrf_exempt
def stream_chat(request):
    """处理流式聊天请求"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
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

        def event_stream():
            """流式读取 DeepSeek API 返回内容，并转发给前端"""
            try:
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
                            user = User.objects.get(username=request.user.username)  # 根据当前登录用户获取用户对象
                            ChatMessage.objects.create(
                                user=user,
                                model_type=model,
                                role='user',
                                content=question,
                                is_stream=True
                            )
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
