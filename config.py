# focusbox/config.py

from datetime import timedelta

# 你的时区字符串，只用于日志显示 / 解析
LOCAL_TZ = "America/Toronto"

# Google Calendar 相关
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GOOGLE_TOKEN_FILE = "token.json"
GOOGLE_CREDENTIALS_FILE = "credentials.json"  # 从 Google Cloud 下载

# 日历轮询间隔
CALENDAR_REFRESH_INTERVAL = timedelta(minutes=30)

# 事件匹配关键字（全大写匹配）
FOCUS_KEYWORD = "FOCUS"
SLEEP_KEYWORD = "SLEEP"

# 硬件相关（你后面可以改成真实的 GPIO 引脚）
LOCK_ENABLED = True
LOCK_ACTIVE_HIGH = True     # True：输出高电平上锁；False：低电平上锁

# 显示屏配置（后续接 OLED/e-ink 时用）
DISPLAY_ENABLED = True
