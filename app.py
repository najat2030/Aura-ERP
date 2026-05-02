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
# CONFIG
# =========================
st.set_page_config(page_title="Aura ERP", page_icon="📊", layout="wide")

DB_NAME = "aura_erp.db"
CURRENT_DB_VERSION = 3

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

.stTextInput>div>div>input,
.stTextArea textarea {
    text-align: right;
    font-weight: 600;
}

.kpi-card {
    background: white;
    border-radius: 18px;
    padding: 18px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.08);
    border-right: 6px solid #0B6B3A;
    text-align: center;
}

.kpi-title {
    color: #6b7280;
    font-size: 14px;
}

.kpi-value {
    color: #111827;
    font-size: 30px;
    font-weight: 800;
}
</style>
""", unsafe_allow_html=True)


# =========================
# DATABASE
# =========================
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
            api_status TEXT,
            api_message TEXT,
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
    cols = [row[1] for row in cursor.fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()


def migrate_db(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM db_version WHERE id = 1")
    row = cursor.fetchone()

    if row is None:
        cursor.execute("INSERT INTO db_version (id, version) VALUES (1, 1)")
        conn.commit()

    columns = [
        ("created_date", "TEXT"),
        ("sale_place", "TEXT"),
        ("seller_name", "TEXT"),
        ("extra_services", "TEXT"),
        ("line_status", "TEXT"),
        ("activation_status", "TEXT"),
        ("api_status", "TEXT"),
        ("api_message", "TEXT"),
        ("notes", "TEXT"),
        ("created_by", "TEXT"),
    ]

    for col, typ in columns:
        add_column_if_not_exists(conn, "customers", col, typ)

    add_column_if_not_exists(conn, "users", "outlet_name", "TEXT")
    add_column_if_not_exists(conn, "users", "created_at", "TEXT")

    cursor.execute("UPDATE db_version SET version = ? WHERE id = 1", (CURRENT_DB_VERSION,))
    conn.commit()


migrate_db(conn)


def create_default_admin():
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE username='admin'")
    if cursor.fetchone() is None:
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


create_default_admin()


# =========================
# OCR ENGINE
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
# OCR HELPERS
# =========================
def normalize_digits(text):
    if not text:
        return ""

    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"

    for i in range(10):
        text = text.replace(arabic_digits[i], str(i))
        text = text.replace(persian_digits[i], str(i))

    return text


def clean_arabic_text(text):
    if not text:
        return ""

    text = normalize_digits(text)

    bad_words = [
        "جمهورية", "مصر", "العربية", "بطاقة", "تحقيق", "الشخصية",
        "الاسم", "العنوان", "محافظة", "ذكر", "انثى", "أنثى",
        "مسلم", "مسيحي", "تاريخ", "الميلاد"
    ]

    for word in bad_words:
        text = text.replace(word, " ")

    text = re.sub(r"[^\u0600-\u06FF\s\d\-\/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def auto_correct_name(name):
    if not name:
        return ""

    fixes = {
        "علا ء": "علاء",
        "علاءالدين": "علاء الدين",
        "علاء الدين": "علاء الدين",
        "سيداحمد": "سيد احمد",
        "احمدمحمد": "احمد محمد",
        "محمداحمد": "محمد احمد",
        "عبدالرحمن": "عبد الرحمن",
        "عبدالله": "عبد الله",
        "عبدالعزيز": "عبد العزيز",
        "عبدالفتاح": "عبد الفتاح",
        "ابوالعلا": "ابو العلا",
        "ابوالمجد": "ابو المجد",
    }

    name = clean_arabic_text(name)

    for wrong, right in fixes.items():
        name = name.replace(wrong, right)

    words = name.split()

    remove_words = [
        "مركز", "قسم", "شارع", "ش", "مدينة", "اسوان", "القاهرة",
        "الجيزة", "الدقهلية", "الشرقية", "الشرواونة", "ادفو"
    ]

    words = [w for w in words if w not in remove_words and not w.isdigit()]

    # الاسم غالبًا 4 أو 5 كلمات
    if len(words) > 5:
        words = words[:5]

    return " ".join(words).strip()


def auto_correct_address(addr):
    if not addr:
        return ""

    addr = clean_arabic_text(addr)

    fixes = {
        "ادفو": "إدفو",
        "اسوان": "أسوان",
        "القاهره": "القاهرة",
        "الجيزه": "الجيزة",
        "شارع": "ش",
    }

    for wrong, right in fixes.items():
        addr = addr.replace(wrong, right)

    return addr.strip()


def preprocess_image(img):
    """
    تحسين الصورة قبل OCR:
    - تكبير
    - إزالة noise
    - sharpening
    - contrast
    """
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])

    sharp = cv2.filter2D(gray, -1, kernel)

    return sharp


def extract_national_id_from_text(text):
    text = normalize_digits(text)
    text = text.replace(" ", "").replace("-", "").replace("/", "").replace(".", "")

    numbers = re.findall(r"\d+", text)

    candidates = []

    for num in numbers:
        if len(num) == 14 and num.startswith(("2", "3")):
            candidates.append(num)

        # لو الرقم ملزوق وسط نص طويل
        long_matches = re.findall(r"[23]\d{13}", num)
        for m in long_matches:
            candidates.append(m)

    if candidates:
        return candidates[0]

    return ""


def ocr_card(img):
    h, w, _ = img.shape

    processed = preprocess_image(img)

    # لأن الصورة اتكبرت 2X
    ph, pw = processed.shape

    # مناطق البطاقة
    name_crop = processed[int(ph * 0.22):int(ph * 0.48), int(pw * 0.42):int(pw * 0.98)]
    addr_crop = processed[int(ph * 0.42):int(ph * 0.72), int(pw * 0.40):int(pw * 0.98)]
    nid_crop = processed[int(ph * 0.65):int(ph * 0.88), int(pw * 0.35):int(pw * 0.98)]

    # قراءة مناطق محددة
    name_res = reader.readtext(name_crop, detail=0, paragraph=False)
    addr_res = reader.readtext(addr_crop, detail=0, paragraph=False)
    nid_res = reader.readtext(nid_crop, detail=0, paragraph=False)

    # قراءة الصورة كاملة كـ backup
    full_res = reader.readtext(processed, detail=0, paragraph=False)

    raw_name = " ".join(name_res)
    raw_addr = " ".join(addr_res)
    raw_nid = " ".join(nid_res)

    full_text = " ".join(full_res)

    nid = extract_national_id_from_text(raw_nid)

    if not nid:
        nid = extract_national_id_from_text(full_text)

    name = auto_correct_name(raw_name)
    address = auto_correct_address(raw_addr)

    # fallback لو الاسم طلع ناقص
    if len(name.split()) < 4:
        cleaned_full = clean_arabic_text(full_text)
        words = cleaned_full.split()

        # نحاول نلقط الاسم قبل العنوان
        possible_name = []
        for word in words:
            if word in ["الشرواونة", "مركز", "ادفو", "إدفو", "اسوان", "أسوان"]:
                break
            if not word.isdigit() and len(word) > 1:
                possible_name.append(word)

        if len(possible_name) >= 4:
            name = auto_correct_name(" ".join(possible_name[-5:]))

    return name, nid, address


# =========================
# API PLACEHOLDER
# =========================
def link_line_api(phone, national_id, customer_name):
    """
    هنا مكان الربط الحقيقي مع API بتاع الخطوط.
    لما يبقى عندك API من الشركة، هنبدل الجزء ده بالطلب الحقيقي.

    مثال المتوقع:
    - إرسال رقم المحمول
    - إرسال الرقم القومي
    - استقبال حالة الخط
    """

    if not phone or not national_id:
        return "فشل", "بيانات ناقصة للربط"

    # Mock Success
    return "تم", "تم تجهيز الخط للربط داخل النظام"


# =========================
# DATA HELPERS
# =========================
def login(username, password):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, role, outlet_name
        FROM users
        WHERE username = ? AND password = ?
    """, (username, hash_password(password)))

    return cursor.fetchone()


