from pathlib import Path
import os # 用于环境变量

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-x!dai(_x0i426y=8f^8z9_g5s33%=0kvk&ux*+!ck#*e0$@(p*') # 从环境变量获取

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True' # 从环境变量获取，默认为True

ALLOWED_HOSTS = ['ai.dangdangdark.xyz', 
                 '34.126.104.17', 
                 'localhost', 
                 '127.0.0.1', 
                 '.googleusercontent.com']
# 如果 DEBUG 为 False，ALLOWED_HOSTS 不应包含 'localhost', '127.0.0.1' 等开发用地址
# if not DEBUG:
#     ALLOWED_HOSTS = ['ai.dangdangdark.xyz', '34.126.104.17', '.googleusercontent.com']


CSRF_TRUSTED_ORIGINS = ['https://ai.dangdangdark.xyz']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'ai_api', # 您的 ai_api 应用
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ai_site.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ai_site.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'ai_project'),
        'USER': os.environ.get('DB_USER', 'ai_project'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'DarkDang19831109'),
        'HOST': os.environ.get('DB_HOST', 'localhost'), 
        'PORT': os.environ.get('DB_PORT', '5432'), 
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
# STATIC_ROOT = BASE_DIR / 'staticfiles_collected' # 用于 collectstatic

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-8d62e2d709e445ae979ed1b20450b5a3')
DEEPSEEK_API_URL = os.environ.get('DEEPSEEK_API_URL', "https://api.deepseek.com/v1/chat/completions")


LOGIN_REDIRECT_URL = '/stream_chat/'
LOGIN_URL = '/login/'


# LOGGING 配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False, # 保留 Django 默认 logger
    'formatters': { # 定义日志格式
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': { # 输出到 stderr，Gunicorn 的 --error-logfile 会捕获它
            'class': 'logging.StreamHandler',
            'formatter': 'verbose', # 使用详细格式
        },
        # 您也可以配置一个 FileHandler 来直接写入Django日志到特定文件
        # 'file_django': {
        #     'level': 'INFO',
        #     'class': 'logging.FileHandler',
        #     'filename': BASE_DIR / 'logs/django.log',
        #     'formatter': 'verbose',
        # },
        # 'file_ai_api': {
        #     'level': 'DEBUG',
        #     'class': 'logging.FileHandler',
        #     'filename': BASE_DIR / 'logs/ai_api.log',
        #     'formatter': 'verbose',
        # },
    },
    'root': { # 根 logger，捕获所有未被特定 logger 处理的日志
        'handlers': ['console'], # 默认发送到 console
        'level': 'WARNING', # 根 logger 的级别，可以设为 INFO 或 DEBUG
    },
    'loggers': {
        'django': { # Django 自身的 logger
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'), # Django 日志级别
            'propagate': False, # 不要传递给 root logger
        },
        'django.request': { # Django 请求相关的错误 (4XX, 5XX)
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'ai_api': { # 您的应用的 logger
            'handlers': ['console'],
            'level': 'DEBUG', # 确保能看到 ai_api 中的 logger.debug 和 logger.info
            'propagate': True, # 可以让 root logger 也处理 (如果 root 的级别允许)
        },
        # 如果有其他应用的日志也想看，可以在这里添加
    },
}
# 确保日志目录存在 (如果使用 FileHandler)
# LOGS_DIR = BASE_DIR / 'logs'
# if not LOGS_DIR.exists():
#     LOGS_DIR.mkdir(parents=True, exist_ok=True)

