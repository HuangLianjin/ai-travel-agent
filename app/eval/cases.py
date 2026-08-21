"""24+ 条业务评测用例：意图识别、参数提取、RAG 检索与行程校验。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    title: str
    input_text: str
    expected_intent: str = "create"
    expected_city: str = "北京"
    expected_keywords: tuple[str, ...] = ()
    expected_absent: tuple[str, ...] = ()
    expected_params: dict = field(default_factory=dict)


EVAL_CASES = [
    EvalCase("t001", "北京三天经典游", "我想去北京玩三天，预算3000元，喜欢历史和美食", "create", "北京", ("北京", "3 日"), {"days": 3}),
    EvalCase("t002", "成都美食游", "成都两天，喜欢火锅和小吃，两个人，预算2000", "create", "成都", ("成都", "2 日"), {"days": 2, "travelers": 2}),
    EvalCase("t003", "上海亲子游", "带孩子去上海迪士尼，计划三天，预算8000", "create", "上海", ("上海", "3 日"), {"days": 3}),
    EvalCase("t004", "北京轻松游", "北京轻松玩两天，不要太赶，喜欢拍照", "create", "北京", ("轻松",), {"days": 2}),
    EvalCase("t005", "成都自然路线", "成都三天，喜欢自然风景，自驾", "create", "成都", ("自驾", "3 日"), {"transport": "自驾", "days": 3}),
    EvalCase("t006", "上海夜景路线", "上海两天，想看夜景和街区，预算1500", "create", "上海", ("外滩",), {"days": 2}),
    EvalCase("t007", "北京亲子文化", "北京三天，亲子，想看故宫和长城", "create", "北京", ("故宫", "长城"), {"days": 3}),
    EvalCase("t008", "成都历史游", "成都两天，喜欢三国历史，预算1000", "create", "成都", ("武侯祠",), {"days": 2}),
    EvalCase("t009", "上海美食早餐", "上海两天，主要吃小笼包和生煎", "create", "上海", ("小笼包", "生煎包"), {"days": 2}),
    EvalCase("t010", "北京高铁游", "北京三天，坐高铁去，预算5000", "create", "北京", ("高铁",), {"transport": "高铁", "days": 3}),
    EvalCase("a001", "当天轻松一些", "当天轻松一些，不要安排太多景点", "adjust", "北京", ("轻松",), {}),
    EvalCase("a002", "增加火锅", "增加火锅推荐，晚上想吃火锅", "adjust", "成都", ("火锅",), {}),
    EvalCase("a003", "推荐附近酒店", "帮我推荐附近酒店", "adjust", "上海", ("酒店",), {}),
    EvalCase("a004", "去掉长城", "第二天去掉长城，太远了", "adjust", "北京", (), ("长城",), {}),
    EvalCase("a005", "减少一天", "行程改成一天，太赶了", "adjust", "北京", (), {"days": 1}),
    EvalCase("a006", "增加亲子景点", "增加适合亲子的景点", "adjust", "成都", ("亲子",), {}),
    EvalCase("a007", "换交通方式", "改成自驾", "adjust", "成都", ("自驾",), {"transport": "自驾"}),
    EvalCase("a008", "提前出发", "第二天提前到早上七点出发", "adjust", "上海", (), {}),
    EvalCase("q001", "成都攻略", "成都攻略有什么推荐", "ask", "成都", ("成都",), {}),
    EvalCase("q002", "北京吃什么", "北京有什么必吃美食", "ask", "北京", ("烤鸭",), {}),
    EvalCase("q003", "上海玩法", "上海两天怎么玩", "ask", "上海", ("上海",), {}),
    EvalCase("q004", "长城介绍", "介绍一下八达岭长城", "ask", "北京", ("长城",), {}),
    EvalCase("c001", "你好", "你好", "chat", "北京", (), {}),
    EvalCase("c002", "谢谢", "谢谢", "chat", "北京", (), {}),
]


def load_cases() -> list[EvalCase]:
    return list(EVAL_CASES)

