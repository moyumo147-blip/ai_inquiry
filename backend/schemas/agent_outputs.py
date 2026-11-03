# backend/schemas/agent_outputs.py
# Agent 的「结构化输出」Schema（LangChain with_structured_output 用）。

from typing import Literal

from pydantic import BaseModel, Field

Urgency = Literal["emergency", "urgent", "routine"]


class TriageOutput(BaseModel):
    """分诊结果。"""

    department: str = Field(description="建议就诊科室，如：心血管内科、急诊科、儿科")
    urgency: Urgency = Field(description="紧急程度：emergency 立即急诊 / urgent 24小时内 / routine 常规门诊")
    red_flags: list[str] = Field(default_factory=list, description="识别到的红旗症状（没有则空数组）")
    differential: list[str] = Field(default_factory=list, description="需要考虑的 2-4 个可能方向（不是确诊）")
    recommended_tests: list[str] = Field(default_factory=list, description="建议的检查项目")
    questions: list[str] = Field(default_factory=list, description="还需要向患者补充询问的问题，最多 3 个")
    advice: str = Field(description="给患者的下一步行动建议，2-3 句")
    rationale: str = Field(default="", description="分诊理由，简要说明依据")


class FollowupOutput(BaseModel):
    """问诊追问建议。"""

    questions: list[str] = Field(default_factory=list, description="最多 3 个最关键、最具体的追问")
    missing_info: list[str] = Field(default_factory=list, description="当前缺失的关键信息类别")


class SOAPOutput(BaseModel):
    """结构化门诊病历（SOAP）。"""

    chief_complaint: str = Field(description="主诉：症状 + 持续时间，一句话")
    present_illness: str = Field(description="现病史：起病时间、诱因、症状特点、伴随症状、诊疗经过")
    past_history: str = Field(default="未提供", description="既往史：慢性病、手术、用药")
    allergy_history: str = Field(default="未提供", description="过敏史")
    physical_exam: str = Field(default="未提供（线上问诊，无体格检查）", description="体格检查/生命体征")
    assessment: str = Field(description="初步评估：最可能的方向 + 鉴别考虑（注明不是确诊）")
    plan: str = Field(description="诊疗计划：建议就诊科室、检查、生活方式、复诊指征")
    diagnosis: str = Field(default="待明确", description="初步诊断名称（不确定写待明确）")
    summary: str = Field(default="", description="一句话病情摘要，用于会话列表展示")
