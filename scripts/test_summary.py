# scripts/test_summary.py
# 长会话摘要链路验证：连续问 6 轮（12 条消息）→ 触发摘要压缩 → 校验 summary / 水位 / 后续对话仍可用。
#
# 前置：后端已启动（默认 http://127.0.0.1:8000）。
# 用法：python scripts/test_summary.py

import random
import string
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
API = "/api/v1"

QUESTIONS = [
    "孩子这种情况一般从几岁开始出现？",
    "需要先做哪些检查？",
    "平时写作业拖拉有什么办法改善？",
    "饮食上要注意什么？",
    "需要吃药吗？",
    "多久复查一次比较合适？",
    "学校和老师那边需要怎么配合？",
]


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=180)

    username = "sum_" + "".join(random.choices(string.ascii_lowercase, k=6))
    r = client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "demo123456", "display_name": "摘要测试"},
    )
    if r.status_code != 201:
        print("注册失败：", r.status_code, r.text[:200])
        return 1
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post(
        f"{API}/sessions",
        json={"chief_complaint": "孩子8岁，上课坐不住、注意力不集中，写作业拖拉，怀疑多动症"},
        headers=headers,
    )
    session_id = r.json()["session"]["id"]
    print(f"会话：{session_id}")

    t0 = time.time()
    for i, question in enumerate(QUESTIONS[:6], 1):
        started = time.time()
        r = client.post(f"{API}/chat", json={"session_id": session_id, "message": question}, headers=headers)
        ok = r.status_code == 200
        print(f"  第 {i} 轮 {'OK' if ok else 'FAIL'}  {time.time() - started:5.1f}s  {question}")
        if not ok:
            print("   ", r.status_code, r.text[:300])
            return 1

    detail = client.get(f"{API}/sessions/{session_id}", headers=headers).json()
    session = detail["session"]
    summary = session.get("summary") or ""

    print("\n── 校验 ──")
    checks = [
        ("消息数 ≥ 12", (session.get("message_count") or 0) >= 12),
        ("已生成摘要", bool(summary.strip())),
        ("摘要长度合理（30-1200）", 30 <= len(summary) <= 1200),
        ("摘要包含病情关键信息", any(k in summary for k in ("注意力", "多动", "8岁", "写作业"))),
    ]
    for name, ok in checks:
        print(f"{'✅' if ok else '❌'} {name}")

    print("\n摘要内容：\n" + summary)

    # 摘要之后继续问一轮，确认上下文仍可用
    started = time.time()
    r = client.post(
        f"{API}/chat",
        json={"session_id": session_id, "message": "刚才说的检查项目能再具体一点吗？"},
        headers=headers,
    )
    ok = r.status_code == 200 and len(r.json().get("answer") or "") > 20
    print(f"\n{'✅' if ok else '❌'} 摘要后继续问诊（{time.time() - started:.1f}s）")

    detail2 = client.get(f"{API}/sessions/{session_id}", headers=headers).json()
    print(f"   → 当前消息数 {detail2['session'].get('message_count')}，"
          f"摘要长度 {len(detail2['session'].get('summary') or '')}")

    print(f"\n总耗时 {time.time() - t0:.1f}s")
    return 0 if all(ok for _, ok in checks) and ok else 1


if __name__ == "__main__":
    sys.exit(main())
