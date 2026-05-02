import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import cv2
import numpy as np
from PIL import Image
import re
from datetime import datetime
import io

# =========================
# 1. إعدادات الصفحة والتصميم
# =========================
st.set_page_config(page_title="Aura ERP", page_icon="📶", layout="wide")

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
        color: #0B6B3A;
        text-align: center;
        font-weight: 800;
    }

    h2, h3 {
        color: #111827;
        font-weight: 700;
    }

    .stButton>button {
        background-color: #0B6B3A;
        color: white;
        border-radius: 10px;
        border: none;
        font-weight: 700;
        width: 100%;
        height: 42px;
    }

    .stButton>button:hover {
        background-color: #084f2b;
        color: white;
    }

    .stFormSubmitButton>button {
        background-color: #0B6B3A;
        color: white;
        border-radius: 10px;
        border: none;
        font-weight: 700;
        width: 100%;
        height: 42px;
    }

    .stTextInput>div>div>input {
        font-weight: 600;
        text-align: right;
    }

    .stSelectbox label, .stTextInput label, .stMultiSelect label {
        font-weight: 700;
        color: #374151;
    }

    .metric-card {
        background: white;
        border-radius: 14px;
        padding: 18px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.06);
        border-right: 5px solid #0B6B3A;
    }

    .small-note {
        color: #6b7280;
        font-size: 13px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

st.title("📶 Aura ERP - النظام المتكامل المصغر")


# =========================
# 2. قاعدة البيانات
# =========================
def init_db():
    conn = sqlite3.connect('etisalat_telecom.db', check_same_thread=False)
    cursor = conn.cursor()

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
            notes TEXT
        )
    """)

    conn.commit()
    return conn


conn = init_db()


# =========================
# 3. OCR
# =========================
@st.cache_resource
def load_reader():
    return easyocr.Reader(['ar', 'en'], gpu=False)

reader = load_reader()


# =========================
# 4. Session State
# =========================
if 'fields' not in st.session_state:
    st.session_state.fields = {
        'name': '',
        'nid': '',
        'addr': ''
    }


# =========================
# 5. دوال مساعدة
# =========================
def clean_arabic_text(text):
    if not text:
        return ""

    unwanted_words = [
        "جمهورية", "مصر", "العربية", "بطاقة", "تحقيق", "الشخصية",
        "الاسم", "العنوان", "ذكر", "أنثى", "مسلم", "مسيحي"
    ]

    for word in unwanted_words:
        text = text.replace(word, "")

    text = re.sub(r'[^\u0600-\u06FF\s\d\-\/]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_national_id(text):
    if not text:
        return ""

    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")

    # تحويل الأرقام العربية / الفارسية إلى إنجليزية
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    for i in range(10):
        text = text.replace(arabic_digits[i], str(i))
        text = text.replace(persian_digits[i], str(i))

    numbers = re.findall(r'\d+', text)
    joined = "".join(numbers)

    matches = re.findall(r'\d{14}', joined)

    if matches:
        nid = matches[0]

        # لو اتقرأ مقلوب
        if not nid.startswith(("2", "3")):
            reversed_nid = nid[::-1]
            if reversed_nid.startswith(("2", "3")):
                return reversed_nid

        return nid

    return ""


def ocr_card_data(img):
    h, w, _ = img.shape

    # نفس فكرة القص بتاعتك، بس أوسع شوية عشان نلقط الاسم والعنوان أفضل
    name_img = img[int(h * 0.20):int(h * 0.52), int(w * 0.35):int(w * 0.98)]
    addr_img = img[int(h * 0.43):int(h * 0.78), int(w * 0.32):int(w * 0.98)]
    nid_img = img[int(h * 0.72):int(h * 0.98), int(w * 0.02):int(w * 0.95)]

    name_res = reader.readtext(name_img, detail=0, paragraph=True)
    addr_res = reader.readtext(addr_img, detail=0, paragraph=True)
    nid_res = reader.readtext(nid_img, detail=0, paragraph=True)

    full_name = clean_arabic_text(" ".join(name_res))
    full_addr = clean_arabic_text(" ".join(addr_res))
    full_nid_text = " ".join(nid_res)
    final_nid = extract_national_id(full_nid_text)

    return full_name, final_nid, full_addr


def export_excel(df):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='customers')

        workbook = writer.book
        worksheet = writer.sheets['customers']

        for col in worksheet.columns:
            max_length = 0
            column = col[0].column_letter

            for cell in col:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass

            worksheet.column_dimensions[column].width = max_length + 5

    output.seek(0)
    return output


# =========================
# 6. الواجهة الرئيسية
# =========================
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📸 مسح هوية العميل")

    uploaded_file = st.file_uploader(
        "ارفع صورة البطاقة",
        type=['jpg', 'jpeg', 'png']
    )

    if uploaded_file:
        file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, 1)

        st.image(
            cv2.cvtColor(img, cv2.COLOR_BGR2RGB),
            caption="البطاقة المرفوعة",
            use_container_width=True
        )

        if st.button("🚀 قنص وتحليل البيانات"):
            with st.spinner("جاري المسح الذكي للبطاقة..."):
                full_name, final_nid, full_addr = ocr_card_data(img)

                st.session_state.fields = {
                    'name': full_name,
                    'nid': final_nid,
                    'addr': full_addr
                }

                st.success("تم استخراج البيانات. راجعيها قبل الحفظ.")
                st.rerun()

with col2:
    st.subheader("📝 تسجيل البيانات والخط")

    with st.form("main_form"):
        today_date = datetime.today().strftime("%Y-%m-%d")

        created_date = st.text_input("تاريخ التسجيل", value=today_date)
        u_name = st.text_input("اسم العميل", value=st.session_state.fields['name'])
        u_nid = st.text_input("الرقم القومي", value=st.session_state.fields['nid'])
        u_addr = st.text_input("العنوان", value=st.session_state.fields['addr'])

        u_phone = st.text_input("رقم المحمول")
        u_network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون", "WE"])

        sale_place = st.text_input("مكان البيع")
        seller_name = st.text_input("اسم البائع")

        services = st.multiselect(
            "الخدمات الإضافية",
            [
                "باقة نت",
                "باقة وحدات إضافية",
                "خدمة معرفة الرصيد",
                "خدمة منع المعاكسات",
                "خدمة كول تون",
                "خدمة حفظ المكالمات",
                "أخرى"
            ]
        )

        line_status = st.selectbox(
            "حالة الخط",
            ["مفعل", "موقوف", "قيد التفعيل", "مرفوض", "منتظر استكمال بيانات"]
        )

        notes = st.text_area("ملاحظات")

        save_btn = st.form_submit_button("💾 حفظ في قاعدة البيانات")

        if save_btn:
            if not u_nid or len(u_nid) != 14:
                st.error("الرقم القومي لازم يكون 14 رقم.")
            elif not u_phone:
                st.error("يرجى إدخال رقم المحمول.")
            elif not u_name:
                st.error("يرجى إدخال اسم العميل.")
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
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    created_date,
                    u_nid,
                    u_name,
                    u_addr,
                    u_phone,
                    u_network,
                    sale_place,
                    seller_name,
                    " - ".join(services),
                    line_status,
                    notes
                ))

                conn.commit()

                st.success(f"✅ تم حفظ بيانات العميل: {u_name}")

                st.session_state.fields = {
                    'name': '',
                    'nid': '',
                    'addr': ''
                }


# =========================
# 7. Dashboard مختصر
# =========================
st.divider()
st.subheader("📊 ملخص العمليات")

df = pd.read_sql_query("SELECT * FROM customers ORDER BY id DESC", conn)

total_customers = len(df)
active_lines = len(df[df["line_status"] == "مفعل"]) if not df.empty else 0
stopped_lines = len(df[df["line_status"] == "موقوف"]) if not df.empty else 0
pending_lines = len(df[df["line_status"] == "قيد التفعيل"]) if not df.empty else 0

m1, m2, m3, m4 = st.columns(4)

m1.metric("إجمالي العملاء", total_customers)
m2.metric("الخطوط المفعلة", active_lines)
m3.metric("الخطوط الموقوفة", stopped_lines)
m4.metric("قيد التفعيل", pending_lines)


# =========================
# 8. جدول بيانات العمليات
# =========================
st.divider()
st.subheader("📋 جدول بيانات العملاء")

if not df.empty:
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
        "notes": "ملاحظات"
    })

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    excel_file = export_excel(df_display)

    st.download_button(
        label="⬇️ تحميل شيت العملاء Excel",
        data=excel_file,
        file_name=f"aura_customers_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("لا توجد بيانات مسجلة حالياً.")
