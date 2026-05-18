# tools/__init__.py
from .weather import get_weather
from .file_ops import read_file, write_file, list_directory
from .shell import run_command
from .email_sender import send_email_tool, send_notification_tool

# Browser tools загружаются лениво, чтобы не требовать zendriver при импорте
_browser_tools = None

def _get_browser_tools():
    global _browser_tools
    if _browser_tools is None:
        try:
            from .browser import (
                get_page_text, get_page_html, click_element,
                fill_input, perform_actions, close_browser,
                get_current_url, take_screenshot
            )
            _browser_tools = {
                "get_page_text": get_page_text,
                "get_page_html": get_page_html,
                "click_element": click_element,
                "fill_input": fill_input,
                "perform_actions": perform_actions,
                "get_current_url": get_current_url,
                "take_screenshot": take_screenshot,
                "close_browser": close_browser,
            }
        except ImportError:
            _browser_tools = {}
    return _browser_tools

TOOLS = {
    "get_weather": {
        "function": get_weather,
        "description": "Получить погоду для города. Возвращает детальные данные для логистики."
    },
    "read_file": {
        "function": read_file,
        "description": "Чтение содержимого файла по указанному пути."
    },
    "write_file": {
        "function": write_file,
        "description": "Запись содержимого в файл. Создаёт директории при необходимости."
    },
    "list_directory": {
        "function": list_directory,
        "description": "Получение списка файлов и папок в указанной директории."
    },
    "run_command": {
        "function": run_command,
        "description": "Выполнение shell команды в системе. Используй для запуска скриптов, установки пакетов, проверки статуса."
    },
    "send_email": {
        "function": send_email_tool,
        "description": "Отправить email. Требует настройки SMTP в .env файле. Параметры: to_email, subject, body, is_html (опционально)."
    },
    "send_notification": {
        "function": send_notification_tool,
        "description": "Отправить HTML уведомление по email с красивым оформлением. Параметры: to_email, title, message, notification_type (info, success, warning, error)."
    }
}

# Browser tools добавляются лениво при первом обращении
def get_tools():
    """Возвращает полный список инструментов, загружая browser tools при необходимости."""
    tools = dict(TOOLS)
    browser = _get_browser_tools()
    for name, func in browser.items():
        tools[name] = {
            "function": func,
            "description": f"Browser tool: {name}"
        }
    return tools
