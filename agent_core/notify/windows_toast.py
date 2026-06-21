"""Windows Toast notifications via winotify or PowerShell fallback."""

import logging
import subprocess  # nosec B404 -- Windows toast notification only

logger = logging.getLogger(__name__)


def notify(title: str, message: str):
    try:
        from winotify import Notification
        Notification(app_id="求职Agent", title=title, msg=message).show()
    except ImportError:
        try:
            ps = f'''[Windows.UI.Notifications.ToastNotificationManager,
            Windows.UI.Notifications] > $null
            $t=[Windows.UI.Notifications.ToastNotificationManager]::
            GetTemplateContent(ToastTemplateType::ToastText02)
            $t.GetElementsByTagName("text")[0].AppendChild(
            $t.CreateTextNode("{title}")) > $null
            $t.GetElementsByTagName("text")[1].AppendChild(
            $t.CreateTextNode("{message}")) > $null
            [Windows.UI.Notifications.ToastNotificationManager]::
            CreateToastNotifier("求职Agent").
            Show([Windows.UI.Notifications.ToastNotification]::new($t))'''
            subprocess.run(["powershell", "-Command", ps], capture_output=True)  # nosec
        except Exception as e:
            logger.warning(f"Toast failed: {e}")


def notify_search_complete(count: int, skipped: int = 0):
    msg = f"找到 {count} 个新岗位" if count else "一切正常，本次无新岗位"
    if skipped:
        msg += f"（{skipped} 个因评估失败已跳过）"
    notify("搜索完成", msg)


def notify_captcha(platform: str):
    notify("需要验证", f"{platform} 需要验证码，请在浏览器中完成")


def notify_cookie_expired(platform: str):
    notify("Cookie 已过期", f"{platform} 登录态失效，请重新登录并导出 cookie")


def notify_anti_bot(platform: str):
    notify("触发反爬挑战", f"{platform} 触发反爬挑战，请稍后重试或重新导出 cookie")
