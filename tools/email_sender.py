"""
Инструмент для отправки email через SMTP.
Поддерживает отправку простых текстовых сообщений и HTML.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import os

logger = logging.getLogger(__name__)


class EmailSender:
    """Класс для отправки email через SMTP."""
    
    def __init__(self, 
                 smtp_server: str = None,
                 smtp_port: int = None,
                 username: str = None,
                 password: str = None,
                 use_tls: bool = True):
        """
        Инициализирует отправитель email.
        
        Args:
            smtp_server: SMTP сервер (по умолчанию из переменных окружения)
            smtp_port: Порт SMTP (по умолчанию из переменных окружения)
            username: Имя пользователя (по умолчанию из переменных окружения)
            password: Пароль (по умолчанию из переменных окружения)
            use_tls: Использовать TLS (по умолчанию True)
        """
        # Получаем настройки из переменных окружения, если не указаны
        self.smtp_server = smtp_server or os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.username = username or os.getenv("SMTP_USERNAME")
        self.password = password or os.getenv("SMTP_PASSWORD")
        self.use_tls = use_tls
        
        logger.info(f"EmailSender инициализирован: {self.smtp_server}:{self.smtp_port}")
    
    def send_email(self,
                   to_email: str,
                   subject: str,
                   body: str,
                   from_email: str = None,
                   cc: List[str] = None,
                   bcc: List[str] = None,
                   is_html: bool = False) -> Dict[str, Any]:
        """
        Отправляет email.
        
        Args:
            to_email: Email получателя
            subject: Тема письма
            body: Текст письма
            from_email: Email отправителя (по умолчанию username)
            cc: Список email для копии
            bcc: Список email для скрытой копии
            is_html: True если тело письма в формате HTML
            
        Returns:
            Словарь с результатом отправки
        """
        try:
            # Проверяем обязательные параметры
            if not self.username or not self.password:
                return {
                    "success": False,
                    "error": "Не указаны учетные данные SMTP (SMTP_USERNAME, SMTP_PASSWORD)"
                }
            
            if not to_email:
                return {
                    "success": False,
                    "error": "Не указан получатель (to_email)"
                }
            
            # Создаем сообщение
            from_email = from_email or self.username
            msg = MIMEMultipart('alternative')
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Добавляем CC и BCC
            if cc:
                msg['Cc'] = ', '.join(cc)
            
            # Формируем список всех получателей
            all_recipients = [to_email]
            if cc:
                all_recipients.extend(cc)
            if bcc:
                all_recipients.extend(bcc)
            
            # Добавляем тело письма
            if is_html:
                msg.attach(MIMEText(body, 'html', 'utf-8'))
            else:
                msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # Подключаемся к SMTP серверу и отправляем
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                
                server.login(self.username, self.password)
                server.sendmail(from_email, all_recipients, msg.as_string())
            
            logger.info(f"Email успешно отправлен: {subject} -> {to_email}")
            
            return {
                "success": True,
                "message": f"Email успешно отправлен на {to_email}",
                "subject": subject,
                "to": to_email,
                "from": from_email
            }
            
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"Ошибка аутентификации SMTP: {e}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "details": "Проверьте логин и пароль SMTP"
            }
        except smtplib.SMTPException as e:
            error_msg = f"Ошибка SMTP: {e}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "details": "Проверьте настройки SMTP сервера"
            }
        except Exception as e:
            error_msg = f"Ошибка отправки email: {e}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }
    
    def send_bulk_emails(self,
                         emails: List[Dict[str, str]],
                         from_email: str = None,
                         batch_size: int = 10) -> Dict[str, Any]:
        """
        Отправляет несколько email пакетно.
        
        Args:
            emails: Список словарей с ключами: to_email, subject, body, is_html
            from_email: Email отправителя
            batch_size: Размер пакета для отправки
            
        Returns:
            Словарь с результатами отправки
        """
        results = {
            "success": True,
            "total": len(emails),
            "sent": 0,
            "failed": 0,
            "details": []
        }
        
        for i, email_data in enumerate(emails):
            try:
                result = self.send_email(
                    to_email=email_data.get('to_email'),
                    subject=email_data.get('subject', 'Без темы'),
                    body=email_data.get('body', ''),
                    from_email=from_email,
                    is_html=email_data.get('is_html', False)
                )
                
                if result.get('success'):
                    results['sent'] += 1
                else:
                    results['failed'] += 1
                    results['success'] = False
                
                results['details'].append({
                    'index': i,
                    'to': email_data.get('to_email'),
                    'success': result.get('success'),
                    'error': result.get('error')
                })
                
                # Пауза между пакетами для избежания блокировки
                if (i + 1) % batch_size == 0:
                    logger.info(f"Отправлено {i + 1} из {len(emails)} email")
                    
            except Exception as e:
                results['failed'] += 1
                results['success'] = False
                results['details'].append({
                    'index': i,
                    'to': email_data.get('to_email'),
                    'success': False,
                    'error': str(e)
                })
        
        logger.info(f"Пакетная отправка завершена: {results['sent']} успешно, {results['failed']} с ошибками")
        return results
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Тестирует подключение к SMTP серверу.
        
        Returns:
            Словарь с результатом теста
        """
        try:
            if not self.username or not self.password:
                return {
                    "success": False,
                    "error": "Не указаны учетные данные SMTP"
                }
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                
                server.login(self.username, self.password)
                # Просто проверяем подключение, не отправляем письмо
                server.noop()
            
            return {
                "success": True,
                "message": f"Подключение к SMTP серверу {self.smtp_server}:{self.smtp_port} успешно",
                "server": self.smtp_server,
                "port": self.smtp_port,
                "username": self.username
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка подключения к SMTP: {e}",
                "server": self.smtp_server,
                "port": self.smtp_port,
                "username": self.username
            }


