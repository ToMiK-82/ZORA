# tools/__init__.py
from .weather import get_weather
from .file_ops import read_file, write_file, list_directory
from .shell import run_command
from .browser import (
    get_page_text, 
    get_page_html, 
    click_element, 
    fill_input, 
    perform_actions, 
    close_browser,
    get_current_url,
    take_screenshot
)
from .email_sender import send_email_tool, send_notification_tool

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
    "get_page_text": {
        "function": get_page_text,
        "description": "Открыть URL и вернуть текстовое содержимое страницы."
    },
    "get_page_html": {
        "function": get_page_html,
        "description": "Открыть URL и вернуть HTML-код страницы."
    },
    "click_element": {
        "function": click_element,
        "description": "Кликнуть по элементу (CSS-селектор или текст)."
    },
    "fill_input": {
        "function": fill_input,
        "description": "Заполнить поле ввода по CSS-селектору."
    },
    "perform_actions": {
        "function": perform_actions,
        "description": "Выполнить последовательность действий (open, click, fill, wait) в формате JSON."
    },
    "get_current_url": {
        "function": get_current_url,
        "description": "Получить URL текущей страницы."
    },
    "take_screenshot": {
        "function": take_screenshot,
        "description": "Сделать скриншот текущей страницы."
    },
    "close_browser": {
        "function": close_browser,
        "description": "Закрыть браузер (освободить ресурсы)."
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
