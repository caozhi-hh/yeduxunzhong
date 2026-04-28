# tools/images.py - Unsplash 景点真实照片搜索
import re
import requests
import base64
import os
from config import UNSPLASH_ACCESS_KEY

_image_cache = {}


def generate_spot_image(spot_name: str, city: str = "") -> dict:
    """从 Unsplash 搜索景点真实照片，返回 base64 图片。"""
    cache_key = f"{spot_name}_{city}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    if not UNSPLASH_ACCESS_KEY:
        print("[images] 未配置 UNSPLASH_ACCESS_KEY")
        return _error_result(cache_key)

    # 搜索关键词：去掉 "travel landmark" 噪声词，提高中文景点匹配率
    query = f"{spot_name} {city}" if city else spot_name

    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 3, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        if not results:
            # 中文搜不到，用英文关键词兜底
            query2 = f"{spot_name} China"
            resp2 = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query2, "per_page": 3, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
                timeout=15,
            )
            results = resp2.json().get("results", [])

        if results:
            img_url = results[0]["urls"]["regular"]
            result = {"status": "ok", "url": img_url, "base64": ""}
            _image_cache[cache_key] = result
            return result

        print(f"[images] Unsplash 无搜索结果: {query}")
        return _error_result(cache_key)

    except Exception as e:
        print(f"[images] 搜索 {spot_name} 照片失败: {e}")
        return _error_result(cache_key)


def _error_result(cache_key: str) -> dict:
    _image_cache[cache_key] = {"status": "error", "url": "", "base64": ""}
    return {"status": "error", "url": "", "base64": ""}


def extract_spots_from_text(text: str) -> list:
    """从 AI 推荐文本中提取景点名称。"""
    spots = []
    seen = set()

    bold_pattern = r'\*\*([^*]{2,20})\*\*'
    skip_words = [
        "门票", "时长", "推荐", "价格", "费用", "交通", "住宿", "餐饮",
        "预算", "行程", "描述", "备注", "总计", "合计", "Day", "天", "第",
        "小时", "元", "攻略", "参考", "其他", "注意", "提示", "建议",
        "到达", "离开", "早", "中", "晚", "餐", "住宿建议", "费用明细",
        "实用贴士", "详细攻略", "大景点", "推荐景点", "顺路", "位置",
        "美食", "特产", "小吃", "景点推荐", "安排", "路线",
        "全天", "半天", "上午", "下午", "傍晚", "晚上", "夜景",
        "早上", "出发", "回程", "自由", "休息", "返程",
        "预约", "放票", "抢票",
    ]
    for match in re.finditer(bold_pattern, text):
        name = match.group(1).strip()
        if name not in seen and len(name) >= 2 and not any(w in name for w in skip_words):
            spots.append(name)
            seen.add(name)

    if not spots:
        emoji_pattern = r'[🏞️🏯🏔️🛕🏛️🕌🏰⛩️⛪🌉🌃🏖️🌋🏕️]\s*(.+?)(?:\n|$)'
        for match in re.finditer(emoji_pattern, text):
            name = match.group(1).strip()
            if name not in seen and len(name) >= 2:
                spots.append(name)
                seen.add(name)

    return spots[:12]


def geocode_spots(spots: list, city: str) -> list:
    """用 LLM 生成景点的大致经纬度坐标。"""
    if not spots:
        return []

    try:
        from config import ARK_API_KEY, ARK_BASE_URL, CHAT_MODEL
        from langchain_openai import ChatOpenAI
        import json

        geo_llm = ChatOpenAI(
            model=CHAT_MODEL, api_key=ARK_API_KEY, base_url=ARK_BASE_URL, streaming=False,
        )

        spot_list = "、".join(spots)
        prompt = f"""请给出{city}以下景点的大致经纬度坐标（GCJ-02坐标系，用于高德地图）。
只返回JSON数组，不要其他内容。格式：
[{{"name":"景点名","lng":120.xxx,"lat":30.xxx}}]

景点：{spot_list}"""

        resp = geo_llm.invoke(prompt)
        text = resp.content.strip()
        # 提取 JSON 部分
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            return [{"name": r["name"], "lng": float(r["lng"]), "lat": float(r["lat"])} for r in result if "lng" in r and "lat" in r]
    except Exception as e:
        print(f"[geocode_spots] LLM 地理编码失败: {e}")

    return []
