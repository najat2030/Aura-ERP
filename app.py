import streamlit as st
import easyocr
import sqlite3
import pandas as pd
import re
from PIL import Image
import numpy as np

# --- الإعدادات الفخمة ---
st.set_page_config(page_title="Aura ERP", page_icon="📶", layout="wide")

# --- قاعدة البيانات ---
conn = sqlite3.connect('etisalat_telecom.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS customers (national_id TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, network TEXT)')
conn.commit()

# --- تحميل المحرك ---
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['ar', 'en'])
reader = load_ocr()

if 'data' not in st.session_state:
    st.session_state['data'] = {'name': '', 'nid': '', 'addr': ''}

col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📸 مسح هوية العميل")
    uploaded_file = st.file_uploader("ارفع صورة البطاقة", type=['jpg', 'png', 'jpeg'])
    
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="البطاقة المرفوعة", width=400)
        
        if st.button("🚀 بدء السحب الذكي"):
            with st.spinner('جاري تحليل البطاقة هندسياً...'):
                img_array = np.array(image)
                # نطلب من المحرك الإحداثيات واليقين
                results = reader.readtext(img_array)
                
                full_text_list = []
                extracted_nid = ""
                
                # الكلمات المستبعدة تماماً من الظهور في الاسم أو العنوان
                blacklist = ['جمهورية', 'مصر', 'العربية', 'بطاقة', 'تحقيق', 'شخصية', 'الرقم', 'القومي', 'وزارة', 'الداخلية']

                for (bbox, text, prob) in results:
                    clean_text = text.strip()
                    full_text_list.append(clean_text)
                    
                    # 1. البحث عن الرقم القومي (تجاهل أي رموز أو مسافات)
                    nums_only = re.sub(r'\D', '', clean_text)
                    if len(nums_only) == 14:
                        extracted_nid = nums_only
                    elif len(nums_only) > 10: # لو الرقم اتقسم لقطعتين
                        # بنحاول نجمعه مع اللي قبله أو اللي بعده
                        pass

                # 2. منطق استخراج الاسم (الاسم عادة في النصف العلوي الأيمن)
                # هنفلتر النصوص: لازم ميكونش فيها أرقام وميكونش في البلاك ليست
                potential_info = [t for t in full_text_list if not any(b in t for b in blacklist) and not re.search(r'\d', t)]
                
                name = ""
                address = ""
                
                if len(potential_info) >= 1:
                    # الاسم في البطاقة المصرية غالباً هو أول نص بشري يظهر بعد العناوين الرسمية
                    name = potential_info[0]
                if len(potential_info) >= 2:
                    # العنوان غالباً هو الكتلة النصية التي تلي الاسم
                    address = " ".join(potential_info[1:3])

                # تصحيح الرقم القومي لو اتقرأ بالمقلوب
                if extracted_nid.startswith('75'):
                    extracted_nid = extracted_nid[::-1]

                st.session_state['data'] = {'name': name, 'nid': extracted_nid, 'addr': address}
                st.success("✅ تمت المعالجة!")
                st.rerun()

with col2:
    st.subheader("📝 تسجيل بيانات الخط")
    
    name_input = st.text_input("اسم العميل بالكامل", value=st.session_state['data']['name'])
    nid_input = st.text_input("الرقم القومي", value=st.session_state['data']['nid'])
    addr_input = st.text_input("العنوان", value=st.session_state['data']['addr'])
    
    phone = st.text_input("رقم المحمول الجديد")
    network = st.selectbox("الشبكة", ["اتصالات", "أورانج", "فودافون"])
    
    if st.button("💾 حفظ في النظام"):
        cursor.execute("INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)", 
                       (nid_input, name_input, addr_input, phone, network))
        conn.commit()
        st.success("تم الحفظ!")
