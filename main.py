import random

# 数据结构：列表，每个元素是一个字典，存储餐厅名称、所属类型（正餐/自助/小吃及甜品）和细节信息（所属菜系）
# 类型分为：自助 / 正餐 / 小吃及甜品
restaurants = [
    {"name": "耶里夏丽", "type": "正餐", "detail": "新疆菜"},
    {"name": "食在顺德打边炉", "type": "正餐", "detail": "火锅"},
    {"name": "韩吞", "type": "正餐", "detail": "韩餐"},
    {"name": "滨寿司", "type": "正餐", "detail": "日餐"},
    {"name": "芝乐坊 The Cheesecake Factory", "type": "小吃及甜品", "detail": "甜点"},
    {"name": "奇利斯美式小餐馆 Chili's", "type": "正餐", "detail": "西餐"},
    {"name": "IMO阿姨汤饭", "type": "正餐", "detail": "韩餐"},
    {"name": "味冕Champs美式小餐馆", "type": "正餐", "detail": "西餐"},
    {"name": "OTF加州餐厅", "type": "正餐", "detail": "西餐"},
    {"name": "对酒当歌地道川菜", "type": "正餐", "detail": "川菜"},
    {"name": "大宝口福海鲜排挡", "type": "正餐", "detail": "上海菜"},
    {"name": "inkool创意韩餐", "type": "正餐", "detail": "韩餐"},
    {"name": "俄士厨房", "type": "正餐", "detail": "俄餐"},
    {"name": "东大门一头猪", "type": "烧烤", "detail": "韩餐"},
    {"name": "厚贞日式烤肉", "type": "烧烤", "detail": "日餐"},
    {"name": "安又胖韩国烤肉", "type": "烧烤", "detail": "韩餐"}
]

def pick_restaurant(restaurant_list):
    """
    根据餐厅总数生成随机数，并返回被选中的餐厅。
    随机数范围：1 到 餐厅总数（包含两端）
    """
    total = len(restaurant_list)
    if total == 0:
        return None, None, 0

    # 生成 1 到 total 之间的随机整数作为最大值
    random_num = random.randint(1, total)
    # 将随机数转换为列表索引（0 到 total-1）
    index = random_num - 1
    return restaurant_list[index], random_num, total

if __name__ == "__main__":
    print("📋 待去餐厅列表：")
    for i, r in enumerate(restaurants, 1):
        print(f"{i:2d}. {r['name']}  ——  {r['type']}")

    print("\n🎲 正在随机选择餐厅...")
    selected, num, total = pick_restaurant(restaurants)

    if selected:
        print(f"餐厅总数：{total}")
        print(f"生成的随机数：{num}")
        print(f"🎉 恭喜！今天就去：{selected['name']}（{selected['type']}）")
    else:
        print("❌ 餐厅列表为空，无法选择。")
