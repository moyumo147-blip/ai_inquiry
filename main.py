import os
import re
import json
import hashlib
import psycopg2
from psycopg2.extras import Json
from openai import OpenAI

# ================= 配置区 =================
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "123456",  # ⚠️ 请务必替换为你真实的数据库密码
    "host": "localhost",
    "port": "5432"
}

# 读取系统环境变量 (已重启 PyCharm，应该能正常读取)
DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY")

if not DASHSCOPE_KEY:
    print("❌ 错误: 依然没有读取到环境变量 DASH_SCOPE_API_KEY！")
    print("请检查：1. 系统环境变量名是否完全一致；2. 是否彻底重启了 PyCharm。")
    exit()

# 初始化阿里云百炼客户端 (用于生成向量)
embed_client = OpenAI(
    api_key=DASHSCOPE_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# ⚠️ 将所有 txt 文件放在这个文件夹下（若没有该文件夹，代码会自动创建）
DATA_DIR = "./medical_data"


# ================= 数据库连接 =================
def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


# ================= 文本解析逻辑 =================
def parse_record(raw_text):
    """解析单条病例文本"""
    if not raw_text.strip(): return None

    # 1. 提取 URL
    url_match = re.search(r'(https?://[^\s]+)', raw_text)
    if not url_match: return None
    source_url = url_match.group(1).strip()

    # 2. 提取科室 (Doctor faculty)
    doctor_faculty = ""
    faculty_match = re.search(r'Doctor faculty\s*\n(.*?)\n', raw_text, re.DOTALL)
    if faculty_match:
        doctor_faculty = faculty_match.group(1).strip()

    hospital = doctor_faculty.split()[0] if doctor_faculty else "未知医院"
    department = " ".join(doctor_faculty.split()[1:]) if len(doctor_faculty.split()) > 1 else "未知科室"

    # 3. 提取疾病
    disease = ""
    disease_match = re.search(r'疾病：\s*\n?(.*?)\n', raw_text)
    if disease_match:
        disease = disease_match.group(1).strip()

    # 4. 提取对话 (Dialogue)
    dialogue = []
    dialogue_section = raw_text.split("Dialogue")
    if len(dialogue_section) > 1:
        dialog_text = dialogue_section[1].strip()
        turns = re.split(r'\n(?=医生：|病人：)', "\n" + dialog_text)
        for turn in turns:
            if turn.startswith("医生："):
                dialogue.append({"role": "doctor", "content": turn.replace("医生：", "").strip()})
            elif turn.startswith("病人："):
                dialogue.append({"role": "patient", "content": turn.replace("病人：", "").strip()})

    # 5. 提取其他描述字段
    patient_desc = ""
    match_desc = re.search(r'病情描述.*?：\s*\n?(.*?)(?=曾经治疗|想得到|Dialogue)', raw_text, re.DOTALL)
    if match_desc: patient_desc = match_desc.group(1).strip()

    help_wanted = ""
    match_help = re.search(r'想得到怎样的帮助：\s*\n?(.*?)(?=Dialogue)', raw_text, re.DOTALL)
    if match_help: help_wanted = match_help.group(1).strip()

    return {
        "source_url": source_url,
        "hospital": hospital,
        "department": department,
        "doctor_faculty_raw": doctor_faculty,
        "disease": disease,
        "patient_description": patient_desc,
        "help_wanted": help_wanted,
        "dialogue": dialogue,
        "raw_text": raw_text
    }


# ================= 核心入库逻辑 =================
def insert_case_to_db(conn, data, filename):
    with conn.cursor() as cur:
        content_hash = hashlib.sha256(data["raw_text"].encode('utf-8')).hexdigest()

        # 1. 插入主表 (忽略重复 URL)
        insert_case_sql = """
                          INSERT INTO medical_cases
                          (source_file, source_url, hospital, department, doctor_faculty_raw, disease, \
                           patient_description, help_wanted, dialogue, content_hash)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source_url) DO NOTHING
            RETURNING id; \
                          """
        cur.execute(insert_case_sql, (
            filename, data["source_url"], data["hospital"], data["department"],
            data["doctor_faculty_raw"], data["disease"], data["patient_description"],
            data["help_wanted"], Json(data["dialogue"]), content_hash
        ))

        result = cur.fetchone()
        if not result:
            return "duplicate"

        case_id = result[0]

        # 2. 拆分 QA 对入表
        turn_no = 1
        for i in range(len(data["dialogue"])):
            if data["dialogue"][i]["role"] == "patient":
                q = data["dialogue"][i]["content"]
                a = ""
                if i + 1 < len(data["dialogue"]) and data["dialogue"][i + 1]["role"] == "doctor":
                    a = data["dialogue"][i + 1]["content"]

                if a:
                    cur.execute("""
                                INSERT INTO qa_pairs (case_id, turn_no, patient_question, doctor_answer)
                                VALUES (%s, %s, %s, %s)
                                """, (case_id, turn_no, q, a))
                    turn_no += 1

        # 3. 生成 Chunk 及 向量 (Embedding)
        chunk_text = f"医院:{data['hospital']} 科室:{data['department']}。疾病:{data['disease']}。病情:{data['patient_description']}。患者诉求:{data['help_wanted']}"

        # 计算 chunk 的 hash (解决刚才的报错)
        chunk_hash = hashlib.sha256(chunk_text.encode('utf-8')).hexdigest()

        try:
            # 调用 text-embedding-v2 生成 1536 维向量
            response = embed_client.embeddings.create(
                input=chunk_text,
                model="text-embedding-v2"
            )
            embedding = response.data[0].embedding

            # 插入向量表，带上 content_hash
            cur.execute("""
                        INSERT INTO case_chunks (case_id, chunk_type, chunk_index, chunk_text, embedding, content_hash)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """, (case_id, 'summary', 0, chunk_text, embedding, chunk_hash))
        except Exception as e:
            print(f"  [!] 向量生成或插入失败: {e}")
            raise e

    conn.commit()
    return "success"


# ================= 主程序 =================
def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"📁 创建了数据文件夹: {DATA_DIR}，请将 txt 文件放入该目录后重新运行。")
        return

    conn = get_db_connection()
    stats = {"files": 0, "total_records": 0, "success": 0, "duplicate": 0, "error": 0}

    for root, dirs, files in os.walk(DATA_DIR):
        for filename in files:
            if not filename.endswith(".txt") or filename.startswith("._"):
                continue

            stats["files"] += 1
            filepath = os.path.join(root, filename)
            print(f"\n📄 [{stats['files']}] 正在处理文件: {filepath}")

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"  [!] 读取文件失败: {e}")
                continue

            records = re.split(r'\nid=\d+\n', content)

            for raw_record in records:
                if not raw_record.strip(): continue
                stats["total_records"] += 1

                parsed_data = parse_record(raw_record)
                if parsed_data:
                    try:
                        res = insert_case_to_db(conn, parsed_data, filename)
                        if res == "success":
                            stats["success"] += 1
                            if stats["success"] % 10 == 0:
                                print(f"  ... 已成功入库 {stats['success']} 条")
                        elif res == "duplicate":
                            stats["duplicate"] += 1
                    except Exception as e:
                        conn.rollback()
                        stats["error"] += 1
                        # 过滤掉重复的报错信息，只打印第一条
                        if stats["error"] == 1:
                            print(f"  [!] 入库失败 (可能由于某些字段过长或格式异常): {e}")
                else:
                    stats["error"] += 1

    conn.close()
    print("\n" + "=" * 40)
    print("🎉 全部文件处理完毕！统计结果：")
    print(f"  - 扫描文件数: {stats['files']}")
    print(f"  - 解析总记录: {stats['total_records']}")
    print(f"  - 成功入库数: {stats['success']}")
    print(f"  - 重复跳过数: {stats['duplicate']}")
    print(f"  - 异常失败数: {stats['error']}")
    print("=" * 40)


if __name__ == "__main__":
    main()