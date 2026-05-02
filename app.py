import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import cv2
import numpy as np
import re
from datetime import datetime
import io
import hashlib

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="Aura ERP", page_icon="📶", layout="wide")

# =========================
# STYLE
# =========================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Cairo', sans-serif;
    direction: rtl;
}

.stApp {
    background-color: #f7f8fa;
}

h1 {
    text-align: center;
    color: #0B6B3A;
    font-weight: 800;
}

h2, h3 {
    color: #111827;
    font-weight: 700;
}

.stButton>button,
.stFormSubmitButton>button {
    background-color: #0B6B3A;
    color: white;
    border-radius: 10px;
    border: none;
    font-weight: 700;
    width: 100%;
    height: 42px;
}

.stButton>button:hover,
.stFormSubmitButton>button:hover {
    background-color: #084f2b;
    color: white;
}

.stTextInput>div>div>input,
.stTextArea textarea {
    text-align: right;
    font-weight: 600;
}

.metric-box {
    background: white;
    padding: 18px;
    border-radius: 16px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.07);
    border-right: 6px solid #0B6B3A;
    text-align: center;
}

.metric-title {
    color: #6b7280;
    font-size: 15px;
}

.metric-value {
    color: #111827;
    font-size: 28px;
    font-weight: 800;
}
</style>
""", unsafe_allow_html=True)


# =========================
# DATABASE
# =========================
DB_NAME = "aura_erp.db"
CURRENT_DB_VERSION = 2


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS db_version (
            id INTEGER PRIMARY KEY,
            version INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            outlet_name TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
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
            notes TEXT,
            created_by TEXT
        )
    """)

    conn.commit()
    return conn


conn = init_db()


def add_column_if_not_exists(conn, table, column, col_type):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]

    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()


def migrate_db(conn):
    cursor = conn.cursor()

    cursor.execute("SELECT version FROM db_version WHERE id = 1")
    row = cursor.fetchone()

    if row is None:
        cursor.execute("INSERT INTO db_version (id, version) VALUES (1, 1)")
        conn.commit()
        current_version = 1
    else:
        current_version = row[0]

    add_column_if_not_exists(conn, "customers", "created_date", "TEXT")
    add_column_if_not_exists(conn, "customers", "sale_place", "TEXT")
    add_column_if_not_exists(conn, "customers", "seller_name", "TEXT")
    add_column_if_not_exists(conn, "customers", "extra_services", "TEXT")
    add_column_if_not_exists(conn, "customers", "line_status", "TEXT")
    add_column_if_not_exists(conn, "customers", "activation_status", "TEXT")
    add_column_if_not_exists(conn, "customers", "notes", "TEXT")
    add_column_if_not_exists(conn, "customers", "created_by", "TEXT")

    add_column_if_not_exists(conn, "users", "outlet_name", "TEXT")
    add_column_if_not_exists(conn, "users", "created_at", "TEXT")

    cursor.execute("UPDATE db_version SET version = ? WHERE id = 1", (CURRENT_DB_VERSION,))
    conn.commit()


migrate_db(conn)


