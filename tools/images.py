# tools/images.py - 豆包 Seedream 图片生成工具
import re
import requests
import base64
import time
import os
from config import ARK_API_KEY, ARK_BASE_URL, IMAGE_MODEL, IMAGE_SIZE

_image_cache = {}


def generate_spot_image(spot_name: str, city: str = "") -> str:
    """用豆包 Seedream 模型生成景点图片，返回本地文件路径。"""
    cache_key = f"{spot_name}_{city}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    prompt = f"中国{city}{spot_name}风景名胜，蓝天白云，游客游览，高清摄影风格，宽幅风景照"

    try:
        url = f"{ARK_BASE_URL}/images/generations"
        headers = {
            "Authorization": f"Bearer {ARK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "size": IMAGE_SIZE,
            "response_format": "url",
            "stream": False,
            "watermark": True,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        # 解析返回的图片数据
        img_data = data.get("data", [])
        if not img_data:
            return _placeholder(spot_name, cache_key)

        img_info = img_data[0]

        # 优先取 url，其次取 b64_json
        img_url = img_info.get("url", "")
        b64 = img_info.get("b64_json", "")

        # 保存到本地
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "images")
        os.makedirs(output_dir, exist_ok=True)
        safe_name = re.sub(r'[\\/*?:"<>|]', "", spot_name)[:30]
        filepath = os.path.join(output_dir, f"{safe_name}.png")

        if b64:
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
        elif img_url:
            img_resp = requests.get(img_url, timeout=30)
            img_resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(img_resp.content)
        else:
            return _placeholder(spot_name, cache_key)

        _image_cache[cache_key] = filepath
        return filepath

    except Exception as e:
        print(f"[images] 生成 {spot_name} 图片失败: {e}")
        return _placeholder(spot_name, cache_key)


def _placeholder(spot_name: str, cache_key: str) -> str:
    """生成失败时返回空字符串（app.py 中会跳过显示）。"""
    _image_cache[cache_key] = ""
    return ""


def get_multiple_spot_images(spot_names: list, city: str = "") -> dict:
    """批量生成景点图片，返回 {景点名: 文件路径} 字典。"""
    results = {}
    for name in spot_names:
        results[name] = generate_spot_image(name, city)
        time.sleep(1)  # 避免 API 限流
    return results


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
