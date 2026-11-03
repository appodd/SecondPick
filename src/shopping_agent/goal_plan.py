from __future__ import annotations

from shopping_agent.region_preference import region_preference, region_instruction

import re
from dataclasses import dataclass


@dataclass
class GoalPlanOptions:
    city: str | None = None
    platforms: list[str] | None = None
    clarify_via_codex: bool = False
    expand_similar_via_codex: bool = False


def build_goal_plan(goal: str, options: GoalPlanOptions | None = None) -> dict:
    options = options or GoalPlanOptions()
    platforms = options.platforms or ["xianyu"]
    facts = _extract_goal_facts(goal)
    preference = region_preference(goal, explicit_city=options.city)
    city = preference['city'] or ''
    if facts["family"] == "macbook":
        plan = _macbook_goal_plan(goal, facts, city, platforms)
    elif facts["family"] == "imac":
        plan = _imac_goal_plan(goal, facts, city, platforms)
    else:
        plan = _generic_goal_plan(goal, facts, city, platforms)
    plan["region_preference"] = preference
    plan["region_instruction"] = region_instruction(preference)
    plan["notes"] = [
        "This is a planning artifact for the LLM/Codex, not a final purchase recommendation.",
        "Search terms are seed strategies. The LLM should revise them after inspecting run-summary and candidate-pool outputs.",
        "Keep at least one broad/unfiltered run for audit before narrowing with price or platform filters.",
        "When clarification_request.is_ambiguous is true, a Codex-driven clarification pass can refine the fuzzy goal using the model product knowledge; this is advisory and does not auto-launch Codex.",
    ]
    if getattr(options, "clarify_via_codex", False):
        plan["clarification_request"] = build_clarification_request(goal, facts, city)
    if getattr(options, "expand_similar_via_codex", False):
        plan["similar_product_request"] = build_similar_product_request(goal, facts, city)
    return plan


def build_similar_product_request(goal: str, facts: dict, city: str) -> dict:
    """Build an advisory Codex request to expand similar/adjacent products.

    Covers the case where the user has settled on a target (e.g. MacBook M1)
    but is open to similar products (M2, M1 Pro, adjacent models). Toggled off
    by default: when the user only wants the exact model (common for spare parts
    or accessory buys), the caller leaves --expand-similar-via-codex off and no
    expansion request is produced.
    """
    prompt = _build_similar_product_prompt(goal, facts, city)
    return {
        "is_specific_target": facts.get("family", "generic") != "generic",
        "codex_prompt": prompt,
        "command_preview": _similar_product_codex_command(goal),
        "policy": (
            "Advisory only. Does not auto-launch Codex or open a platform. "
            "When is_specific_target is true the user has a concrete model; "
            "expansion is opt-in and the caller decides whether to run it. "
            "When the user only wants the exact model, leave this request unexecuted."
        ),
    }


def _build_similar_product_prompt(goal: str, facts: dict, city: str) -> str:
    family = facts.get("family", "generic")
    subtype = facts.get("subtype")
    chips = facts.get("chips") or []
    sizes = facts.get("screen_sizes") or []
    years = facts.get("years") or []
    target_line = f"Recognized target: family={family}"
    if subtype:
        target_line += f", subtype={subtype}"
    if chips:
        target_line += f", chips={chips}"
    if sizes:
        target_line += f", screen_sizes={sizes}"
    if years:
        target_line += f", years={years}"
    return f"""You are the planner for a secondhand shopping research workflow.

User goal: {goal}
Explicit trading city (empty means no preference): {city}
{target_line}

The user has shown some specificity but may be open to similar or adjacent products.
Expand the search surface with model knowledge. Do NOT open any platform or run browser
collection. Specifically:
1. List 2-5 similar or adjacent products worth comparing: same-series adjacent generations
   (e.g. M1 -> M2), tier variants (e.g. base chip -> Pro/Max), same-brand alternatives in the
   same category, or category-equivalents from other brands. Give a one-line reason each and
   note whether it is a near-equivalent or a trade-off (price/performance/availability).
2. For each, give the typical Chinese secondhand price band and the main caveat.
3. Mark which expansions are "safe to include by default" (close enough to not pollute the
   candidate pool) versus "needs explicit user confirmation" (meaningfully different price or
   form factor that could derail the comparison).
4. If the goal looks like a spare-part or accessory buy (the user wants one exact item), state
   that expansion is probably unwanted and explain why.

Return only the similar-product expansion pass. The downstream workflow will fold approved
expansions into search_rounds as alternatives before any real platform search.
"""


