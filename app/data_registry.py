"""真实数据登记表：官方预约链接与数据可信度分级。"""

from __future__ import annotations

OFFICIAL_SITES = {
    "布达拉宫": "https://potalapalace.cn",
    "故宫": "https://gugong.ktmtech.cn",
    "故宫博物院": "https://gugong.ktmtech.cn",
    "八达岭长城": "https://www.badaling.cn",
    "国家博物馆": "https://www.chnmuseum.cn",
    "中国国家博物馆": "https://www.chnmuseum.cn",
    "颐和园": "https://www.summerpalace-china.com",
    "天坛": "https://www.tiantanpark.com",
    "成都大熊猫繁育研究基地": "https://www.panda.org.cn",
    "上海迪士尼度假区": "https://www.shanghaidisneyresort.com",
    "上海迪士尼乐园": "https://www.shanghaidisneyresort.com",
    "北京环球度假区": "https://www.universalbeijingresort.com",
    "秦始皇兵马俑": "https://www.bmy.com.cn",
    "秦始皇帝陵博物院": "https://www.bmy.com.cn",
    "莫高窟": "https://www.mogaoku.net",
    "三星堆博物馆": "https://www.sxd.cn",
    "广州长隆": "https://www.chimelong.com",
    "长隆野生动物世界": "https://www.chimelong.com",
}

LEVEL_LABELS = {
    "S": "官方实时",
    "A": "官方预约",
    "B": "参考",
    "C": "估算",
    "D": "用户反馈",
}


def official_site(name: str) -> str:
    if not name:
        return ""
    for key, url in OFFICIAL_SITES.items():
        if key in name or name in key:
            return url
    return ""


def level_label(level: str) -> str:
    return LEVEL_LABELS.get(level, "参考")
