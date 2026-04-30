"""
ITS Scout v3 — сборщик карты сайта its.1c.ru
Читает логин/пароль из .env, авторизуется через login.1c.ru
"""
import json
import os
import sys
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Настройка вывода для Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)

SITE_MAP_FILE = DATA_DIR / 'its_site_map.json'
COOKIES_FILE = DATA_DIR / 'portal_cookies.json'

# Загружаем .env
load_dotenv(BASE_DIR / '.env')
USERNAME = os.getenv('ITS_USERNAME', '')
PASSWORD = os.getenv('ITS_PASSWORD', '')

if not USERNAME or not PASSWORD:
    print("❌ Ошибка: не указаны ITS_USERNAME и/или ITS_PASSWORD в .env")
    exit(1)

AUTH_URL = 'https://login.1c.ru/login?service=https%3A%2F%2Fits.1c.ru%2Flogin%2F%3Faction%3Daftercheck%26provider%3Dlogin'
BASE_URL = 'https://its.1c.ru'


def create_session():
    """Создать сессию с авторизацией через login.1c.ru"""
    session = requests.Session()

    # Пробуем загрузить сохранённые cookies
    if COOKIES_FILE.exists():
        with open(COOKIES_FILE, 'r') as f:
            cookies = requests.utils.cookiejar_from_dict(json.load(f))
        session.cookies.update(cookies)
        print('✅ Загружены сохранённые cookies')
        return session

    print('🔑 Авторизация на login.1c.ru...')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    # 1. Получаем страницу входа
    login_page = session.get(AUTH_URL, headers=headers, timeout=30)
    soup = BeautifulSoup(login_page.text, 'html.parser')

    # 2. Ищем форму
    form = soup.find('form')
    if not form:
        print("❌ Форма не найдена на странице входа")
        return None

    action = form.get('action', '')
    if not action.startswith('http'):
        action = 'https://login.1c.ru' + action

    print(f'  → action: {action}')

    # 3. Извлекаем все поля формы (включая скрытые — CSRF, execution, etc.)
    # Исключаем checkbox и submit, чтобы избежать typeMismatch
    data = {}
    for input_tag in form.find_all('input'):
        name = input_tag.get('name')
        value = input_tag.get('value', '')
        input_type = input_tag.get('type', 'text')
        if name and input_type not in ('checkbox', 'submit'):
            data[name] = value
            if input_type != 'hidden':
                print(f'  → поле: {name} = {value or "(пусто)"}')

    # 4. Добавляем логин/пароль (перезаписываем пустые значения)
    data['username'] = USERNAME
    data['password'] = PASSWORD

    # 5. Отправляем POST — все поля формы + логин/пароль
    print(f'  → отправка POST на {action}')
    print(f'  → полей в data: {len(data)}')
    response = session.post(
        action,
        data=data,
        headers={**headers, 'Content-Type': 'application/x-www-form-urlencoded', 'Referer': AUTH_URL},
        timeout=30,
        allow_redirects=True
    )

    print(f'  → статус: {response.status_code}')
    print(f'  → финальный URL: {response.url}')

    # 6. Проверяем, перенаправило ли на ITS
    if 'its.1c.ru' in response.url:
        print('✅ Авторизация успешна!')
        # Сохраняем cookies
        with open(COOKIES_FILE, 'w') as f:
            json.dump(requests.utils.dict_from_cookiejar(session.cookies), f, indent=2)
        print('  → Cookies сохранены')
        return session
    else:
        print('❌ Авторизация не удалась — не перенаправлено на its.1c.ru')
        # Сохраняем страницу для отладки
        debug_path = DATA_DIR / 'login_debug.html'
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f'  → Страница сохранена в {debug_path} для отладки')
        return None


def fetch_site_map(session):
    """Получить карту сайта its.1c.ru"""
    print('\n📂 Получение карты сайта...')

    # Собираем ссылки с главной страницы
    print('  Собираю ссылки с главной страницы...')
    main_page = session.get(BASE_URL, timeout=30)
    main_soup = BeautifulSoup(main_page.text, 'html.parser')
    
    urls_to_try = set()
    for a in main_soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/db/') and '/content/' in href:
            urls_to_try.add(f'{BASE_URL}{href}')
    
    # Добавляем основные разделы
    for section in ['/db/aboutitsnew', '/db/itsrev', '/db/morphmerged/search', '/news/']:
        urls_to_try.add(f'{BASE_URL}{section}')
    
    urls_to_try = list(urls_to_try)[:50]  # Ограничиваем количество

    site_map = {}

    for url in urls_to_try:
        try:
            print(f'  Проверяю: {url}')
            response = session.get(url, timeout=30)
            if response.status_code == 200:
                print(f'    ✅ Доступен ({len(response.text)} байт)')
                site_map[url] = {
                    'status': response.status_code,
                    'url': response.url,
                    'size': len(response.text),
                }
            else:
                print(f'    ❌ Ошибка {response.status_code}')
        except Exception as e:
            print(f'    ❌ Исключение: {e}')

    with open(SITE_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(site_map, f, indent=2, ensure_ascii=False)
    print(f'\n✅ Карта сайта сохранена в {SITE_MAP_FILE}')

    return site_map


if __name__ == '__main__':
    print('=== ITS Scout v3 ===')
    print(f'Логин: {USERNAME}')
    print(f'URL авторизации: {AUTH_URL}')
    print()

    session = create_session()
    if not session:
        exit(1)

    print()
    print('🔍 Проверка авторизации...')
    test_response = session.get(BASE_URL, timeout=30)
    print(f'  Статус главной страницы ITS: {test_response.status_code}')

    # Проверяем наличие PROFILE_TYPE cookie — признак успешной авторизации
    if 'PROFILE_TYPE' in session.cookies:
        print('✅ Авторизация подтверждена!')
        print()
        site_map = fetch_site_map(session)
        print()
        print('=== Результаты ===')
        for url, info in site_map.items():
            print(f'  {url}: {info["status"]} ({info["size"]} байт)')
    else:
        print('⚠️ Похоже, авторизация не прошла — нет PROFILE_TYPE cookie')
