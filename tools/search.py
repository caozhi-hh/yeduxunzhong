# tools/search.py - 天气查询工具
import requests


def get_weather(city: str) -> str:
    """查询目的地未来3天天气预报。

    调用 wttr.in（免费，无需 API key），返回格式化的中文天气摘要。
    供 agent.py 的 @tool 和 backend/main.py 直接调用。

    Args:
        city: 中文城市名，如"北京"、"成都"、"西安"

    Returns:
        格式化的天气摘要字符串，失败时返回错误提示。
    """
    try:
        url = f"https://wttr.in/{city}?format=j1&lang=zh"
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        days = data.get("weather", [])
        lines = []
        for day in days:
            date = day.get("date", "")
            hourly = day.get("hourly", [])
            mid = hourly[4] if len(hourly) > 4 else (hourly[0] if hourly else {})
            max_temp = day.get("maxtempC", "?")
            min_temp = day.get("mintempC", "?")
            desc = mid.get("lang_zh", [{}])[0].get("value",
                    mid.get("weatherDesc", [{}])[0].get("value", "?"))
            wind = mid.get("windspeedKmph", "?")
            humidity = mid.get("humidity", "?")
            lines.append(
                f"{date}: {desc}, {min_temp}~{max_temp}°C, "
                f"风速{wind}km/h, 湿度{humidity}%"
            )

        return f"📍 {city}未来天气：\n" + "\n".join(lines)
    except Exception as e:
        return f"天气查询失败（{e}），请根据季节和常识给出穿衣建议。"