def _similar_product_codex_command(goal: str) -> str:
    escaped = goal.replace("\\", "\\\\").replace('"', '\\"')
    return (
        'codex --search "Expand similar/adjacent products for the shopping goal below. '
        f'Do not open any platform.\n\nGoal: \"{escaped}\""'
    )


def is_goal_ambiguous(facts: dict) -> bool:
    """Decide whether the extracted intent is too vague for rule-based search seeding.

    Conservative heuristic so a Codex clarification pass is only suggested when
    the rule layer genuinely cannot seed useful searches. Recognized macbook/imac
    families are treated as specific enough; generic goals, or named families
    missing all discriminating dimensions (chip, size, memory, year), are vague.
    """
    family = facts.get("family", "generic")
    if family == "generic":
        return True
    has_chip = bool(facts.get("chips"))
    has_size = bool(facts.get("screen_sizes"))
    has_memory = facts.get("memory_gb") is not None
    has_year = bool(facts.get("years"))
    return not (has_chip or has_size or has_memory or has_year)


def build_clarification_request(goal: str, facts: dict, city: str) -> dict:
    """Build an advisory Codex clarification request for a fuzzy goal.

    Returns a prompt plus a Codex command preview so the caller (CLI or a
    driving Codex session) can decide whether to run it. Does not launch
    Codex itself; this keeps the path deterministic, testable, and side-effect
    free unless the caller explicitly runs the preview.
    """
    ambiguous = is_goal_ambiguous(facts)
    prompt = _build_clarification_prompt(goal, facts, city, ambiguous=ambiguous)
    return {
        "is_ambiguous": ambiguous,
        "reason": (
            "Could not recognize a target product family or any discriminating "
            "dimension (chip, screen size, memory, year); rule-based search terms "
            "are unlikely to be specific."
            if ambiguous
            else "Goal is specific enough for rule-based seeding, but Codex can still "
            "refine adjacent-model and price-band context."
        ),
        "codex_prompt": prompt,
        "command_preview": _clarification_codex_command(goal),
        "policy": (
            "This request is advisory. It must not auto-launch Codex or open a "
            "platform. The caller decides whether to run command_preview. "
            "Clarification output feeds back into a refined goal-plan, not directly "
            "into browser collection."
        ),
    }


