import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import cv2
import numpy as np
from PIL import Image
import re

# --- 1. إعدادات التصميم الفخمة ---
st.set_page_config(page_title="Aura ERP", page_icon="📶", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    h1 { color: #D4AF37; text-align: center; font-family: 'Cairo', sans-serif; }
    .stButton>button { background-color: #006400; color: white; border-radius: 10px; border: 1px solid #D4AF37; width: 100%; }
    .stTextInput>div>div>input { color: #D4AF37 !important; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("📶 Aura ERP - النظام المتكامل")

# --- 2. قاعدة البيانات ---
def init_db():
    conn = sqlite3.connect('etisalat_telecom.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers 
                     (national_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, network TEXT)''')
    conn.commit()
    return conn

conn = init_db()

# --- 3. محرك الـ OCR ---
@st.cache_resource
def load_reader():
    return easyocr.Reader(['ar', 'en'])
reader = load_reader()

# --- 4. إدارة الحالة (Session State) ---
if 'fields' not in st.session_state:
    st.session_state.fields = {'name': '', 'nid': '', 'addr': ''}

# --- 5. واجهة المستخدم ---
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📸 مسح هوية العميل")
    uploaded_file = st.file_uploader("ارفع صورة البطاقة", type=['jpg', 'jpeg', 'png'])
    
    if uploaded_file:
        file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, 1)
        st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), caption="البطاقة المرفوعة")
        
        if st.button("🚀 قنص وتحليل البيانات"):
            with st.spinner("جاري المسح الذكي..."):
                h, w, _ = img.shape
                # قص المناطق (تعديل النسب لضمان لقط الاسم والعنوان)
                name_img = img[int(h*0.25):int(h*0.50), int(w*0.40):int(w*0.98)]
                addr_img = img[int(h*0.50):int(h*0.82), int(w*0.40):int(w*0.98)]
                nid_img = img[int(h*0.78):int(h*0.98), int(w*0.02):int(w*0.80)]
                
                name_res = reader.readtext(name_img, detail=0)
                addr_res = reader.readtext(addr_img, detail=0)
                nid_res = reader.readtext(nid_img, detail=0)
                
                # تنظيف الاسم من الكلمات الدخيلة
                full_name = " ".join(name_res).replace("مصطفى", "").replace("الاسم", "").strip()
                full_addr = " ".join(addr_res).strip()
                
                # استخراج الرقم القومي بدقة
                full_nid_text = "".join(nid_res).replace(" ", "")
                nid_match = re.findall(r'\d{14}', full_nid_text)
                final_nid = nid_match[0] if nid_match else ""
                if final_nid.startswith('75'): final_nid = final_nid[::-1]

                st.session_state.fields = {'name': full_name, 'nid': final_nid, 'addr': full_addr}
                st.rerun()

with col2:
    st.subheader("📝 تسجيل البيانات والخط")
    with st.form("main_form"):
        u_name = st.text_input("اسم العميل", value=st.session_state.fields['name'])
        u_nid = st.text_input("الرقم القومي", value=st.session_state.fields['nid'])
        u_addr = st.text_input("العنوان", value=st.session_state.fields['addr'])
        
        # رجوع الخانات المفقودة
        u_phone = st.text_input("رقم المحمول الجديد")
        u_network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون"])
        
        save_btn = st.form_submit_button("💾 حفظ في قاعدة البيانات")
        
        if save_btn:
            if u_nid and u_phone:
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)", 
                               (u_nid, u_name, u_addr, u_phone, u_network))
                conn.commit()
                st.success(f"✅ تم حفظ العميل {u_name} بنجاح!")
                st.session_state.fields = {'name': '', 'nid': '', 'addr': ''}
            else:
                st.error("يرجى التأكد من الرقم القومي ورقم المحمول")

# --- 6. جدول البيانات (الذي اختفى) ---
st.divider()
st.subheader("📊 جدول بيانات العمليات")
try:
    df = pd.read_sql_query("SELECT * FROM customers ORDER BY rowid DESC", conn)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("لا توجد بيانات مسجلة حالياً.")
except Exception as e:
    st.error(f"خطأ في عرض الجدول: {e}")
