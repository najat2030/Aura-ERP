import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import re
from PIL import Image
import numpy as np

# --- 1. إعدادات الصفحة والتصميم (Luxury Emerald & Gold) ---
st.set_page_config(page_title="Aura ERP | Etisalat Telecom", page_icon="📶", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    h1 { color: #D4AF37; font-family: 'Cairo', sans-serif; text-align: center; }
    h3 { color: #008040; }
    .stButton>button { 
        background-color: #006400; 
        color: white; 
        border-radius: 10px; 
        width: 100%;
        border: 1px solid #D4AF37;
    }
    .stTextInput>div>div>input { color: #D4AF37; }
    </style>
    """, unsafe_allow_html=True)

st.title("📶 Aura ERP - نظام الإدارة الذكي")
st.write("<p style='text-align: center; color: #888;'>نائبة المدير: أهلاً بكِ في لوحة تحكم اتصالات تليكوم</p>", unsafe_allow_html=True)

# --- 2. إدارة قاعدة البيانات ---
def init_db():
    conn = sqlite3.connect('etisalat_telecom.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers 
                     (national_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, network TEXT)''')
    conn.commit()
    return conn

conn = init_db()
cursor = conn.cursor()

# --- 3. محرك الـ OCR (تحميل لمرة واحدة فقط) ---
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['ar', 'en'])

reader = load_ocr()

# --- 4. إدارة الحالة (Session State) لتحديث الخانات ---
if 'nid_val' not in st.session_state:
    st.session_state['nid_val'] = ""

# --- 5. واجهة المستخدم (التقسيم لعمودين) ---
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📸 مسح هوية العميل")
    uploaded_file = st.file_uploader("ارفع صورة البطاقة الشخصية", type=['jpg', 'png', 'jpeg'])
    
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="البطاقة المرفوعة", width=400)
        
        if st.button("🚀 بدء السحب الذكي للبيانات"):
            with st.spinner('جاري تحليل الصورة واستخراج الأرقام...'):
                # تحويل الصورة لمصفوفة ومعالجتها
                img_array = np.array(image)
                results = reader.readtext(img_array, detail=0)
                
                # دمج كل النصوص المستخرجة وحذف المسافات للبحث عن الرقم القومي
                full_text_clean = "".join(results).replace(" ", "")
                
                # البحث عن أي 14 رقم متتالي (نمط الرقم القومي المصري)
                nid_match = re.findall(r'\d{14}', full_text_clean)
                
                if nid_match:
                    st.session_state['nid_val'] = nid_match[0]
                    st.success("✅ تم استخراج الرقم القومي بنجاح!")
                    st.rerun() # إعادة تحميل الصفحة لتحديث الخانة بالرقم الجديد
                else:
                    st.error("❌ لم نتمكن من لقط 14 رقم كاملين. تأكدي من إضاءة الصورة أو اكتبي الرقم يدوياً.")

with col2:
    st.subheader("📝 تسجيل بيانات الخط")
    
    # الخانات المرتبطة بقاعدة البيانات والحالة
    with st.form("customer_form", clear_on_submit=True):
        name = st.text_input("اسم العميل بالكامل")
        
        # خانة الرقم القومي تأخذ قيمتها من الـ Session State اللي بيملاها الـ OCR
        nid = st.text_input("الرقم القومي", value=st.session_state['nid_val'])
        
        phone = st.text_input("رقم المحمول الجديد")
        network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون"])
        address = st.text_input("العنوان (اختياري)")
        
        submitted = st.form_submit_button("💾 حفظ البيانات في النظام")
        
        if submitted:
            if len(nid) == 14 and len(phone) >= 11:
                try:
                    cursor.execute("INSERT OR REPLACE INTO customers (national_id, name, address, phone, network) VALUES (?, ?, ?, ?, ?)", 
                                   (nid, name, address, phone, network))
                    conn.commit()
                    st.balloons()
                    st.success(f"تم تسجيل العميل {name} بنجاح على شبكة {network}")
                    # تصفير الرقم القومي بعد الحفظ
                    st.session_state['nid_val'] = ""
                except Exception as e:
                    st.error(f"حدث خطأ أثناء الحفظ: {e}")
            else:
                st.warning("تأكدي من كتابة الرقم القومي (14 رقم) ورقم الهاتف بشكل صحيح.")

# --- 6. عرض قاعدة البيانات (للإدارة فقط) ---
st.divider()
st.subheader("📊 سجل العمليات الأخير (Aura Database)")
try:
    df = pd.read_sql_query("SELECT * FROM customers ORDER BY rowid DESC LIMIT 10", conn)
    st.dataframe(df, use_container_width=True)
except:
    st.info("قاعدة البيانات فارغة حالياً. ابدأي بتسجيل أول عميل.")