def _build_clarification_prompt(goal: str, facts: dict, city: str, *, ambiguous: bool) -> str:
    family = facts.get("family", "generic")
    facts_lines = [
        f"- family: {family}",
        f"- subtype: {facts.get('subtype')}",
        f"- chips: {facts.get('chips')}",
        f"- screen_sizes: {facts.get('screen_sizes')}",
        f"- memory_gb: {facts.get('memory_gb')}",
        f"- storage: {facts.get('storage')}",
        f"- years: {facts.get('years')}",
        f"- mentions_city: {facts.get('mentions_city')}",
    ]
    facts_block = "\n".join(facts_lines)
    ambiguity_note = (
        "The user goal is vague: the rule layer could not extract a product family or any "
        "discriminating dimension. You must NOT assume a specific model. Use your product "
        "knowledge to propose a small set of plausible candidate product identities, typical "
        "price bands, and the dimensions most worth confirming with the user."
        if ambiguous
        else "The user goal is partly specific but could still benefit from Codex refinement "
        "of adjacent models, typical configurations, and price-band context."
    )
    return f"""You are the planner for a secondhand shopping research workflow.

User goal: {goal}
Explicit trading city (empty means no preference): {city}

Extracted intent (rule-based, possibly incomplete):
{facts_block}

{ambiguity_note}

Produce a concise clarification pass for the user. Do NOT open any platform or run browser
collection. Specifically:
1. State your best hypothesis of the target product identity (brand/model/series), or if
   genuinely ambiguous, list 2-3 plausible candidates with a one-line reason each.
2. Give typical price bands for the Chinese secondhand market for each candidate, with the
   caveats that make them uncertain.
3. List the dimensions most worth confirming with the user to narrow the search: prioritize
   by impact on price and on whether results would be polluted (e.g. screen size, chip,
   memory/storage, condition, must-have vs nice-to-have, local-pickup vs shipping).
4. Draft the clarification questions in natural Chinese, ordered by importance. Mark which
   are blocking (product identity is too unclear) versus non-blocking (can be answered while
   a broad search runs).

Return only the clarification pass. The downstream workflow will fold your answers into a
refined goal-plan before any real platform search.
"""


def _clarification_codex_command(goal: str) -> str:
    escaped = goal.replace("\\", "\\\\").replace('"', '\\"')
    return (
        'codex --search "Refine the fuzzy shopping goal below into targeted clarification '
        f'questions and candidate product identities. Do not open any platform.\n\nGoal: \"{escaped}\""'
    )


def _extract_goal_facts(goal: str) -> dict:
    lowered = goal.lower()
    compact = re.sub(r"\s+", "", lowered)
    family = "generic"
    if "macbook" in lowered or "苹果笔记本" in goal or "苹果电脑" in goal:
        family = "macbook"
    elif "imac" in lowered or "一体机" in goal:
        family = "imac"

    subtype = None
    if "macbook pro" in lowered or "macbookpro" in compact:
        subtype = "pro"
    elif "macbook air" in lowered or "macbookair" in compact:
        subtype = "air"

    chips = []
    for chip in ("m4", "m3", "m2", "m1"):
        if re.search(rf"\b{chip}\b", lowered) or chip in compact:
            chips.append(chip.upper())
    for chip in ("m3 pro", "m2 pro", "m1 pro", "m1 max", "m2 max", "m3 max"):
        if chip in lowered or chip.replace(" ", "") in compact:
            chips.append(chip.upper())
    chips = _dedupe(chips)

    return {
        "family": family,
        "subtype": subtype,
        "chips": chips,
        "years": _extract_years(goal),
        "screen_sizes": _extract_screen_sizes(goal, family=family),
        "memory_gb": _extract_capacity_gb(goal, labels=("内存", "运存", "ram", "memory")),
        "storage": _extract_storage(goal),
        "mentions_city": _extract_city(goal),
        "raw_goal": goal,
    }