# Функция для отправки email (удобный интерфейс)
def send_email(to_email: str, 
               subject: str, 
               body: str, 
               from_email: str = None,
               smtp_server: str = None,
               smtp_port: int = None,
               username: str = None,
               password: str = None,
               is_html: bool = False) -> Dict[str, Any]:
    """
    Удобная функция для отправки email.
    
    Args:
        to_email: Email получателя
        subject: Тема письма
        body: Текст письма
        from_email: Email отправителя
        smtp_server: SMTP сервер
        smtp_port: Порт SMTP
        username: Имя пользователя SMTP
        password: Пароль SMTP
        is_html: True если тело письма в формате HTML
        
    Returns:
        Словарь с результатом отправки
    """
    sender = EmailSender(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        username=username,
        password=password
    )
    
    return sender.send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        from_email=from_email,
        is_html=is_html
    )


# Глобальный экземпляр для использования в других модулях
email_sender = EmailSender()


# Функции для использования в качестве инструментов
def send_email_tool(to_email: str, subject: str, body: str, is_html: bool = False) -> Dict[str, Any]:
    """
    Инструмент для отправки email.
    
    Args:
        to_email: Email получателя
        subject: Тема письма
        body: Текст письма
        is_html: True если тело письма в формате HTML
        
    Returns:
        Словарь с результатом отправки
    """
    return email_sender.send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        is_html=is_html
    )


def send_notification_tool(to_email: str, title: str, message: str, notification_type: str = "info") -> Dict[str, Any]:
    """
    Инструмент для отправки HTML уведомления по email.
    
    Args:
        to_email: Email получателя
        title: Заголовок уведомления
        message: Текст сообщения
        notification_type: Тип уведомления (info, success, warning, error)
        
    Returns:
        Словарь с результатом отправки
    """
    # Создаем HTML шаблон уведомления
    colors = {
        "info": "#3498db",
        "success": "#2ecc71",
        "warning": "#f39c12",
        "error": "#e74c3c"
    }
    
    color = colors.get(notification_type, "#3498db")
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .notification {{ 
                border-left: 4px solid {color};
                background-color: #f8f9fa;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .title {{ 
                color: {color};
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 10px;
            }}
            .message {{ 
                color: #555;
                font-size: 14px;
            }}
            .footer {{ 
                margin-top: 20px;
                font-size: 12px;
                color: #777;
                border-top: 1px solid #eee;
                padding-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="notification">
            <div class="title">{title}</div>
            <div class="message">{message}</div>
            <div class="footer">
                Это автоматическое уведомление от системы ZORA.<br>
                Дата: {__import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M")}
            </div>
        </div>
    </body>
    </html>
    """
    
    return email_sender.send_email(
        to_email=to_email,
        subject=f"ZORA: {title}",
        body=html_body,
        is_html=True
    )
