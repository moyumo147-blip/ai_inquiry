# backend/core/safety.py
# 医疗安全护栏（本项目最重要的一层）：红旗症状识别 + 分级 + 强制免责声明。
# 规则先行（便宜、可解释、不会被模型幻觉绕过），LLM 只做补充说明。

import re
from dataclasses import dataclass, field

DISCLAIMER = (
    "以上内容由 AI 基于公开病例知识库生成，仅供健康科普与就医参考，"
    "不能替代执业医师的面诊、检查与处方。请勿据此自行用药；"
    "如症状加重或出现紧急情况，请立即前往急诊或拨打 120。"
)

EMERGENCY_ADVICE = (
    "您描述的情况包含可能危及生命的警示信号，请**立即拨打 120 或前往最近医院急诊**，"
    "不要等待线上回复、不要自行驾车、不要先吃药观察。"
)

URGENT_ADVICE = (
    "建议您在 24 小时内前往医院就诊（必要时急诊），"
    "就诊前注意休息、补充水分，避免自行使用抗生素或止痛药掩盖症状。"
)

ROUTINE_ADVICE = "建议规律作息、观察症状变化；若持续不缓解或加重，请及时到相应科室就诊。"

# (级别, 标签, 正则)。级别：emergency 立即急诊 / urgent 24h 内就诊
_RULES: list[tuple[str, str, str]] = [
    # ── 立即急诊 ──────────────────────────────────────────────
    ("emergency", "呼吸困难", r"(呼吸困难|喘不上气|喘不过气|窒息|口唇发紫|嘴唇发紫|呼吸急促)"),
    ("emergency", "意识障碍", r"(意识模糊|意识不清|昏迷|晕厥|晕倒|人事不省|呼之不应|抽搐|惊厥)"),
    ("emergency", "胸痛", r"(胸痛|胸口.{0,3}(痛|闷|压)|心前区.{0,3}(痛|闷)|压榨样)"),
    ("emergency", "大出血", r"(大出血|呕血|咯血|喷血|血便|黑便|产后出血|阴道大量出血)"),
    ("emergency", "剧烈头痛", r"(炸裂样头痛|雷击样头痛|剧烈头痛|一生中最痛的头痛)"),
    ("emergency", "自伤风险", r"(自杀|轻生|不想活|活不下去|自残)"),
    ("emergency", "中毒/误服", r"(中毒|误服|农药|喝了.{0,4}药|过量服药)"),
    ("emergency", "孕产急症", r"(胎动.{0,4}(减少|消失)|破水|羊水|孕.{0,6}(出血|剧烈腹痛))"),
    ("emergency", "儿童急症", r"((婴儿|新生儿|宝宝|孩子).{0,6}(抽搐|惊厥|呼吸困难|口唇发紫|精神差|叫不醒))"),
    ("emergency", "严重过敏", r"(喉头水肿|(喉咙|喉头).{0,4}(发紧|紧缩|肿)|全身荨麻疹.{0,6}呼吸|过敏性休克|休克)"),

    # ── 24 小时内就诊 ─────────────────────────────────────────
    ("urgent", "持续高热", r"(高热|高烧|39度|40度|体温.{0,3}(39|40))"),
    ("urgent", "剧烈腹痛", r"(剧烈腹痛|腹痛难忍|肚子剧痛|急腹症|(肚子|腹).{0,6}(疼|痛).{0,8}(直不起腰|打滚|难忍|冒冷汗))"),
    ("urgent", "频繁吐泻", r"(频繁呕吐|呕吐不止|喷射性呕吐|腹泻.{0,6}(十几次|脱水)|脱水)"),
    ("urgent", "出血", r"(血尿|尿血|便血|痰中带血|鼻出血不止|伤口出血不止|(小便|尿).{0,6}(带血|有血))"),
    ("urgent", "黄疸", r"(黄疸|眼睛发黄|皮肤发黄|小便像浓茶)"),
    ("urgent", "体重骤降", r"(体重.{0,4}(下降|掉了|减轻).{0,6}(斤|公斤|kg)|消瘦明显)"),
    ("urgent", "持续咳嗽", r"(咳嗽.{0,6}(两周|2周|一个月|3周)|久咳不愈)"),
    ("urgent", "视力骤降", r"(视力.{0,4}(突然|骤降|下降)|突然看不见|眼前黑影)"),
    ("urgent", "外伤", r"(骨折|外伤|摔伤|扭伤.{0,6}肿|头部外伤|撞击)"),
    ("urgent", "精神症状", r"(幻觉|妄想|极度焦虑|惊恐发作)"),
]

_NEGATIONS = ("不", "无", "没有", "未", "否认", "无明显", "不曾")

_LEVEL_ORDER = {"routine": 0, "urgent": 1, "emergency": 2}


@dataclass
class SafetyAssessment:
    level: str = "routine"              # routine / urgent / emergency
    flags: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    advice: str = ROUTINE_ADVICE

    @property
    def is_emergency(self) -> bool:
        return self.level == "emergency"

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "flags": self.flags,
            "matched": self.matched,
            "advice": self.advice,
            "disclaimer": DISCLAIMER,
        }


def _is_negated(text: str, start: int) -> bool:
    """粗略判断关键词前 4 个字内是否出现否定词（“没有胸痛”不应触发急诊）。"""
    window = text[max(0, start - 4) : start]
    return any(neg in window for neg in _NEGATIONS)


def assess(text: str) -> SafetyAssessment:
    """对用户描述做红旗症状扫描。"""
    text = text or ""
    result = SafetyAssessment()
    best = "routine"

    for level, label, pattern in _RULES:
        for match in re.finditer(pattern, text):
            if _is_negated(text, match.start()):
                continue
            if label not in result.flags:
                result.flags.append(label)
                result.matched.append(match.group(0))
            if _LEVEL_ORDER[level] > _LEVEL_ORDER[best]:
                best = level
            break  # 同一规则命中一次即可

    # 组合规则：胸痛 + 出汗/放射痛 → 升级为急诊（更贴近心梗表现）
    if best != "emergency" and re.search(r"(胸|心前区).{0,6}(痛|闷)", text) and re.search(
        r"(大汗|冷汗|出汗|放射|左肩|左臂|濒死感)", text
    ):
        best = "emergency"
        if "胸痛伴冷汗" not in result.flags:
            result.flags.append("胸痛伴冷汗")

    result.level = best
    result.advice = {
        "emergency": EMERGENCY_ADVICE,
        "urgent": URGENT_ADVICE,
        "routine": ROUTINE_ADVICE,
    }[best]
    return result


def emergency_answer(assessment: SafetyAssessment) -> str:
    """急诊场景的标准回复（不经过大模型，确保稳定、不被改写）。"""
    flags = "、".join(assessment.flags) if assessment.flags else "危及生命的警示症状"
    return (
        f"⚠️ **请立即就医**\n\n"
        f"您描述中出现了「{flags}」，属于需要紧急处理的情况。\n\n"
        f"{EMERGENCY_ADVICE}\n\n"
        f"在等待或前往医院途中：保持安静、不要独处、不要进食大量食物或自行服药；"
        f"如已知有既往病史（心脏病、癫痫、糖尿病等），请让家属告知接诊医生。\n\n"
        f"> {DISCLAIMER}"
    )
