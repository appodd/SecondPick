"""Read explicit trading intent without treating system/legacy city metadata as intent.

No migration: old city values remain intact and are labelled unverified metadata.
Unknown wording is left for user confirmation, never converted to a hard filter.
"""
import re

_CITIES = "上海 北京 天津 重庆 深圳 广州 杭州 苏州 南京 成都 武汉 西安 郑州 长沙 宁波 无锡 厦门 福州 济南 青岛 合肥 昆明 南昌 南宁 贵阳 海口 沈阳 大连 长春 哈尔滨 石家庄 太原 呼和浩特 兰州 西宁 银川 乌鲁木齐 香港 澳门 台北 东莞 佛山 珠海 中山 温州 嘉兴 常州 南通 绍兴 金华 惠州".split()
_PLACE = "(?:" + "|".join(sorted(_CITIES, key=len, reverse=True)) + r")(?:市)?"
_NAMED_PLACE = r"(?:" + _PLACE + r"|[\u4e00-\u9fff]{2,6}(?:市|省))"


def region_preference(goal=None, *, hard=(), soft=(), explicit_city=None, legacy_city=None):
    def detect(text, kind=None):
        text = str(text or "").strip()
        clauses = re.split(r"[，,。；;\n]|但是|不过|但", text)
        if len(clauses) > 1:
            matches = [value for clause in clauses if (value := detect(clause, kind))]
            return next((value for value in matches if value[0] == "restricted"), matches[0] if matches else None)
        # Negated statements must not become a preference through a substring match.
        if re.search(r"不(?:要求|限定|限制|限于|偏好)|无需|不限地区|无地区偏好|不设置地区偏好", text):
            return None
        patterns = [
            ("preferred", r"^交易地区偏好[:：]\s*([^\n，,；;]{1,40}?)优先$"),
            ("restricted", r"^(?:交易地区限定|限定交易地区)[:：]\s*([^\n，,；;]{1,40})$"),
            ("restricted", rf"(?:只考虑|仅考虑|只接受|仅接受|仅限|限定|必须在|只在|限于)\s*({_NAMED_PLACE})(?:自提|交易|面交|本地|地区)?"),
            ("restricted", rf"({_NAMED_PLACE})(?:地区)?(?:自提|面交)?(?:限定|仅限|才考虑)"),
            ("preferred", rf"({_NAMED_PLACE})(?:地区)?(?:自提|面交)?优先"),
            ("preferred", rf"(?:优先考虑|优先|偏好|希望在)\s*({_NAMED_PLACE})"),
            ("preferred", rf"({_NAMED_PLACE})(?:自提|面交)"),
        ]
        if kind:
            match = re.fullmatch(rf"(?:交易地区|地区|城市)?\s*[:：]?\s*({_NAMED_PLACE})(?:自提|面交)?", text)
            if match:
                return kind, match.group(1).removesuffix("市")
        for mode, pattern in patterns:
            match = re.search(pattern, text)
            if match:
                # A condition explicitly placed in the soft list never becomes hard.
                return ("preferred" if "优先" in match.group(0) else kind or mode), match.group(1).removesuffix("市")
        return None

    result = next((value for item in hard if (value := detect(item, "restricted"))), None)
    if result is None:
        result = detect(goal)
    if result is None:
        result = next((value for item in soft if (value := detect(item, "preferred"))), None)
    if result is None and explicit_city and str(explicit_city).strip():
        result = "preferred", str(explicit_city).strip()
    mode, city = result or ("none", None)
    return dict(mode=mode, city=city, source="explicit" if result else "none",
                legacy_city=legacy_city or None,
                needs_confirmation=bool(not result and re.search(r"地区|城市|自提|面交", str(goal or '') + ' '.join([*hard, *soft]))),
                legacy_unverified=bool(legacy_city and not result))


def normalize_region_draft(payload, original_goal):
    """Do not let AI invent a city or promote an explicit soft preference to hard."""
    preference = region_preference(original_goal)
    result = dict(payload, goal=original_goal)
    for field in ("hard", "soft"):
        result[field] = [item for item in payload.get(field, [])
                         if region_preference(hard=[item])["mode"] == "none"]
    if preference["city"]:
        field = "hard" if preference["mode"] == "restricted" else "soft"
        trade = "自提" if "自提" in original_goal else "面交" if "面交" in original_goal else "交易"
        result[field].append(("只考虑" + preference["city"] + trade) if field == "hard" else preference["city"] + (trade if trade != "交易" else "") + "优先")
    return result


def region_instruction(preference):
    mode, city = preference["mode"], preference["city"]
    if mode == "none" and preference.get("needs_confirmation"):
        return "交易地区：原文可能包含尚未可靠识别的地区或交易方式要求，需核对原文并向用户确认。不要用系统默认城市或历史 city 字段补齐，不擅自排除商品，不修改监控。"
    if mode == "none":
        return "交易地区：不设置地区偏好。系统默认城市及历史 city 字段不是用户偏好，不得据此给同城加分、降低外地商品评价或排除商品。"
    if mode == "preferred":
        return f"交易地区：{city}优先，仅为软偏好，可解释交易便利性；不得作为硬条件，不得自动排除外地商品或修改监控。"
    return f"交易地区：限定{city}，为用户明确硬条件。按保存证据核实，地点缺失、冲突或不能确认自提条件时标记待核实；不要修改已有监控范围。"
