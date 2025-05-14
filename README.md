# DeepSeek Chatbot

## 项目介绍-第一次使用GitHub 有点乱
这是一个基于 DeepSeek API 的智能聊天机器人，用户可以与 AI 模型进行对话。项目基于 Django 框架，使用 `gunicorn` 和 `gevent` 作为生产环境的服务器，支持流式数据交互。

## 安装与配置

### 1. 克隆项目

```bash
git clone https://github.com/DangHuengZing/ai-chatbot.git
cd ai-chatbot



echo "🔍 实时查看 Gunicorn 日志：sudo journalctl -u gunicorn -e -f"