def _macbook_goal_plan(goal: str, facts: dict, city: str, platforms: list[str]) -> dict:
    target = "MacBook"
    if facts["subtype"] == "pro":
        target = "MacBook Pro"
    elif facts["subtype"] == "air":
        target = "MacBook Air"

    chip_terms = _macbook_chip_terms(facts)
    chips = facts["chips"]
    screen_sizes = facts["screen_sizes"]
    memory_gb = facts["memory_gb"]
    storage = facts["storage"]

    primary_queries = []
    compound_queries = []
    if chip_terms:
        for chip in chip_terms:
            if screen_sizes or memory_gb or storage:
                compound_queries.append(
                    _macbook_query(
                        target,
                        chip=chip,
                        size=screen_sizes[0] if screen_sizes else None,
                        memory_gb=memory_gb,
                        storage=storage,
                    )
                )
            primary_queries.append(f"{target} {chip}")
    else:
        if screen_sizes or memory_gb or storage:
            compound_queries.append(
                _macbook_query(
                    target,
                    size=screen_sizes[0] if screen_sizes else None,
                    memory_gb=memory_gb,
                    storage=storage,
                )
            )
        primary_queries.append(target)

    primary_queries = compound_queries + primary_queries

    if screen_sizes:
        for size in screen_sizes:
            primary_queries.append(f"{target} {size}寸")
    elif facts["subtype"] == "pro":
        primary_queries.extend([f"{target} 14寸", f"{target} 16寸"])

    if memory_gb:
        primary_queries.append(f"{target} {memory_gb}G")
    elif facts["subtype"] == "pro":
        primary_queries.append(f"{target} 32G")

    if facts["subtype"] == "pro":
        primary_queries.extend(["A2442 32G", "A2485 32G"])

    alternatives = []
    if any(chip in chips for chip in ("M1", "M1 PRO")) or not chips:
        alternatives.append(
            {
                "query": _macbook_query(
                    "MacBook Pro",
                    chip="M2 Pro",
                    size=screen_sizes[0] if screen_sizes else None,
                    memory_gb=memory_gb,
                    storage=storage,
                ),
                "reason": "相邻一代，若价格接近或成色明显更好，可能比 M1 Pro 更值得比较。",
                "requires_user_confirmation": False,
            }
        )
    if facts["subtype"] == "pro" and not facts["screen_sizes"]:
        alternatives.append(
            {
                "query": "MacBook Pro 14寸 M1 Pro",
                "reason": "14 寸通常是便携和性能的平衡点，可作为默认重点样本。",
                "requires_user_confirmation": False,
            }
        )

    questions = []
    if facts["subtype"] == "pro" and "M1" in chips and "M1 PRO" not in chips:
        questions.append("你说的 M1 是基础款 M1，还是 M1 Pro/M1 Max？这会影响 13 寸旧模具和 14/16 寸新模具的搜索口径。")
    if not facts["screen_sizes"] and facts["subtype"] == "pro":
        questions.append("14 寸和 16 寸是否都接受？16 寸更重但散热和屏幕更好，价格样本也会不同。")
    if not facts["memory_gb"]:
        questions.append("内存是否有硬要求，例如 16G 够用还是优先 32G？这会显著影响价格区间。")
    questions.append("是否有交易地区或自提要求？未明确时不设置地区偏好，异地商品同样参与比较。")
    questions.append("是否接受 M2 Pro 或 M1 Max 这类相邻方案，只在价格明显合适时纳入对比？")

    return _assemble_plan(
        goal=goal,
        facts=facts,
        city=city,
        platforms=platforms,
        primary_queries=_dedupe(primary_queries),
        alternatives=alternatives,
        clarification_questions=_dedupe(questions),
        conditional_filters=[
            {
                "condition": "如果首轮结果被保护壳、贴膜、键盘膜、包装盒、配件或低价服务项污染。",
                "filters": {"min_price": 3000},
                "reason": "MacBook Pro Apple Silicon 整机通常不会低到配件价；保留无过滤 run 后再加价格下限提升整机密度。",
            }
        ],
    )


