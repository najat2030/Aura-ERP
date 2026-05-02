import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import re
from PIL import Image
import numpy as np

# --- إعدادات الصفحة الفخمة ---
st.set_page_config(page_title="Etisalat Telecom ERP", page_icon="📶", layout="wide")

# ستايل CSS لإضافة لمسة الذهب والأخضر
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    h1 { color: #D4AF37; font-family: 'Cairo', sans-serif; }
    .stButton>button { background-color: #006400; color: white; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

st.title("📶 اتصالات تليكوم - نظام الإدارة الذكي")
st.write("نائبة المدير: أهلاً بكِ في لوحة التحكم الخاصة بكِ")

# --- قاعدة البيانات ---
def init_db():
    conn = sqlite3.connect('etisalat_telecom.db', check_same_thread=False)
    return conn

conn = init_db()
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS customers (national_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, network TEXT)')
conn.commit()

# --- محرك الـ OCR (كاش عشان السرعة) ---
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['ar', 'en'])

reader = load_ocr()

# --- واجهة المستخدم ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📸 مسح هوية العميل")
    uploaded_file = st.file_uploader("ارفع صورة البطاقة هنا", type=['jpg', 'png', 'jpeg'])
    
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="البطاقة المرفوعة", width=300)
        
        if st.button("بدء السحب الذكي"):
            with st.spinner('جاري قراءة البيانات...'):
                img_array = np.array(image)
                results = reader.readtext(img_array, detail=0)
                full_text = " ".join(results)
                
                # استخراج الرقم القومي
                nid_match = re.findall(r'\b[23]\d{13}\b', full_text)
                st.session_state['nid'] = nid_match[0] if nid_match else ""
                st.success("تم المسح بنجاح!")

with col2:
    st.subheader("📝 تسجيل البيانات")
    name = st.text_input("اسم العميل بالكامل")
    nid = st.text_input("الرقم القومي", value=st.session_state.get('nid', ""))
    phone = st.text_input("رقم المحمول")
    network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون"])
    
    if st.button("حفظ في قاعدة البيانات"):
        if nid and phone:
            cursor.execute("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)", 
                           (nid, name, "العنوان مستخرج من OCR", phone, network))
            conn.commit()
            st.balloons()
            st.success(f"تم تسجيل العميل {name} بنجاح!")
        else:
            st.error("من فضلك أدخل الرقم القومي ورقم التليفون")

# --- عرض البيانات (ERP) ---
st.divider()
st.subheader("📊 قاعدة بيانات العملاء الحالية")
df = pd.read_sql_query("SELECT * FROM customers", conn)
st.dataframe(df, use_container_width=True)
