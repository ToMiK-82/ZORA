"""
tools/weather.py
Получение погоды для логистики: температура, осадки, ветер
"""
import requests
from typing import Optional, Dict

def get_weather(city: str = None) -> Optional[Dict[str, any]]:
    """
    Возвращает данные о погоде в виде словаря.
    Используется агентом логиста для анализа маршрутов.
    
    Теперь использует геокодирование через Open-Meteo API,
    чтобы получать погоду в любом городе по его названию.
    Если город не указан — возвращает ошибку.
    """
    if city is None:
        print("❌ Не указан город для получения погоды.")
        return None
        
    city = city.strip()
    if not city:
        print("❌ Название города пустое после очистки.")
        return None
        
    # Простая нормализация предложного падежа (упрощённый морфологический анализ)
    city_map = {
        'москве': 'москва',
        'петербурге': 'санкт-петербург',
        'екатеринбурге': 'екатеринбург',
        'новосибирске': 'новосибирск',
        'казане': 'казань',
        'краснодаре': 'краснодар',
        'симферополе': 'симферополь',
        'ростове': 'ростов-на-дону',
        'воронеже': 'воронеж',
        'самаре': 'самара',
        'челябинске': 'челябинск',
        'перми': 'пермь',
        'волгограде': 'волгоград',
        'красноярске': 'красноярск',
        'ульяновске': 'ульяновск',
        'ярославле': 'ярославль',
        'тюмени': 'тюмень',
        'барнауле': 'бarnaul',  # оставлено как есть, но в идеале — уточнить
        'иркутске': 'иркутск',
        'омске': 'омск',
        'кемерово': 'кемерово',
        'рязани': 'рязань',
        'набережныхчелнах': 'набережные челны',
        'пензе': 'пенза',
        'липецке': 'липецк',
        'кирове': 'киров',
        'чебоксарах': 'чебоксары',
        'тольятти': 'тольятти',
        'калиниграде': 'калиниград',
        'астрахани': 'астрахань',
        'владивостоке': 'владивосток',
        'мурманске': 'мурманск',
        'твери': 'тверь',
        'ставрополе': 'ставрополь',
        'нижнемновгороде': 'нижний новгород',
        'хабаровске': 'хабаровск',
        'белгороде': 'белгород',
        'курске': 'курск',
        'сочи': 'сочи',
        'томске': 'томск',
        'магнитогорске': 'магнитогорск',
        'иваново': 'иваново',
        'твери': 'тверь',
        'брятске': 'брятск',
        'сургуте': 'сургут',
        'владимире': 'владимир',
        'чите': 'чита',
        'архангельске': 'архангельск',
        'химках': 'химки'
    }
    
    city_lower = city.lower()
    normalized_city = city_map.get(city_lower, city_lower)
    
    # Используем геокодирование через Open-Meteo Geocoding API
    try:
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocode_params = {"name": normalized_city, "count": 1, "language": "ru", "format": "json"}
        geocode_response = requests.get(geocode_url, params=geocode_params, timeout=10)
        geocode_response.raise_for_status()
        geocode_data = geocode_response.json()
        
        if "results" not in geocode_data or not geocode_data["results"]:
            print(f"❌ Город '{city}' (нормализовано: '{normalized_city}') не найден в результате геокодирования.")
            return None
            
        location = geocode_data["results"][0]
        lat, lon = location["latitude"], location["longitude"]
        city_result = location["name"]  # Уточняем название города из API
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка HTTP-запроса при геокодировании: {e}")
        return None
    except Exception as e:
        print(f"❌ Неожиданная ошибка при геокодировании: {e}")
        return None

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m,precipitation",
            "hourly": "temperature_2m,precipitation_probability",
            "forecast_days": 1,
            "timezone": "Europe/Moscow"
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data["current"]
        hourly = data["hourly"]

        # Коды погоды
        weather_code = current["weather_code"]
        weather_desc = {
            0: "ясно", 1: "в основном ясно", 2: "частичная облачность", 3: "облачно",
            45: "туман", 48: "туман с изморозью",
            51: "лёгкий дождь", 53: "умеренный дождь", 55: "сильный дождь",
            61: "слабый дождь", 63: "умеренный дождь", 65: "сильный дождь",
            71: "слабый снег", 73: "умеренный снег", 75: "сильный снег",
            95: "гроза", 96: "гроза с градом"
        }.get(weather_code, "неизвестно")

        return {
            "city": city_result,
            "temperature": current["temperature_2m"],
            "weather_code": weather_code,
            "description": weather_desc,
            "precipitation": current["precipitation"] > 0,
            "precipitation_mm": current["precipitation"],
            "wind_speed": current["wind_speed_10m"],
            "hourly_forecast": {
                "next_3h_temp": hourly["temperature_2m"][1:4],
                "precipitation_chance": max(hourly["precipitation_probability"][1:4])
            },
            "raw": data  # можно использовать для глубокого анализа
        }
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка HTTP-запроса при получении погоды: {e}")
        return None
    except Exception as e:
        print(f"❌ Неожиданная ошибка при получении погоды: {e}")
        return None