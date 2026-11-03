# scripts/smoke_test.py
# 端到端冒烟测试：健康检查 → 注册/登录 → 分诊建会话 → 问诊（普通 + SSE）→ 病历 → 病例库。
# 用法（后端已启动）：
#   python scripts/smoke_test.py
#   python scripts/smoke_test.py --base http://127.0.0.1:8000

import argparse
import json
import random
import string
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
API = "/api/v1"

PASS, FAIL = "✅", "❌"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL} {name}" + (f"  {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    client = httpx.Client(base_url=BASE, timeout=180)

    # ① 健康检查
    r = client.get("/health")
    check("健康检查", r.status_code == 200 and r.json().get("status") == "ok", str(r.status_code))

    # ② 注册（随机用户名，避免重复）
    username = "demo_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    r = client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "demo123456", "display_name": "冒烟测试用户", "age": 34, "gender": "female"},
    )
    check("注册", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get(f"{API}/auth/me", headers=headers)
    check("当前用户", r.status_code == 200 and r.json()["username"] == username)

    # ③ 建会话（带主诉 → 自动分诊）
    complaint = "孩子8岁，上课坐不住、注意力不集中，写作业拖拉，怀疑多动症"
    r = client.post(f"{API}/sessions", json={"chief_complaint": complaint}, headers=headers)
    check("新建会话 + 自动分诊", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    detail = r.json()
    session_id = detail["session"]["id"]
    triage = detail.get("triage") or {}
    print(f"   → 科室={triage.get('department')} 紧急度={triage.get('urgency')} 红旗={triage.get('red_flags')}")
    check("分诊返回科室", bool(triage.get("department")))
    check("开场白已写入", len(detail.get("messages") or []) == 1)

    # ④ 问诊（非流式）
    t0 = time.time()
    r = client.post(
        f"{API}/chat",
        json={"session_id": session_id, "message": "需要做哪些检查才能确诊？平时饮食要注意什么？"},
        headers=headers,
    )
    elapsed = time.time() - t0
    check("问诊（非流式）", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    chat = r.json()
    print(
        f"   → mode={chat.get('answer_mode')} 命中病例={len(chat.get('citations') or [])} "
        f"追问={len(chat.get('followups') or [])} 置信度={chat.get('confidence')} 用时={elapsed:.1f}s"
    )
    check("回答非空", len(chat.get("answer") or "") > 30)
    check("有引用病例", len(chat.get("citations") or []) > 0)
    check("回答带免责声明", "不能替代" in (chat.get("disclaimer") or ""))

    # ⑤ 问诊（SSE 流式）
    tokens = 0
    meta = {}
    got_done = False
    with client.stream(
        "POST",
        f"{API}/chat/stream",
        json={"session_id": session_id, "message": "在家里可以做哪些训练帮助他集中注意力？"},
        headers=headers,
    ) as resp:
        check("问诊（SSE）HTTP", resp.status_code == 200, str(resp.status_code))
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "token":
                tokens += 1
            elif event.get("type") == "meta":
                meta = event
            elif event.get("type") == "done":
                got_done = True
    check("SSE 收到 token", tokens > 5, f"tokens={tokens}")
    check("SSE 收到 meta", bool(meta), f"mode={meta.get('answer_mode')}")
    check("SSE 正常结束", got_done)

    # ⑥ 生成病历
    r = client.post(f"{API}/records/generate", json={"session_id": session_id}, headers=headers)
    check("生成病历", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    record = r.json() if r.status_code == 200 else {}
    print(f"   → 主诉={(record.get('chief_complaint') or '')[:40]} 初步诊断={record.get('diagnosis')}")
    check("病历有主诉", bool(record.get("chief_complaint")))
    check("病历有诊疗计划", bool(record.get("plan")))

    # ⑦ 会话 / 病历列表
    r = client.get(f"{API}/sessions", headers=headers)
    check("会话列表", r.status_code == 200 and len(r.json()) >= 1)
    r = client.get(f"{API}/records", headers=headers)
    check("病历列表", r.status_code == 200 and len(r.json()) >= 1)

    # ⑧ 病例库
    r = client.get(f"{API}/cases", params={"keyword": "多动症", "page_size": 3}, headers=headers)
    check("病例库关键词检索", r.status_code == 200 and r.json().get("total", 0) > 0, f"total={r.json().get('total')}")
    r = client.get(f"{API}/cases/semantic", params={"q": "孩子注意力不集中", "top_k": 3}, headers=headers)
    ok = r.status_code == 200 and len(r.json().get("cases") or []) > 0
    check("病例库语义检索", ok, f"confidence={r.json().get('confidence') if r.status_code==200 else '-'}")

    # ⑨ 统计
    r = client.get(f"{API}/system/stats", headers=headers)
    check("统计接口", r.status_code == 200, f"{r.status_code}")
    if r.status_code == 200:
        s = r.json()
        print(f"   → 病例={s.get('cases')} 问答={s.get('qa_pairs')} 用户={s.get('users')} 会话={s.get('sessions')}")

    # ⑩ 安全护栏：急诊场景
    r = client.post(f"{API}/sessions", json={"chief_complaint": "胸痛2小时，伴大汗和左肩放射痛"}, headers=headers)
    if r.status_code == 201:
        d = r.json()
        check(
            "急诊分诊（红旗症状）",
            (d.get("triage") or {}).get("urgency") == "emergency",
            str((d.get("triage") or {}).get("urgency")),
        )
        emergency_session = d["session"]["id"]
        r2 = client.post(
            f"{API}/chat",
            json={"session_id": emergency_session, "message": "现在该怎么办？"},
            headers=headers,
        )
        check("急诊对话走固定话术", r2.status_code == 200 and r2.json().get("answer_mode") == "emergency")

    print()
    if failures:
        print(f"❌ 失败 {len(failures)} 项：" + "、".join(failures))
        return 1
    print("🎉 全部冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