def _imac_goal_plan(goal: str, facts: dict, city: str, platforms: list[str]) -> dict:
    years = facts["years"]
    sizes = facts["screen_sizes"] or [27]
    primary_queries = []
    for size in sizes:
        primary_queries.append(f"iMac {size}")
        for year in years:
            primary_queries.append(f"{year} iMac {size}")
        primary_queries.append(f"苹果一体机 {size}寸 5K")

    alternatives = []
    if 2020 not in years:
        alternatives.append(
            {
                "query": "2020 iMac 27",
                "reason": "相邻年份，可能作为价格/配置基准或替代选择。",
                "requires_user_confirmation": False,
            }
        )

    questions = [
        "是否接受 2020 款作为相邻年份对比？它可能在 CPU/GPU/SSD 配置上更好，但价格也会变化。",
        "是否要求原装硬盘，还是接受后换 SSD？iMac 老机型里 1TB 可能是 SSD，也可能是 Fusion Drive。",
        "是否接受后加内存？iMac 27 寸内存升级常见，但硬盘/显卡拆修风险不同。",
        "是否有交易地区或自提要求？未明确时不设置地区偏好；27 寸 iMac 需另行核实包装和运输风险。",
    ]

    return _assemble_plan(
        goal=goal,
        facts=facts,
        city=city,
        platforms=platforms,
        primary_queries=_dedupe(primary_queries),
        alternatives=alternatives,
        clarification_questions=questions,
        conditional_filters=[
            {
                "condition": "如果结果混入 21.5 寸、配件、维修升级服务或明显旧款。",
                "filters": {"min_price": 2500},
                "reason": "保留无过滤 run 后，再用保守价格下限降低配件和维修服务噪音。",
            }
        ],
    )


def _generic_goal_plan(goal: str, facts: dict, city: str, platforms: list[str]) -> dict:
    return _assemble_plan(
        goal=goal,
        facts=facts,
        city=city,
        platforms=platforms,
        primary_queries=[goal],
        alternatives=[],
        clarification_questions=[
            "这个目标商品的品牌、型号、预算、成色和地区偏好是什么？如果不确定，可以先让我做一轮宽搜索。",
            "地区默认不限；如有偏好，请区分某地区优先与仅接受某地区交易。",
        ],
        conditional_filters=[
            {
                "condition": "如果首轮结果明显包含大量配件、服务或无关商品。",
                "filters": {"min_price": "LLM-estimated"},
                "reason": "由大模型根据首轮价格分布估计保守价格下限，不写死全局阈值。",
            }
        ],
    )


def _assemble_plan(
    *,
    goal: str,
    facts: dict,
    city: str,
    platforms: list[str],
    primary_queries: list[str],
    alternatives: list[dict],
    clarification_questions: list[str],
    conditional_filters: list[dict],
) -> dict:
    default_platform = "xianyu" if "xianyu" in platforms else platforms[0]
    search_rounds = []
    for index, query in enumerate(primary_queries, start=1):
        search_rounds.append(
            {
                "round": index,
                "platform": default_platform,
                "query": query,
                "filters": {},
                "purpose": "首轮或扩展搜索种子；执行后必须用 run-summary 检查质量。",
            }
        )
    for alternative in alternatives:
        candidate_key = _search_round_key(
            {
                "platform": default_platform,
                "query": alternative["query"],
                "filters": {},
            }
        )
        if any(_search_round_key(search) == candidate_key for search in search_rounds):
            continue
        search_rounds.append(
            {
                "round": len(search_rounds) + 1,
                "platform": default_platform,
                "query": alternative["query"],
                "filters": {},
                "purpose": alternative["reason"],
                "alternative": True,
            }
        )

    return {
        "goal": goal,
        "city": city,
        "platforms": platforms,
        "interpreted_intent": facts,
        "clarification_questions": clarification_questions,
        "search_rounds": search_rounds,
        "conditional_filters": conditional_filters,
        "quality_checks": [
            "是否有真实商品卡片，而不是配件、服务、回收或维修。",
            "价格和地区覆盖是否接近 100%。",
            "目标配置密度是否足够，例如型号、芯片、尺寸、内存、硬盘是否频繁出现。",
            "深滚动是否带来新增 URL；如果新增很少，优先换关键词而不是继续滚动。",
            "是否需要把相邻型号放进候选池，用于价格/性能横向比较。",
        ],
        "web_coverage_strategy": [
            "先保留一轮宽关键词、无价格过滤的搜索作为审计样本。",
            "如果宽搜索被配件、贴膜、盒子、维修或回收服务污染，优先让大模型估算保守价格下限并追加一轮价格筛选搜索。",
            "如果热门商品的网页结果明显偏少，可以追加一次小步数深滚动并比较新增 URL；若新增很少，优先换关键词、同义词、型号代号或相邻型号，而不是继续加深滚动。",
            "相邻型号只作为比较候选进入池子，是否推荐仍由大模型根据价格、证据和用户偏好判断。",
        ],
        "next_tool_sequence": [
            "spike-search",
            "run-summary",
            "candidate-pool",
            "prepare-evidence",
            "evaluation-task",
            "save-html-report",
        ],
    }


