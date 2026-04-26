# tools/images.py - Unsplash 景点真实照片搜索
import re
import requests
import base64
import os

UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

_image_cache = {}


def generate_spot_image(spot_name: str, city: str = "") -> dict:
    """从 Unsplash 搜索景点真实照片，返回 base64 图片。"""
    cache_key = f"{spot_name}_{city}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    if not UNSPLASH_ACCESS_KEY:
        print("[images] 未配置 UNSPLASH_ACCESS_KEY")
        return _error_result(cache_key)

    # 搜索关键词：中文景点名 + 英文关键词提高准确率
    query = f"{city} {spot_name} travel landmark" if city else f"{spot_name} travel landmark"

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
            # 换成纯英文搜索重试
            query2 = f"{spot_name} scenic"
            resp2 = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query2, "per_page": 3, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
                timeout=15,
            )
            results = resp2.json().get("results", [])

        if results:
            img_url = results[0]["urls"]["regular"]
            img_resp = requests.get(img_url, timeout=15)
            img_resp.raise_for_status()
            b64 = base64.b64encode(img_resp.content).decode("utf-8")
            result = {"status": "ok", "base64": f"data:image/jpeg;base64,{b64}"}
            _image_cache[cache_key] = result
            return result

        print(f"[images] Unsplash 无搜索结果: {query}")
        return _error_result(cache_key)

    except Exception as e:
        print(f"[images] 搜索 {spot_name} 照片失败: {e}")
        return _error_result(cache_key)


def _error_result(cache_key: str) -> dict:
    _image_cache[cache_key] = {"status": "error", "base64": ""}
    return {"status": "error", "base64": ""}


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