def create_default_admin(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    admin = cursor.fetchone()

    if admin is None:
        cursor.execute("""
            INSERT INTO users (username, password, role, outlet_name, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "admin",
            hash_password("admin123"),
            "admin",
            "الإدارة",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()


create_default_admin(conn)


# =========================
# OCR
# =========================
@st.cache_resource
def load_reader():
    return easyocr.Reader(['ar', 'en'], gpu=False)


reader = load_reader()


# =========================
# SESSION
# =========================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user" not in st.session_state:
    st.session_state.user = {}

if "fields" not in st.session_state:
    st.session_state.fields = {
        "name": "",
        "nid": "",
        "addr": ""
    }


# =========================
# HELPERS
# =========================
def clean_text(text):
    if not text:
        return ""

    unwanted = [
        "جمهورية", "مصر", "العربية", "بطاقة", "تحقيق", "الشخصية",
        "الاسم", "العنوان", "ذكر", "أنثى", "مسلم", "مسيحي"
    ]

    for word in unwanted:
        text = text.replace(word, "")

    text = re.sub(r"[^\u0600-\u06FF\s\d\-\/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_digits(text):
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"

    for i in range(10):
        text = text.replace(arabic_digits[i], str(i))
        text = text.replace(persian_digits[i], str(i))

    return text


def extract_nid(text):
    text = normalize_digits(text)
    text = text.replace(" ", "").replace("-", "")

    numbers = re.findall(r"\d+", text)
    joined = "".join(numbers)

    matches = re.findall(r"\d{14}", joined)

    if matches:
        nid = matches[0]

        if not nid.startswith(("2", "3")):
            reversed_nid = nid[::-1]
            if reversed_nid.startswith(("2", "3")):
                return reversed_nid

        return nid

    return ""


def ocr_card(img):
    h, w, _ = img.shape

    name_img = img[int(h * 0.20):int(h * 0.52), int(w * 0.35):int(w * 0.98)]
    addr_img = img[int(h * 0.43):int(h * 0.80), int(w * 0.30):int(w * 0.98)]
    nid_img = img[int(h * 0.70):int(h * 0.98), int(w * 0.02):int(w * 0.95)]

    name_res = reader.readtext(name_img, detail=0, paragraph=True)
    addr_res = reader.readtext(addr_img, detail=0, paragraph=True)
    nid_res = reader.readtext(nid_img, detail=0, paragraph=True)

    name = clean_text(" ".join(name_res))
    addr = clean_text(" ".join(addr_res))
    nid = extract_nid(" ".join(nid_res))

    return name, nid, addr


def read_customers():
    return pd.read_sql_query("SELECT * FROM customers ORDER BY id DESC", conn)


def export_excel(df):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="customers")
        worksheet = writer.sheets["customers"]

        for col in worksheet.columns:
            max_length = 0
            column_letter = col[0].column_letter

            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))

            worksheet.column_dimensions[column_letter].width = max_length + 5

    output.seek(0)
    return output


def login(username, password):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, role, outlet_name 
        FROM users 
        WHERE username = ? AND password = ?
    """, (username, hash_password(password)))

    return cursor.fetchone()


# =========================
# LOGIN PAGE
# =========================
if not st.session_state.logged_in:
    st.title("📶 Aura ERP - Login")

    col_a, col_b, col_c = st.columns([1, 1, 1])

    with col_b:
        st.subheader("تسجيل الدخول")

        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")

        if st.button("دخول"):
            user = login(username, password)

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
st.title("📶 Aura ERP - النظام المتكامل المصغر")

user_role = st.session_state.user["role"]
username = st.session_state.user["username"]
outlet_name = st.session_state.user["outlet_name"]

top1, top2, top3 = st.columns([2, 2, 1])
top1.info(f"المستخدم: {username}")
top2.info(f"الصلاحية: {user_role} | الفرع: {outlet_name}")

with top3:
    if st.button("تسجيل خروج"):
        st.session_state.logged_in = False
        st.session_state.user = {}
        st.rerun()


# =========================
# SIDEBAR
# =========================
if user_role == "admin":
    menu = st.sidebar.radio(
        "القائمة",
        [
            "تسجيل عميل وخط",
            "Dashboard KPI",
            "جدول العملاء",
            "إدارة المستخدمين",
            "إعدادات النظام"
        ]
    )
else:
    menu = st.sidebar.radio(
        "القائمة",
        [
            "تسجيل عميل وخط",
            "Dashboard KPI",
            "جدول العملاء"
        ]
    )


# =========================
# PAGE: REGISTER
# =========================
if menu == "تسجيل عميل وخط":
    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        st.subheader("📸 مسح بطاقة العميل")

        uploaded_file = st.file_uploader("ارفع صورة البطاقة", type=["jpg", "jpeg", "png"])

        if uploaded_file:
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, 1)

            st.image(
                cv2.cvtColor(img, cv2.COLOR_BGR2RGB),
                caption="البطاقة المرفوعة",
                use_container_width=True
            )

            if st.button("🚀 تحليل البطاقة"):
                with st.spinner("جاري قراءة البطاقة..."):
                    name, nid, addr = ocr_card(img)

                    st.session_state.fields = {
                        "name": name,
                        "nid": nid,
                        "addr": addr
                    }

                    st.success("تم استخراج البيانات، راجعيها قبل الحفظ.")
                    st.rerun()

    with col2:
        st.subheader("📝 تسجيل بيانات العميل والخط")

        with st.form("customer_form"):
            today = datetime.today().strftime("%Y-%m-%d")

            created_date = st.text_input("تاريخ اليوم", value=today)
            name = st.text_input("اسم العميل بالكامل", value=st.session_state.fields["name"])
            nid = st.text_input("الرقم القومي 14 رقم", value=st.session_state.fields["nid"])
            address = st.text_input("العنوان بالكامل", value=st.session_state.fields["addr"])

            phone = st.text_input("رقم المحمول")
            network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون", "WE"])

            if user_role == "admin":
                sale_place = st.text_input("مكان البيع", value=outlet_name or "")
            else:
                sale_place = st.text_input("مكان البيع", value=outlet_name or "", disabled=True)

            seller_name = st.text_input("اسم البائع", value=username)

            services = st.multiselect(
                "الخدمات الإضافية",
                [
                    "باقة نت",
                    "باقة وحدات إضافية",
                    "خدمة معرفة الرصيد",
                    "خدمة منع المعاكسات",
                    "كول تون",
                    "خدمة الاحتفاظ بالمكالمات",
                    "أخرى"
                ]
            )

            line_status = st.selectbox(
                "حالة الخط",
                ["مفعل", "موقوف", "قيد التفعيل", "مرفوض", "منتظر استكمال بيانات"]
            )

            activation_status = st.selectbox(
                "حالة الربط بالخط",
                [
                    "تم ربط الخط بالعميل",
                    "لم يتم الربط",
                    "منتظر التفعيل",
                    "يوجد مشكلة في البيانات"
                ]
            )

            notes = st.text_area("ملاحظات")

            save = st.form_submit_button("💾 حفظ العميل والخط")

            if save:
                if not name:
                    st.error("اسم العميل مطلوب")
                elif not nid or len(nid) != 14:
                    st.error("الرقم القومي يجب أن يكون 14 رقم")
                elif not phone:
                    st.error("رقم المحمول مطلوب")
                else:
                    cursor = conn.cursor()

                    cursor.execute("""
                        INSERT INTO customers (
                            created_date,
                            national_id,
                            name,
                            address,
                            phone,
                            network,
                            sale_place,
                            seller_name,
                            extra_services,
                            line_status,
                            activation_status,
                            notes,
                            created_by
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        created_date,
                        nid,
                        name,
                        address,
                        phone,
                        network,
                        sale_place,
                        seller_name,
                        " - ".join(services),
                        line_status,
                        activation_status,
                        notes,
                        username
                    ))

                    conn.commit()

                    st.success(f"✅ تم حفظ العميل وربط الخط: {name}")

                    st.session_state.fields = {
                        "name": "",
                        "nid": "",
                        "addr": ""
                    }


# =========================
# PAGE: DASHBOARD
# =========================
elif menu == "Dashboard KPI":
    st.subheader("🔥 Dashboard KPI")

    df = read_customers()

    if user_role != "admin":
        df = df[df["sale_place"] == outlet_name]

    total = len(df)
    active = len(df[df["line_status"] == "مفعل"]) if not df.empty else 0
    stopped = len(df[df["line_status"] == "موقوف"]) if not df.empty else 0
    pending = len(df[df["line_status"] == "قيد التفعيل"]) if not df.empty else 0
    linked = len(df[df["activation_status"] == "تم ربط الخط بالعميل"]) if not df.empty else 0

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric("إجمالي العمليات", total)
    c2.metric("مفعل", active)
    c3.metric("موقوف", stopped)
    c4.metric("قيد التفعيل", pending)
    c5.metric("مربوط بالعميل", linked)

    st.divider()

    if not df.empty:
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("حسب الشبكة")
            network_df = df["network"].value_counts().reset_index()
            network_df.columns = ["الشبكة", "العدد"]
            st.bar_chart(network_df.set_index("الشبكة"))

        with col_b:
            st.subheader("حسب حالة الخط")
            status_df = df["line_status"].value_counts().reset_index()
            status_df.columns = ["الحالة", "العدد"]
            st.bar_chart(status_df.set_index("الحالة"))

        st.subheader("أداء البائعين")
        seller_df = df["seller_name"].value_counts().reset_index()
        seller_df.columns = ["البائع", "عدد العمليات"]
        st.dataframe(seller_df, use_container_width=True, hide_index=True)

    else:
        st.info("لا توجد بيانات كافية لعرض Dashboard.")


# =========================
# PAGE: CUSTOMERS TABLE
# =========================
elif menu == "جدول العملاء":
    st.subheader("📋 شيت العملاء")

    df = read_customers()

    if user_role != "admin":
        df = df[df["sale_place"] == outlet_name]

    if not df.empty:
        search = st.text_input("بحث بالاسم / الرقم القومي / رقم المحمول")

        if search:
            df = df[
                df["name"].astype(str).str.contains(search, case=False, na=False) |
                df["national_id"].astype(str).str.contains(search, case=False, na=False) |
                df["phone"].astype(str).str.contains(search, case=False, na=False)
            ]

        df_display = df.rename(columns={
            "id": "ID",
            "created_date": "تاريخ التسجيل",
            "national_id": "الرقم القومي",
            "name": "اسم العميل",
            "address": "العنوان",
            "phone": "رقم المحمول",
            "network": "الشبكة",
            "sale_place": "مكان البيع",
            "seller_name": "اسم البائع",
            "extra_services": "الخدمات الإضافية",
            "line_status": "حالة الخط",
            "activation_status": "حالة ربط الخط",
            "notes": "ملاحظات",
            "created_by": "تم التسجيل بواسطة"
        })

        st.dataframe(df_display, use_container_width=True, hide_index=True)

        excel_file = export_excel(df_display)

        st.download_button(
            "⬇️ تحميل Excel",
            data=excel_file,
            file_name=f"aura_customers_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.info("لا توجد بيانات مسجلة.")


# =========================
# PAGE: USERS MANAGEMENT
# =========================
elif menu == "إدارة المستخدمين" and user_role == "admin":
    st.subheader("👥 إدارة المستخدمين")

    with st.form("add_user"):
        new_username = st.text_input("اسم المستخدم الجديد")
        new_password = st.text_input("كلمة المرور", type="password")
        new_role = st.selectbox("الصلاحية", ["admin", "outlet"])
        new_outlet = st.text_input("اسم الفرع / مكان البيع")

        add_user = st.form_submit_button("إضافة مستخدم")

        if add_user:
            if not new_username or not new_password:
                st.error("اسم المستخدم وكلمة المرور مطلوبين")
            else:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO users (username, password, role, outlet_name, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        new_username,
                        hash_password(new_password),
                        new_role,
                        new_outlet,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ))
                    conn.commit()
                    st.success("تم إضافة المستخدم بنجاح")
                except sqlite3.IntegrityError:
                    st.error("اسم المستخدم موجود بالفعل")

    st.divider()

    users_df = pd.read_sql_query("""
        SELECT id, username, role, outlet_name, created_at 
        FROM users 
        ORDER BY id DESC
    """, conn)

    users_df = users_df.rename(columns={
        "id": "ID",
        "username": "اسم المستخدم",
        "role": "الصلاحية",
        "outlet_name": "الفرع",
        "created_at": "تاريخ الإنشاء"
    })

    st.dataframe(users_df, use_container_width=True, hide_index=True)


# =========================
# PAGE: SETTINGS
# =========================
elif menu == "إعدادات النظام" and user_role == "admin":
    st.subheader("⚙️ إعدادات النظام")

    cursor = conn.cursor()
    cursor.execute("SELECT version FROM db_version WHERE id = 1")
    version = cursor.fetchone()[0]

    st.info(f"DB Version: {version}")
    st.success("Migration مفعلة تلقائيًا. أي عمود جديد يتم إضافته بدون حذف البيانات القديمة.")

    st.warning("بيانات الدخول الافتراضية: admin / admin123 — يفضل تغييرها لاحقًا.")
