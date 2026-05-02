import streamlit as st
import sqlite3
import pandas as pd
import cv2
import numpy as np
import re
from datetime import datetime, date
import io
import hashlib
import requests
import json

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Aura ERP Pro", page_icon="📊", layout="wide")

DB_NAME = "aura_erp.db"
CURRENT_DB_VERSION = 4

# =========================
# STYLE
# =========================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Cairo', sans-serif; direction: rtl; }
.stApp { background-color: #f7f8fa; }
h1 { text-align:center; color:#0B6B3A; font-weight:800; }
h2,h3 { color:#111827; font-weight:700; }
.stButton>button,.stFormSubmitButton>button {
    background:#0B6B3A; color:white; border-radius:10px; border:none;
    font-weight:700; width:100%; height:42px;
}
.stTextInput input, .stTextArea textarea { text-align:right; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# =========================
# DATABASE
# =========================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS db_version (
            id INTEGER PRIMARY KEY,
            version INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            outlet_name TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_date TEXT,
            national_id TEXT,
            name TEXT,
            address TEXT,
            phone TEXT,
            network TEXT,
            sale_place TEXT,
            seller_name TEXT,
            extra_services TEXT,
            line_status TEXT,
            activation_status TEXT,
            api_status TEXT,
            api_message TEXT,
            due_amount REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            payment_status TEXT,
            due_date TEXT,
            last_reminder_date TEXT,
            reminder_count INTEGER DEFAULT 0,
            ai_confidence TEXT,
            notes TEXT,
            created_by TEXT
        )
    """)

    conn.commit()
    return conn

conn = init_db()

def add_column_if_not_exists(table, column, col_type):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()

def migrate_db():
    cur = conn.cursor()
    cur.execute("SELECT version FROM db_version WHERE id=1")
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO db_version (id, version) VALUES (1, 1)")
        conn.commit()

    customer_cols = [
        ("created_date", "TEXT"),
        ("sale_place", "TEXT"),
        ("seller_name", "TEXT"),
        ("extra_services", "TEXT"),
        ("line_status", "TEXT"),
        ("activation_status", "TEXT"),
        ("api_status", "TEXT"),
        ("api_message", "TEXT"),
        ("due_amount", "REAL DEFAULT 0"),
        ("paid_amount", "REAL DEFAULT 0"),
        ("payment_status", "TEXT"),
        ("due_date", "TEXT"),
        ("last_reminder_date", "TEXT"),
        ("reminder_count", "INTEGER DEFAULT 0"),
        ("ai_confidence", "TEXT"),
        ("notes", "TEXT"),
        ("created_by", "TEXT"),
    ]

    for col, typ in customer_cols:
        add_column_if_not_exists("customers", col, typ)

    add_column_if_not_exists("users", "outlet_name", "TEXT")
    add_column_if_not_exists("users", "created_at", "TEXT")

    cur.execute("UPDATE db_version SET version=? WHERE id=1", (CURRENT_DB_VERSION,))
    conn.commit()

migrate_db()

def create_default_admin():
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE username='admin'")
    if cur.fetchone() is None:
        cur.execute("""
            INSERT INTO users (username,password,role,outlet_name,created_at)
            VALUES (?,?,?,?,?)
        """, (
            "admin",
            hash_password("admin123"),
            "admin",
            "الإدارة",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()

create_default_admin()

# =========================
# OCR - PADDLEOCR
# =========================
@st.cache_resource
def load_paddle_ocr():
    from paddleocr import PaddleOCR
    return PaddleOCR(
        use_angle_cls=True,
        lang="ar",
        use_gpu=False,
        show_log=False
    )

def normalize_digits(text):
    if not text:
        return ""
    ar = "٠١٢٣٤٥٦٧٨٩"
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i in range(10):
        text = text.replace(ar[i], str(i)).replace(fa[i], str(i))
    return text

def clean_arabic_text(text):
    if not text:
        return ""
    text = normalize_digits(text)
    bad = [
        "جمهورية", "مصر", "العربية", "بطاقة", "تحقيق", "الشخصية",
        "الاسم", "العنوان", "ذكر", "انثى", "أنثى", "مسلم", "مسيحي",
        "تاريخ", "الميلاد"
    ]
    for w in bad:
        text = text.replace(w, " ")
    text = re.sub(r"[^\u0600-\u06FF\s\d\-\/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def preprocess_image(img):
    img = cv2.resize(img, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    return gray

def extract_national_id(text):
    text = normalize_digits(text)
    text = text.replace(" ", "").replace("-", "").replace("/", "").replace(".", "")
    matches = re.findall(r"[23]\d{13}", text)
    return matches[0] if matches else ""

def local_name_fix(name):
    fixes = {
        "علاءالدين": "علاء الدين",
        "سيداحمد": "سيد احمد",
        "احمدمحمد": "احمد محمد",
        "عبدالله": "عبد الله",
        "عبدالرحمن": "عبد الرحمن",
        "عبدالعزيز": "عبد العزيز",
        "ابوالعلا": "ابو العلا",
    }
    name = clean_arabic_text(name)
    for wrong, right in fixes.items():
        name = name.replace(wrong, right)
    return name.strip()

def ai_correct_identity(raw_text, name, address, national_id):
    """
    AI correction اختياري.
    لو مفيش OPENAI_API_KEY، يرجع التصحيح المحلي بدون كراش.
    """
    api_key = st.secrets.get("OPENAI_API_KEY", "")

    if not api_key:
        return {
            "name": local_name_fix(name),
            "address": address,
            "national_id": national_id,
            "confidence": "Local correction only"
        }

    try:
        payload = {
            "model": "gpt-4.1-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "Extract and correct Egyptian national ID card data. Return strict JSON only."
                },
                {
                    "role": "user",
                    "content": f"""
Raw OCR:
{raw_text}

Current extraction:
name: {name}
address: {address}
national_id: {national_id}

Return JSON:
{{
"name": "",
"address": "",
"national_id": "",
"confidence": ""
}}
"""
                }
            ],
            "temperature": 0
        }

        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=20
        )

        data = res.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        return {
            "name": parsed.get("name", name),
            "address": parsed.get("address", address),
            "national_id": parsed.get("national_id", national_id),
            "confidence": parsed.get("confidence", "AI corrected")
        }

    except Exception as e:
        return {
            "name": local_name_fix(name),
            "address": address,
            "national_id": national_id,
            "confidence": f"AI failed - local used: {e}"
        }

def ocr_card(img):
    ocr = load_paddle_ocr()
    processed = preprocess_image(img)
    result = ocr.ocr(processed, cls=True)

    texts = []
    if result:
        for block in result:
            if block:
                for line in block:
                    try:
                        texts.append(line[1][0])
                    except:
                        pass

    raw_text = " ".join(texts)
    cleaned = clean_arabic_text(raw_text)
    nid = extract_national_id(cleaned)

    text_wo_nid = cleaned.replace(nid, "")
    words = text_wo_nid.split()

    name = " ".join(words[:5])
    address = " ".join(words[5:])

    corrected = ai_correct_identity(raw_text, name, address, nid)

    return (
        corrected["name"],
        corrected["national_id"],
        corrected["address"],
        corrected["confidence"],
        raw_text
    )

# =========================
# e& API READY
# =========================
def eand_api_request(endpoint, payload):
    base_url = st.secrets.get("EAND_API_BASE_URL", "")
    token = st.secrets.get("EAND_API_TOKEN", "")

    if not base_url or not token:
        return {
            "status": "Simulation",
            "message": "لا يوجد API رسمي مضاف. تم تشغيل الوضع التجريبي."
        }

    try:
        url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        res = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=25
        )

        if res.status_code in [200, 201]:
            return {"status": "Success", "message": res.text[:300]}

        return {"status": "Failed", "message": f"{res.status_code}: {res.text[:300]}"}

    except Exception as e:
        return {"status": "Error", "message": str(e)}

def link_line_api(phone, national_id, customer_name, network):
    payload = {
        "phone": phone,
        "national_id": national_id,
        "customer_name": customer_name,
        "network": network
    }
    return eand_api_request("/lines/link-customer", payload)

def check_line_status_api(phone):
    payload = {"phone": phone}
    return eand_api_request("/lines/status", payload)

# =========================
# HELPERS
# =========================
def login(username, password):
    cur = conn.cursor()
    cur.execute("""
        SELECT username, role, outlet_name FROM users
        WHERE username=? AND password=?
    """, (username, hash_password(password)))
    return cur.fetchone()

def read_customers():
    try:
        return pd.read_sql_query("SELECT * FROM customers ORDER BY id DESC", conn)
    except:
        return pd.DataFrame()

def rename_df(df):
    return df.rename(columns={
        "id": "ID",
        "created_date": "تاريخ التسجيل",
        "national_id": "الرقم القومي",
        "name": "اسم العميل",
        "address": "العنوان",
        "phone": "رقم المحمول",
        "network": "الشبكة",
        "sale_place": "مكان البيع",
        "seller_name": "اسم البائع",
        "extra_services": "الخدمات",
        "line_status": "حالة الخط",
        "activation_status": "حالة الربط",
        "api_status": "حالة API",
        "api_message": "رسالة API",
        "due_amount": "المستحق",
        "paid_amount": "المدفوع",
        "payment_status": "حالة التحصيل",
        "due_date": "تاريخ الاستحقاق",
        "last_reminder_date": "آخر تنبيه",
        "reminder_count": "عدد التنبيهات",
        "ai_confidence": "ثقة AI/OCR",
        "notes": "ملاحظات",
        "created_by": "تم بواسطة"
    })

def export_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="customers")
        ws = writer.sheets["customers"]
        for col in ws.columns:
            max_len = 0
            letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[letter].width = max_len + 4
    output.seek(0)
    return output

def payment_status(due, paid):
    due = float(due or 0)
    paid = float(paid or 0)
    if due <= 0:
        return "لا يوجد مستحق"
    if paid >= due:
        return "مدفوع بالكامل"
    if paid > 0:
        return "مدفوع جزئي"
    return "متأخر / غير مدفوع"

def build_reminder_message(name, phone, due_amount, due_date):
    return f"""عميلنا العزيز/ {name}
نحيط حضرتك علمًا بوجود مبلغ مستحق بقيمة {due_amount} جنيه على رقم {phone}
تاريخ الاستحقاق: {due_date}
برجاء السداد في أقرب وقت لتجنب إيقاف الخدمة.
شركة اتصالات تليكوم"""

# =========================
# SESSION
# =========================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = {}
if "fields" not in st.session_state:
    st.session_state.fields = {"name": "", "nid": "", "addr": "", "confidence": "", "raw": ""}

# =========================
# LOGIN
# =========================
if not st.session_state.logged_in:
    st.title("📊 Aura ERP Pro - Login")

    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        username_input = st.text_input("اسم المستخدم")
        password_input = st.text_input("كلمة المرور", type="password")

        if st.button("دخول"):
            user = login(username_input, password_input)
            if user:
                st.session_state.logged_in = True
                st.session_state.user = {
                    "username": user[0],
                    "role": user[1],
                    "outlet_name": user[2]
                }
                st.rerun()
            else:
                st.error("بيانات الدخول غير صحيحة")

        st.info("الدخول الافتراضي: admin / admin123")

    st.stop()

# =========================
# HEADER
# =========================
st.title("📊 Aura ERP Pro - النظام المتكامل")

username = st.session_state.user["username"]
user_role = st.session_state.user["role"]
outlet_name = st.session_state.user["outlet_name"]

a, b, c = st.columns([2,2,1])
a.info(f"المستخدم: {username}")
b.info(f"الصلاحية: {user_role} | الفرع: {outlet_name}")
with c:
    if st.button("تسجيل خروج"):
        st.session_state.logged_in = False
        st.session_state.user = {}
        st.rerun()

if user_role == "admin":
    menu = st.sidebar.radio("القائمة", [
        "تسجيل عميل وخط",
        "CRM Dashboard",
        "تقارير التحصيل",
        "تنبيهات العملاء",
        "جدول العملاء",
        "إدارة المستخدمين",
        "إعدادات النظام"
    ])
else:
    menu = st.sidebar.radio("القائمة", [
        "تسجيل عميل وخط",
        "CRM Dashboard",
        "تقارير التحصيل",
        "تنبيهات العملاء",
        "جدول العملاء"
    ])

# =========================
# REGISTER
# =========================
if menu == "تسجيل عميل وخط":
    col1, col2 = st.columns([1,1], gap="large")

    with col1:
        st.subheader("📸 مسح بطاقة العميل")
        uploaded_file = st.file_uploader("ارفع صورة البطاقة", type=["jpg","jpeg","png"])

        if uploaded_file:
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, 1)

            st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), caption="البطاقة المرفوعة", use_container_width=True)

            if st.button("🚀 OCR + AI تحليل البطاقة"):
                with st.spinner("جاري قراءة البطاقة وتصحيح البيانات..."):
                    try:
                        name, nid, address, confidence, raw = ocr_card(img)
                        st.session_state.fields = {
                            "name": name,
                            "nid": nid,
                            "addr": address,
                            "confidence": confidence,
                            "raw": raw
                        }
                        st.success("تم التحليل. راجعي البيانات قبل الحفظ.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"فشل OCR: {e}")

        if st.session_state.fields.get("raw"):
            with st.expander("RAW OCR للمراجعة"):
                st.write(st.session_state.fields["raw"])

    with col2:
        st.subheader("📝 تسجيل بيانات العميل والخط")

        with st.form("customer_form"):
            created_date = st.text_input("تاريخ اليوم", value=datetime.today().strftime("%Y-%m-%d"))
            name = st.text_input("اسم العميل بالكامل", value=st.session_state.fields["name"])
            nid = st.text_input("الرقم القومي 14 رقم", value=st.session_state.fields["nid"])
            address = st.text_input("العنوان بالكامل", value=st.session_state.fields["addr"])
            ai_confidence = st.text_input("ثقة AI/OCR", value=st.session_state.fields["confidence"])

            phone = st.text_input("رقم المحمول")
            network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون", "WE"])

            if user_role == "admin":
                sale_place = st.text_input("مكان البيع", value=outlet_name or "")
            else:
                sale_place = st.text_input("مكان البيع", value=outlet_name or "", disabled=True)

            seller_name = st.text_input("اسم البائع", value=username)

            services = st.multiselect("الخدمات الإضافية", [
                "باقة نت",
                "باقة وحدات إضافية",
                "خدمة معرفة الرصيد",
                "خدمة منع المعاكسات",
                "كول تون",
                "أخرى"
            ])

            line_status = st.selectbox("حالة الخط", [
                "مفعل", "موقوف", "قيد التفعيل", "مرفوض", "منتظر استكمال بيانات"
            ])

            activation_status = st.selectbox("حالة الربط", [
                "تم ربط الخط بالعميل", "لم يتم الربط", "منتظر التفعيل", "يوجد مشكلة في البيانات"
            ])

            due_amount = st.number_input("المبلغ المستحق", min_value=0.0, value=0.0, step=10.0)
            paid_amount = st.number_input("المبلغ المدفوع", min_value=0.0, value=0.0, step=10.0)
            due_date = st.text_input("تاريخ الاستحقاق", value=datetime.today().strftime("%Y-%m-%d"))

            link_api_now = st.checkbox("ربط الخط تلقائيًا عبر e& API عند الحفظ")
            notes = st.text_area("ملاحظات")

            save = st.form_submit_button("💾 حفظ العميل والخط")

            if save:
                if not name:
                    st.error("اسم العميل مطلوب")
                elif not nid or len(nid) != 14 or not nid.startswith(("2","3")):
                    st.error("الرقم القومي يجب أن يكون 14 رقم ويبدأ بـ 2 أو 3")
                elif not phone:
                    st.error("رقم المحمول مطلوب")
                else:
                    api_status = "لم يتم"
                    api_message = "لم يتم طلب الربط"

                    if link_api_now:
                        api_result = link_line_api(phone, nid, name, network)
                        api_status = api_result["status"]
                        api_message = api_result["message"]

                    pay_status = payment_status(due_amount, paid_amount)

                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO customers (
                            created_date,national_id,name,address,phone,network,
                            sale_place,seller_name,extra_services,line_status,
                            activation_status,api_status,api_message,
                            due_amount,paid_amount,payment_status,due_date,
                            last_reminder_date,reminder_count,ai_confidence,
                            notes,created_by
                        )
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        created_date,nid,name,address,phone,network,
                        sale_place,seller_name," - ".join(services),line_status,
                        activation_status,api_status,api_message,
                        due_amount,paid_amount,pay_status,due_date,
                        "",0,ai_confidence,
                        notes,username
                    ))
                    conn.commit()

                    st.success(f"تم حفظ العميل: {name}")
                    st.info(f"API: {api_status} - {api_message}")

                    st.session_state.fields = {"name": "", "nid": "", "addr": "", "confidence": "", "raw": ""}

# =========================
# DASHBOARD
# =========================
elif menu == "CRM Dashboard":
    st.subheader("🎯 CRM Dashboard")

    df = read_customers()
    if user_role != "admin" and not df.empty:
        df = df[df["sale_place"] == outlet_name]

    total = len(df)
    active = len(df[df["line_status"] == "مفعل"]) if not df.empty else 0
    stopped = len(df[df["line_status"] == "موقوف"]) if not df.empty else 0
    pending = len(df[df["line_status"] == "قيد التفعيل"]) if not df.empty else 0
    unpaid = len(df[df["payment_status"].isin(["متأخر / غير مدفوع", "مدفوع جزئي"])]) if not df.empty else 0
    due_total = df["due_amount"].fillna(0).sum() if not df.empty else 0
    paid_total = df["paid_amount"].fillna(0).sum() if not df.empty else 0

    k1,k2,k3,k4,k5,k6 = st.columns(6)
    k1.metric("إجمالي العملاء", total)
    k2.metric("مفعل", active)
    k3.metric("موقوف", stopped)
    k4.metric("قيد التفعيل", pending)
    k5.metric("عملاء عليهم مستحقات", unpaid)
    k6.metric("نسبة التحصيل", f"{round((paid_total/due_total)*100,1) if due_total else 0}%")

    st.divider()

    if not df.empty:
        c1,c2 = st.columns(2)
        with c1:
            st.subheader("توزيع الشبكات")
            st.bar_chart(df["network"].value_counts())
        with c2:
            st.subheader("حالة الخطوط")
            st.bar_chart(df["line_status"].value_counts())

        st.subheader("عمليات تحتاج متابعة")
        follow = df[
            (df["line_status"] != "مفعل") |
            (df["payment_status"].isin(["متأخر / غير مدفوع", "مدفوع جزئي"])) |
            (df["activation_status"] != "تم ربط الخط بالعميل")
        ]
        st.dataframe(rename_df(follow), use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد بيانات.")

# =========================
# COLLECTION REPORTS
# =========================
elif menu == "تقارير التحصيل":
    st.subheader("💰 تقارير التحصيل")

    df = read_customers()
    if user_role != "admin" and not df.empty:
        df = df[df["sale_place"] == outlet_name]

    if df.empty:
        st.info("لا توجد بيانات.")
    else:
        total_due = df["due_amount"].fillna(0).sum()
        total_paid = df["paid_amount"].fillna(0).sum()
        remaining = total_due - total_paid

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("إجمالي المستحق", total_due)
        c2.metric("إجمالي المدفوع", total_paid)
        c3.metric("المتبقي", remaining)
        c4.metric("نسبة التحصيل", f"{round((total_paid/total_due)*100,1) if total_due else 0}%")

        st.divider()

        status_filter = st.multiselect(
            "فلتر حالة التحصيل",
            df["payment_status"].dropna().unique().tolist(),
            default=df["payment_status"].dropna().unique().tolist()
        )

        filtered = df[df["payment_status"].isin(status_filter)]
        st.dataframe(rename_df(filtered), use_container_width=True, hide_index=True)

# =========================
# REMINDERS
# =========================
elif menu == "تنبيهات العملاء":
    st.subheader("🔔 تنبيهات تأخير العملاء")

    df = read_customers()
    if user_role != "admin" and not df.empty:
        df = df[df["sale_place"] == outlet_name]

    if df.empty:
        st.info("لا توجد بيانات.")
    else:
        late_df = df[df["payment_status"].isin(["متأخر / غير مدفوع", "مدفوع جزئي"])]

        st.warning(f"عدد العملاء المطلوب تنبيههم: {len(late_df)}")

        for _, row in late_df.iterrows():
            with st.expander(f"{row['name']} - {row['phone']} - مستحق {row['due_amount']}"):
                msg = build_reminder_message(
                    row["name"],
                    row["phone"],
                    row["due_amount"],
                    row["due_date"]
                )
                st.text_area("رسالة التنبيه", value=msg, height=150, key=f"msg_{row['id']}")

                whatsapp_link = f"https://wa.me/2{row['phone']}?text={requests.utils.quote(msg)}"
                st.markdown(f"[فتح واتساب للعميل]({whatsapp_link})")

                if st.button("تسجيل أنه تم إرسال التنبيه", key=f"rem_{row['id']}"):
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE customers
                        SET last_reminder_date=?, reminder_count=COALESCE(reminder_count,0)+1
                        WHERE id=?
                    """, (datetime.today().strftime("%Y-%m-%d"), int(row["id"])))
                    conn.commit()
                    st.success("تم تسجيل التنبيه.")
                    st.rerun()

# =========================
# CUSTOMERS TABLE
# =========================
elif menu == "جدول العملاء":
    st.subheader("📋 جدول العملاء")

    df = read_customers()
    if user_role != "admin" and not df.empty:
        df = df[df["sale_place"] == outlet_name]

    if df.empty:
        st.info("لا توجد بيانات.")
    else:
        search = st.text_input("بحث بالاسم / الرقم القومي / رقم المحمول")
        if search:
            df = df[
                df["name"].astype(str).str.contains(search, case=False, na=False) |
                df["national_id"].astype(str).str.contains(search, case=False, na=False) |
                df["phone"].astype(str).str.contains(search, case=False, na=False)
            ]

        display = rename_df(df)
        st.dataframe(display, use_container_width=True, hide_index=True)

        file = export_excel(display)
        st.download_button(
            "تحميل Excel",
            data=file,
            file_name=f"aura_customers_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# =========================
# USERS
# =========================
elif menu == "إدارة المستخدمين" and user_role == "admin":
    st.subheader("👥 إدارة المستخدمين")

    with st.form("add_user"):
        new_username = st.text_input("اسم المستخدم")
        new_password = st.text_input("كلمة المرور", type="password")
        new_role = st.selectbox("الصلاحية", ["admin", "outlet"])
        new_outlet = st.text_input("اسم الفرع / مكان البيع")
        add = st.form_submit_button("إضافة")

        if add:
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO users (username,password,role,outlet_name,created_at)
                    VALUES (?,?,?,?,?)
                """, (
                    new_username,
                    hash_password(new_password),
                    new_role,
                    new_outlet,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()
                st.success("تم إضافة المستخدم.")
            except sqlite3.IntegrityError:
                st.error("اسم المستخدم موجود بالفعل.")

    users = pd.read_sql_query("""
        SELECT id, username, role, outlet_name, created_at FROM users ORDER BY id DESC
    """, conn)
    st.dataframe(users, use_container_width=True, hide_index=True)

# =========================
# SETTINGS
# =========================
elif menu == "إعدادات النظام" and user_role == "admin":
    st.subheader("⚙️ إعدادات النظام")

    cur = conn.cursor()
    cur.execute("SELECT version FROM db_version WHERE id=1")
    version = cur.fetchone()[0]

    st.info(f"DB Version: {version}")
    st.success("Migration مفعلة تلقائيًا.")

    st.markdown("""
### حالة الربط
- OCR: PaddleOCR
- AI Correction: يعمل فقط عند إضافة OPENAI_API_KEY
- e& API: يعمل فقط عند إضافة EAND_API_BASE_URL و EAND_API_TOKEN
- بدون مفاتيح API، النظام يعمل Simulation بدون كراش.
""")
