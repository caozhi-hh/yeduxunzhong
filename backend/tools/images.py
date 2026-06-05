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
        "预约", "放票", "抢票", "旅行", "类型", "出行",
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

    # 兜底：按 --- 或 \n\n 分段，找含 emoji 的行
    if len(spots) < 3:
        segments = re.split(r'(?:---|\n{2,})', text)
        for seg in segments:
            lines = seg.strip().split('\n')
            if not lines:
                continue
            first = lines[0].strip()
            # 从第一行提取名字（去掉 emoji 和 markdown 符号）
            clean = re.sub(r'[🏞️🏯🏔️🛕🏛️🕌🏰⛩️⛪🌉🌃🏖️🌋🏕️📄🎫⏰📍📝🔀💡⭐*\s]', '', first).strip()
            if clean and clean not in seen and len(clean) >= 2 and not any(w in clean for w in skip_words):
                spots.append(clean)
                seen.add(clean)

    return spots[:12]


def extract_spot_details(text: str) -> list:
    """从 AI 推荐文本中提取景点详细信息（名称、评分、时长、描述）。"""
    spots = []
    seen = set()

    skip_words = [
        "门票", "时长", "推荐", "价格", "费用", "交通", "住宿", "餐饮",
        "预算", "行程", "描述", "备注", "总计", "合计", "Day", "天", "第",
        "小时", "元", "攻略", "参考", "其他", "注意", "提示", "建议",
        "到达", "离开", "早", "中", "晚", "餐", "住宿建议", "费用明细",
        "实用贴士", "详细攻略", "大景点", "推荐景点", "顺路", "位置",
        "美食", "特产", "小吃", "景点推荐", "安排", "路线",
        "全天", "半天", "上午", "下午", "傍晚", "晚上", "夜景",
        "早上", "出发", "回程", "自由", "休息", "返程",
        "预约", "放票", "抢票", "旅行", "类型", "出行",
    ]

    # 按 --- 分段，每段是一个景点
    segments = re.split(r'---+', text)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        lines = seg.split('\n')
        name = ""
        rating = ""
        duration = ""
        desc = ""
        ticket = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取名字：从 bold 标记或第一行含 emoji 的行
            bold_match = re.search(r'\*\*([^*]{2,20})\*\*', line)
            if bold_match:
                candidate = bold_match.group(1).strip()
                if not name and not any(w in candidate for w in skip_words):
                    name = candidate

            # 提取评分
            rating_match = re.search(r'⭐\s*推荐指数[：:]\s*(\S+)', line)
            if rating_match:
                rating = rating_match.group(1).strip()
            else:
                rating_match = re.search(r'⭐\s*(\d\.?\d*\s*[/／]\s*\d)', line)
                if rating_match:
                    rating = rating_match.group(1).strip()

            # 提取时长
            duration_match = re.search(r'游玩时长[：:]\s*(\S+)', line)
            if duration_match:
                duration = duration_match.group(1).strip()
            else:
                duration_match = re.search(r'⏰\s*(\d+[~\-到]\d*\s*小时)', line)
                if duration_match:
                    duration = duration_match.group(1).strip()

            # 提取门票
            ticket_match = re.search(r'门票[：:]\s*(.+?)(?:\||\n|$)', line)
            if ticket_match:
                ticket = ticket_match.group(1).strip()

            # 提取描述（📝 开头或一句话描述）
            if '📝' in line or '一句话描述' in line:
                desc_clean = re.sub(r'[📝\s]', ' ', line).strip()
                desc = re.sub(r'一句话描述[：:]?\s*', '', desc_clean).strip()

        # 如果没有通过 bold 提取到名字，尝试从第一行提取
        if not name and lines:
            first = lines[0].strip()
            clean = re.sub(r'[🏞️🏯🏔️🛕🏛️🕌🏰⛩️⛪🌉🌃🏖️🌋🏕️*\s]', '', first).strip()
            if clean and len(clean) >= 2 and not any(w in clean for w in skip_words):
                name = clean

        if name and name not in seen and len(name) >= 2:
            seen.add(name)
            spots.append({
                "name": name,
                "rating": rating or "",
                "duration": duration or "",
                "ticket": ticket or "",
                "desc": desc or "",
            })

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