def _search_round_key(search: dict) -> tuple:
    return (
        search.get("platform"),
        search.get("query"),
        tuple(sorted((search.get("filters") or {}).items())),
    )


def _extract_years(text: str) -> list[int]:
    return [int(match) for match in re.findall(r"\b(20[0-3]\d)\b", text)]


def _extract_screen_sizes(text: str, *, family: str = "generic") -> list[int]:
    sizes = []
    lowered = text.lower()
    for match in re.findall(r"(?<!\d)(13|14|16|21(?:\.5)?|24|27)\s*(?:寸|英寸|吋|inch|in\b)", lowered):
        sizes.append(int(float(match)))
    if family in {"macbook", "imac"}:
        family_sizes = ("13", "14", "16") if family == "macbook" else ("21.5", "24", "27")
        for size in family_sizes:
            escaped_size = re.escape(size)
            if re.search(rf"(?<!\d){escaped_size}(?!\d)(?!\s*(?:g|gb|核|core))", lowered):
                sizes.append(int(float(size)))
    return _dedupe(sizes)


def _macbook_chip_terms(facts: dict) -> list[str]:
    chips = list(facts["chips"])
    specific_chips = [chip for chip in chips if " " in chip]
    base_chips = [
        chip
        for chip in chips
        if " " not in chip and not any(specific.startswith(f"{chip} ") for specific in specific_chips)
    ]
    if facts["subtype"] == "pro" and chips == ["M1"]:
        base_chips.append("M1 PRO")
    ordered = _dedupe(base_chips + specific_chips)
    return [_chip_display_name(chip) for chip in ordered]


def _chip_display_name(chip: str) -> str:
    parts = chip.upper().split()
    if len(parts) == 1:
        return parts[0]
    return " ".join([parts[0], *[part.title() for part in parts[1:]]])


def _macbook_query(
    target: str,
    *,
    chip: str | None = None,
    size: int | None = None,
    memory_gb: int | None = None,
    storage: str | None = None,
) -> str:
    parts = [target]
    if chip:
        parts.append(chip)
    if size:
        parts.append(f"{size}寸")
    if memory_gb:
        parts.append(f"{memory_gb}G")
    if storage:
        parts.append(storage)
    return " ".join(parts)


def _extract_capacity_gb(text: str, *, labels: tuple[str, ...]) -> int | None:
    lowered = text.lower()
    for label in labels:
        match = re.search(rf"{label}\s*(\d+)\s*(?:g|gb)", lowered)
        if match:
            return int(match.group(1))
    match = re.search(r"(?<!\d)(8|16|24|32|36|48|64|96|128)\s*(?:g|gb)\s*(?:内存|运存|ram|memory)?", lowered)
    if match:
        return int(match.group(1))
    return None


def _extract_storage(text: str) -> str | None:
    lowered = text.lower()
    match = re.search(r"(?<!\d)(256|512)\s*(?:g|gb)", lowered)
    if match:
        return f"{match.group(1)}G"
    match = re.search(r"(?<!\d)(1|2|4|8)\s*(?:t|tb)", lowered)
    if match:
        return f"{match.group(1)}T"
    return None


def _extract_city(text: str) -> str | None:
    for city in ("上海", "北京", "深圳", "广州", "杭州", "南京", "苏州", "成都", "武汉"):
        if city in text:
            return city
    return None


def _dedupe(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