def read_customers():
    try:
        return pd.read_sql_query("SELECT * FROM customers ORDER BY id DESC", conn)
    except Exception:
        return pd.DataFrame()


def export_excel(df):
    output = io.BytesIO()

    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="customers")
            worksheet = writer.sheets["customers"]

            for col in worksheet.columns:
                max_length = 0
                col_letter = col[0].column_letter

                for cell in col:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))

                worksheet.column_dimensions[col_letter].width = max_length + 4

    except Exception:
        csv_data = df.to_csv(index=False).encode("utf-8-sig")
        return io.BytesIO(csv_data)

    output.seek(0)
    return output


def rename_customers_df(df):
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
        "extra_services": "الخدمات الإضافية",
        "line_status": "حالة الخط",
        "activation_status": "حالة ربط الخط",
        "api_status": "حالة API",
        "api_message": "رسالة API",
        "notes": "ملاحظات",
        "created_by": "تم التسجيل بواسطة"
    })


# =========================
# LOGIN PAGE
# =========================
if not st.session_state.logged_in:
    st.title("📊 Aura ERP - Login")

    c1, c2, c3 = st.columns([1, 1, 1])

    with c2:
        st.subheader("تسجيل الدخول")

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
st.title("📊 Aura ERP - النظام المتكامل المصغر")

