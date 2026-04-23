"""
Модуль для автоматизации рабочего стола Windows.
Предоставляет функции для работы с окнами, скриншотами и UI-элементами.
"""

import pyautogui
import pygetwindow as gw
import uiautomation as auto
from mss import mss
from PIL import Image
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Настройка безопасности pyautogui
pyautogui.FAILSAFE = True  # Переместить мышь в верхний левый угол для остановки
pyautogui.PAUSE = 0.1      # Пауза между действиями

def get_screenshot(region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
    """
    Возвращает скриншот всего экрана или области.
    
    Args:
        region: (left, top, width, height) - область для скриншота
    
    Returns:
        PIL.Image.Image: изображение скриншота
    """
    try:
        with mss() as sct:
            if region:
                monitor = {"top": region[1], "left": region[0], "width": region[2], "height": region[3]}
            else:
                monitor = sct.monitors[1]  # Основной монитор
            
            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
    except Exception as e:
        logger.error(f"Ошибка при создании скриншота: {e}")
        # Fallback на pyautogui
        try:
            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()
            return screenshot
        except Exception as e2:
            logger.error(f"Ошибка при создании скриншота через pyautogui: {e2}")
            raise

def find_window_by_title(title_substring: str) -> Optional[gw.Window]:
    """
    Находит первое окно, содержащее подстроку в заголовке, и активирует его.
    
    Args:
        title_substring: подстрока для поиска в заголовке окна
    
    Returns:
        pygetwindow.Window: найденное окно или None
    """
    try:
        windows = gw.getWindowsWithTitle(title_substring)
        if windows:
            win = windows[0]
            win.activate()
            logger.info(f"Найдено и активировано окно: {win.title}")
            return win
        logger.warning(f"Окно с подстрокой '{title_substring}' не найдено")
        return None
    except Exception as e:
        logger.error(f"Ошибка при поиске окна '{title_substring}': {e}")
        return None

def click_at_coords(x: int, y: int) -> str:
    """
    Клик по указанным координатам.
    
    Args:
        x: координата X
        y: координата Y
    
    Returns:
        str: сообщение о результате
    """
    try:
        pyautogui.click(x, y)
        logger.info(f"Клик выполнен по координатам ({x}, {y})")
        return f"Клик выполнен по координатам ({x}, {y})"
    except Exception as e:
        logger.error(f"Ошибка при клике по координатам ({x}, {y}): {e}")
        return f"Ошибка при клике: {e}"

def type_text(text: str) -> str:
    """
    Ввод текста с клавиатуры.
    
    Args:
        text: текст для ввода
    
    Returns:
        str: сообщение о результате
    """
    try:
        pyautogui.typewrite(text)
        logger.info(f"Текст введён: '{text}'")
        return f"Текст введён: '{text}'"
    except Exception as e:
        logger.error(f"Ошибка при вводе текста '{text}': {e}")
        return f"Ошибка при вводе текста: {e}"

def click_on_text(text: str) -> bool:
    """
    Ищет элемент с заданным текстом через UI Automation и кликает по нему.
    
    Args:
        text: текст для поиска
    
    Returns:
        bool: True если элемент найден и клик выполнен
    """
    try:
        control = auto.FindControl(auto.Condition.CreateNameCondition(text))
        if control:
            rect = control.BoundingRectangle
            center_x = rect.left + (rect.right - rect.left) // 2
            center_y = rect.top + (rect.bottom - rect.top) // 2
            pyautogui.click(center_x, center_y)
            logger.info(f"Клик выполнен по элементу с текстом: '{text}'")
            return True
        logger.warning(f"Элемент с текстом '{text}' не найден")
        return False
    except Exception as e:
        logger.error(f"Ошибка при поиске элемента с текстом '{text}': {e}")
        return False

def get_window_list() -> list:
    """
    Возвращает список всех открытых окон.
    
    Returns:
        list: список словарей с информацией об окнах
    """
    try:
        windows = gw.getAllWindows()
        window_list = []
        for win in windows:
            if win.title.strip():  # Пропускаем окна без заголовка
                window_list.append({
                    "title": win.title,
                    "left": win.left,
                    "top": win.top,
                    "width": win.width,
                    "height": win.height,
                    "is_active": win.isActive
                })
        logger.info(f"Найдено {len(window_list)} окон")
        return window_list
    except Exception as e:
        logger.error(f"Ошибка при получении списка окон: {e}")
        return []

def move_window(title_substring: str, x: int, y: int) -> str:
    """
    Перемещает окно в указанные координаты.
    
    Args:
        title_substring: подстрока для поиска окна
        x: новая координата X левого верхнего угла
        y: новая координата Y левого верхнего угла
    
    Returns:
        str: сообщение о результате
    """
    try:
        windows = gw.getWindowsWithTitle(title_substring)
        if windows:
            win = windows[0]
            win.moveTo(x, y)
            logger.info(f"Окно '{win.title}' перемещено в ({x}, {y})")
            return f"Окно перемещено в ({x}, {y})"
        return f"Окно с подстрокой '{title_substring}' не найдено"
    except Exception as e:
        logger.error(f"Ошибка при перемещении окна '{title_substring}': {e}")
        return f"Ошибка при перемещении окна: {e}"

def resize_window(title_substring: str, width: int, height: int) -> str:
    """
    Изменяет размер окна.
    
    Args:
        title_substring: подстрока для поиска окна
        width: новая ширина
        height: новая высота
    
    Returns:
        str: сообщение о результате
    """
    try:
        windows = gw.getWindowsWithTitle(title_substring)
        if windows:
            win = windows[0]
            win.resizeTo(width, height)
            logger.info(f"Окно '{win.title}' изменено до {width}x{height}")
            return f"Размер окна изменён до {width}x{height}"
        return f"Окно с подстрокой '{title_substring}' не найдено"
    except Exception as e:
        logger.error(f"Ошибка при изменении размера окна '{title_substring}': {e}")
        return f"Ошибка при изменении размера окна: {e}"

def get_mouse_position() -> dict:
    """
    Возвращает текущую позицию мыши.
    
    Returns:
        dict: словарь с координатами X и Y
    """
    try:
        x, y = pyautogui.position()
        return {"x": x, "y": y}
    except Exception as e:
        logger.error(f"Ошибка при получении позиции мыши: {e}")
        return {"x": 0, "y": 0}

def press_key(key: str) -> str:
    """
    Нажимает клавишу или комбинацию клавиш.
    
    Args:
        key: клавиша или комбинация (например, 'enter', 'ctrl+c')
    
    Returns:
        str: сообщение о результате
    """
    try:
        pyautogui.press(key)
        logger.info(f"Нажата клавиша: '{key}'")
        return f"Нажата клавиша: '{key}'"
    except Exception as e:
        logger.error(f"Ошибка при нажатии клавиши '{key}': {e}")
        return f"Ошибка при нажатии клавиши: {e}"

def hotkey(*keys) -> str:
    """
    Нажимает комбинацию клавиш.
    
    Args:
        *keys: последовательность клавиш (например, 'ctrl', 'c')
    
    Returns:
        str: сообщение о результате
    """
    try:
        pyautogui.hotkey(*keys)
        keys_str = '+'.join(keys)
        logger.info(f"Нажата комбинация клавиш: {keys_str}")
        return f"Нажата комбинация клавиш: {keys_str}"
    except Exception as e:
        logger.error(f"Ошибка при нажатии комбинации клавиш {keys}: {e}")
        return f"Ошибка при нажатии комбинации клавиш: {e}"

def scroll(amount: int) -> str:
    """
    Прокручивает колесо мыши.
    
    Args:
        amount: количество прокруток (положительное - вверх, отрицательное - вниз)
    
    Returns:
        str: сообщение о результате
    """
    try:
        pyautogui.scroll(amount)
        direction = "вверх" if amount > 0 else "вниз"
        logger.info(f"Прокрутка {direction} на {abs(amount)} единиц")
        return f"Прокрутка {direction} на {abs(amount)} единиц"
    except Exception as e:
        logger.error(f"Ошибка при прокрутке на {amount}: {e}")
        return f"Ошибка при прокрутке: {e}"