# tools/search.py - 搜索工具
import requests
from langchain_core.tools import tool


@tool
def search_attractions(city: str, travel_type: str = "性价比") -> str:
    """搜索城市热门景点信息，包括门票价格和游玩时长。
    city: 目标城市名
    travel_type: 旅行类型（特种兵/性价比/享受/City Walk/漫游）
    """
    try:
        url = f"https://wttr.in/{city}?format=j1"
        resp = requests.get(url, timeout=5)
    except:
        pass

    prompt = f"""请为{city}推荐8-12个热门景点，按旅行类型"{travel_type}"排序推荐。

每个景点包含：
- 景点名称
- 门票价格（元，免费的标注"免费"）
- 建议游玩时长（小时）
- 景点类型（自然风光/历史古迹/现代地标/美食街区/文化体验）
- 推荐指数（1-5星）
- 简短描述（一句话）

如果是"特种兵"类型，优先免费和低价景点，紧凑安排。
如果是"享受"类型，优先体验类和高品质景点。
如果是"City Walk"，优先街区、公园、免费景点。

请用以下格式输出，方便解析：
## 景点推荐
1. **景点名** | 门票:XX元 | 时长:X小时 | 类型:XX | 推荐:X星
   描述：一句话描述
"""
    return prompt


@tool
def search_transport(from_city: str, to_city: str, travel_type: str = "性价比") -> str:
    """查询两个城市之间的交通方式和费用。
    from_city: 出发城市
    to_city: 目的城市
    travel_type: 旅行类型
    """
    return f"""请查询从{from_city}到{to_city}的交通方式和费用，旅行类型为"{travel_type}"。

按旅行类型推荐：
- 特种兵：硬座、夜车、大巴（最省钱）
- 性价比：高铁二等座、普通火车
- 享受：高铁一等座、机票
- City Walk：地铁、公交
- 漫游：随意，推荐舒适方式

请列出：
1. 交通方式
2. 大致费用（单程）
3. 大致时长
4. 推荐理由

格式：
## 交通方案
**方式** | 费用:约XX元 | 时长:约XX小时 | 推荐:XX
"""


@tool
def search_food(city: str, budget_per_meal: int = 30) -> str:
    """搜索目的地特色美食和餐饮推荐。
    city: 目的地城市
    budget_per_meal: 每餐预算（元）
    """
    return f"""请推荐{city}的特色美食，每餐预算约{budget_per_meal}元。

请列出：
1. 早餐推荐（当地特色，价格范围）
2. 午餐推荐（当地特色，价格范围）
3. 晚餐推荐（当地特色，价格范围）
4. 小吃/零食推荐

格式：
## 餐饮推荐
**餐别** | 推荐:XX | 价格:约XX元/人 | 特色:XX
"""


@tool
def search_hotel(city: str, budget_per_night: int = 150) -> str:
    """搜索目的地住宿推荐。
    city: 目的地城市
    budget_per_night: 每晚预算（元）
    """
    return f"""请推荐{city}的住宿区域和类型，每晚预算约{budget_per_night}元。

请列出：
1. 推荐住宿区域（靠近哪些景点）
2. 住宿类型（青旅/经济酒店/民宿/舒适酒店）
3. 大致价格范围
4. 优缺点

格式：
## 住宿推荐
**区域** | 类型:XX | 价格:约XX元/晚 | 优点:XX
"""