username = st.session_state.user["username"]
user_role = st.session_state.user["role"]
outlet_name = st.session_state.user["outlet_name"]

h1, h2, h3 = st.columns([2, 2, 1])
h1.info(f"المستخدم: {username}")
h2.info(f"الصلاحية: {user_role} | الفرع: {outlet_name}")

with h3:
    if st.button("تسجيل خروج"):
        st.session_state.logged_in = False
        st.session_state.user = {}
        st.rerun()


# =========================
# MENU
# =========================
if user_role == "admin":
    menu = st.sidebar.radio(
        "القائمة",
        [
            "تسجيل عميل وخط",
            "CRM Dashboard",
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
            "CRM Dashboard",
            "جدول العملاء"
        ]
    )


# =========================
# PAGE REGISTER
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
                with st.spinner("جاري تحسين الصورة وقراءة البطاقة..."):
                    name, nid, address = ocr_card(img)

                    st.session_state.fields = {
                        "name": name,
                        "nid": nid,
                        "addr": address
                    }

                    st.success("تم استخراج البيانات. راجعيها وعدلي أي حرف قبل الحفظ.")
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
                "حالة ربط الخط",
                [
                    "تم ربط الخط بالعميل",
                    "لم يتم الربط",
                    "منتظر التفعيل",
                    "يوجد مشكلة في البيانات"
                ]
            )

            link_api_now = st.checkbox("ربط الخط تلقائيًا عبر API عند الحفظ")

            notes = st.text_area("ملاحظات")

            save = st.form_submit_button("💾 حفظ العميل والخط")

            if save:
                if not name:
                    st.error("اسم العميل مطلوب")
                elif not nid or len(nid) != 14 or not nid.startswith(("2", "3")):
                    st.error("الرقم القومي يجب أن يكون 14 رقم ويبدأ بـ 2 أو 3")
                elif not phone:
                    st.error("رقم المحمول مطلوب")
                else:
                    api_status = "لم يتم"
                    api_message = "لم يتم طلب الربط"

                    if link_api_now:
                        api_status, api_message = link_line_api(phone, nid, name)

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
                            api_status,
                            api_message,
                            notes,
                            created_by
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        api_status,
                        api_message,
                        notes,
                        username
                    ))

                    conn.commit()

                    st.success(f"✅ تم حفظ العميل: {name}")
                    st.info(f"API: {api_status} - {api_message}")

                    st.session_state.fields = {
                        "name": "",
                        "nid": "",
                        "addr": ""
                    }


