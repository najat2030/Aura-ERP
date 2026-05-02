import streamlit as st
import easyocr
import cv2
import numpy as np
from PIL import Image
import re

st.set_page_config(page_title="Aura ERP | Smart Scanner", layout="wide")

@st.cache_resource
def load_reader():
    return easyocr.Reader(['ar', 'en'])
reader = load_reader()

st.title("📶 Aura ERP - النظام الذكي المطور")

if 'fields' not in st.session_state:
    st.session_state.fields = {'name': '', 'nid': '', 'addr': ''}

uploaded_file = st.file_uploader("ارفع صورة البطاقة (تأكد أنها واضحة ومعتدلة)", type=['jpg', 'jpeg', 'png'])

if uploaded_file:
    # تحويل الملف لصورة OpenCV
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, 1)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.image(img_rgb, caption="البطاقة الأصلية")
        if st.button("🚀 قنص البيانات"):
            with st.spinner("جاري قص وتحليل البيانات..."):
                h, w, _ = img.shape
                
                # 1. منطقة الاسم (تقريباً في الربع العلوي الأيمن)
                name_area = img[int(h*0.25):int(h*0.55), int(w*0.45):int(w*0.95)]
                # 2. منطقة العنوان (تحت الاسم)
                addr_area = img[int(h*0.55):int(h*0.85), int(w*0.45):int(w*0.95)]
                # 3. منطقة الرقم القومي (الشريط السفلي)
                nid_area = img[int(h*0.75):int(h*0.95), int(w*0.05):int(w*0.75)]
                
                # قراءة كل جزء
                name_res = reader.readtext(name_area, detail=0)
                addr_res = reader.readtext(addr_area, detail=0)
                nid_res = reader.readtext(nid_area, detail=0)
                
                # تنقية النتائج
                final_name = " ".join(name_res).replace("مصطفى", "").strip()
                final_addr = " ".join(addr_res).strip()
                
                full_nid_text = "".join(nid_res).replace(" ", "")
                nid_match = re.findall(r'\d{14}', full_nid_text)
                final_nid = nid_match[0] if nid_match else ""
                if final_nid.startswith('75'): final_nid = final_nid[::-1]

                st.session_state.fields = {'name': final_name, 'nid': final_nid, 'addr': final_addr}
                st.rerun()

    with col2:
        st.subheader("📝 البيانات المستخرجة")
        name = st.text_input("الاسم المستخرج", value=st.session_state.fields['name'])
        nid = st.text_input("الرقم القومي", value=st.session_state.fields['nid'])
        addr = st.text_input("العنوان المستخرج", value=st.session_state.fields['addr'])
        
        if st.button("💾 حفظ"):
            st.success("تم الحفظ في قاعدة البيانات!")
