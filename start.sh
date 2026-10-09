#!/bin/sh
# yt-dlp مدام آپدیت می‌شود چون سایت‌ها تغییر می‌کنند؛ هر بار استارت آخرین نسخه نصب می‌شود
if [ "${AUTO_UPDATE_YTDLP:-1}" = "1" ]; then
  timeout 120 pip install --no-cache-dir -U "yt-dlp[default]" >/dev/null 2>&1 || echo "yt-dlp update skipped"
fi
exec python -m bot.main