# =========================
# PAGE DASHBOARD
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
    linked = len(df[df["activation_status"] == "تم ربط الخط بالعميل"]) if not df.empty else 0
    api_done = len(df[df["api_status"] == "تم"]) if not df.empty else 0

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("إجمالي العملاء", total)
    k2.metric("مفعل", active)
    k3.metric("موقوف", stopped)
    k4.metric("قيد التفعيل", pending)
    k5.metric("مربوط بالعميل", linked)
    k6.metric("API Done", api_done)

    st.divider()

    if not df.empty:
        c1, c2 = st.columns(2)

        with c1:
            st.subheader("📡 توزيع الشبكات")
            network_df = df["network"].value_counts().reset_index()
            network_df.columns = ["الشبكة", "العدد"]
            st.bar_chart(network_df.set_index("الشبكة"))

        with c2:
            st.subheader("📌 حالة الخطوط")
            status_df = df["line_status"].value_counts().reset_index()
            status_df.columns = ["الحالة", "العدد"]
            st.bar_chart(status_df.set_index("الحالة"))

        c3, c4 = st.columns(2)

        with c3:
            st.subheader("🏪 أداء أماكن البيع")
            outlet_df = df["sale_place"].value_counts().reset_index()
            outlet_df.columns = ["مكان البيع", "عدد العمليات"]
            st.dataframe(outlet_df, use_container_width=True, hide_index=True)

        with c4:
            st.subheader("👤 أداء البائعين")
            seller_df = df["seller_name"].value_counts().reset_index()
            seller_df.columns = ["البائع", "عدد العمليات"]
            st.dataframe(seller_df, use_container_width=True, hide_index=True)

        st.subheader("⚠️ عمليات تحتاج متابعة")
        follow_df = df[
            (df["line_status"] != "مفعل") |
            (df["activation_status"] != "تم ربط الخط بالعميل") |
            (df["api_status"] != "تم")
        ]

        if not follow_df.empty:
            st.dataframe(rename_customers_df(follow_df), use_container_width=True, hide_index=True)
        else:
            st.success("كل العمليات مستقرة ولا توجد مشاكل متابعة.")

    else:
        st.info("لا توجد بيانات لعرض Dashboard.")


# =========================
# PAGE CUSTOMERS TABLE
# =========================
elif menu == "جدول العملاء":
    st.subheader("📋 شيت العملاء")

    df = read_customers()

    if user_role != "admin" and not df.empty:
        df = df[df["sale_place"] == outlet_name]

    if not df.empty:
        search = st.text_input("بحث بالاسم / الرقم القومي / رقم المحمول")

        if search:
            df = df[
                df["name"].astype(str).str.contains(search, case=False, na=False) |
                df["national_id"].astype(str).str.contains(search, case=False, na=False) |
                df["phone"].astype(str).str.contains(search, case=False, na=False)
            ]

        df_display = rename_customers_df(df)

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
# PAGE USERS
# =========================
elif menu == "إدارة المستخدمين" and user_role == "admin":
    st.subheader("👥 إدارة المستخدمين")

    with st.form("add_user_form"):
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
# PAGE SETTINGS
# =========================
elif menu == "إعدادات النظام" and user_role == "admin":
    st.subheader("⚙️ إعدادات النظام")

    cursor = conn.cursor()
    cursor.execute("SELECT version FROM db_version WHERE id = 1")
    version = cursor.fetchone()[0]

    st.info(f"DB Version: {version}")
    st.success("Database Migration مفعلة تلقائيًا.")

    st.warning("بيانات الدخول الافتراضية: admin / admin123")

    st.markdown("""
    ### API الربط المباشر بالخطوط
    الكود جاهز بمكان الربط:
    `link_line_api(phone, national_id, customer_name)`

    لما يكون معاك API فعلي من الشركة، هنبدل الجزء التجريبي بالربط الحقيقي.
    """)
