import smtplib
import ssl
from email.message import EmailMessage
from app.core.config import get_settings


def send_reset_email(recipient: str, token: str):
    """Real SMTP adapter. No logs/bodies/credentials are emitted on errors."""
    settings = get_settings()
    link = settings.public_base_url.rstrip('/') + '/reset-password#token=' + token
    message = EmailMessage()
    message['Subject'] = '云果 · 重置登录密码'
    message['From'] = str(settings.smtp_from)
    message['To'] = recipient
    message.set_content(f'你正在申请重置云果账号密码。\n\n请在 {settings.password_reset_minutes} 分钟内打开此链接：\n{link}\n\n链接仅可使用一次。若非本人操作，请忽略此邮件，不要转发链接。')
    deliver_message(message)

def deliver_message(message: EmailMessage):
    settings = get_settings()
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if settings.smtp_security == 'ssl' else smtplib.SMTP
    kwargs = {'context': context} if settings.smtp_security == 'ssl' else {}
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=10, **kwargs) as connection:
        if settings.smtp_security == 'starttls':
            connection.starttls(context=context)
        if settings.smtp_username:
            connection.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        refused = connection.send_message(message)
        if refused:
            raise smtplib.SMTPException('Recipient rejected')


def send_verification_email(recipient: str, token: str):
    settings = get_settings()
    link = settings.public_base_url.rstrip('/') + '/verify-email#token=' + token
    message = EmailMessage()
    message['Subject'] = '云果 · 验证注册邮箱'
    message['From'] = str(settings.smtp_from)
    message['To'] = recipient
    message.set_content(f'请确认你拥有此云果账号的注册邮箱。\n\n请在 {settings.email_verification_minutes} 分钟内打开链接，并在页面确认验证：\n{link}\n\n链接仅可使用一次。此操作不会登录账号或修改密码。若非本人注册或申请，请忽略此邮件。')
    deliver_message(message)
