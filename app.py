import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import re
from PIL import Image
import numpy as np

# --- 1. الإعدادات والتصميم ---
st.set_page_config(page_title="Aura ERP", page_icon="📶", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    h1 { color: #D4AF37; text-align: center; }
    .stButton>button { background-color: #006400; color: white; border-radius: 10px; border: 1px solid #D4AF37; }
    input { color: #D4AF37 !important; font-weight: bold !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📶 Aura ERP - الإصدار المطور")

# --- 2. قاعدة البيانات ---
conn = sqlite3.connect('etisalat_telecom.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS customers (national_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, network TEXT)')
conn.commit()

# --- 3. تحميل المحرك ---
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['ar', 'en'])
reader = load_ocr()

# --- 4. إدارة البيانات (Session State) ---
# بنعرف الخانات دي عشان نتحكم في اللي بيظهر جواها
if 'nid_val' not in st.session_state: st.session_state['nid_val'] = ""
if 'name_val' not in st.session_state: st.session_state['name_val'] = ""
if 'addr_val' not in st.session_state: st.session_state['addr_val'] = ""

# --- 5. الواجهة ---
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📸 مسح هوية العميل")
    uploaded_file = st.file_uploader("ارفع صورة البطاقة", type=['jpg', 'png', 'jpeg'])
    
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="البطاقة المرفوعة", width=400)
        
        if st.button("🚀 بدء السحب الذكي"):
            with st.spinner('جاري تحليل البيانات...'):
                img_array = np.array(image)
                results = reader.readtext(img_array, detail=0)
                
                # تنظيف النصوص المستخرجة
                clean_results = [res.strip() for res in results if len(res.strip()) > 2]
                full_text_no_spaces = "".join(clean_results).replace(" ", "")
                
                # 1. استخراج الرقم القومي
                nid_match = re.findall(r'\d{14}', full_text_no_spaces)
                if nid_match:
                    nid = nid_match[0]
                    # تصحيح الاتجاه: لو بدأ بـ 75 (نهاية الرقم المصري) بنعكسه
                    if nid.startswith('75'): nid = nid[::-1]
                    st.session_state['nid_val'] = nid

                # 2. استخراج الاسم (محاولة ذكية)
                # الكلمات اللي مش عايزينها تطلع كـ "اسم"
                ignored_words = ['جمهورية', 'مصر', 'العربية', 'بطاقة', 'تحقيق', 'شخصية', 'الرقم', 'القومي']
                potential_names = []
                for res in clean_results:
                    if not any(word in res for word in ignored_words) and not re.search(r'\d', res):
                        potential_names.append(res)
                
                if potential_names:
                    # غالباً الاسم بيكون أول سطر نصي واضح في نص البطاقة
                    st.session_state['name_val'] = potential_names[0]
                    if len(potential_names) > 1:
                        st.session_state['addr_val'] = potential_names[1]

                st.success("✅ تم سحب البيانات! راجعي الخانات الآن.")
                st.rerun()

with col2:
    st.subheader("📝 تسجيل بيانات الخط")
    
    # ربط الخانات بـ Session State لضمان ظهور البيانات فوراً
    name = st.text_input("اسم العميل بالكامل", value=st.session_state['name_val'])
    nid = st.text_input("الرقم القومي (14 رقم)", value=st.session_state['nid_val'])
    phone = st.text_input("رقم المحمول الجديد")
    network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون"])
    address = st.text_input("العنوان", value=st.session_state['addr_val'])
    
    if st.button("💾 حفظ في النظام"):
        if len(nid) == 14 and phone:
            cursor.execute("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)", 
                           (nid, name, address, phone, network))
            conn.commit()
            st.success(f"تم حفظ العميل {name} بنجاح!")
            # تصفير البيانات بعد الحفظ
            st.session_state['nid_val'] = ""; st.session_state['name_val'] = ""; st.session_state['addr_val'] = ""
            st.rerun()
        else:
            st.error("تأكدي من الرقم القومي ورقم التليفون")
