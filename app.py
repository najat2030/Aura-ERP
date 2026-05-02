import streamlit as st
import sqlite3
import pandas as pd
import cv2
import numpy as np
import pytesseract
import re
from datetime import datetime
import io

# ================= CONFIG =================
st.set_page_config(page_title="Aura ERP", layout="wide")

# ================= STYLE =================
st.markdown("""
<style>
body { direction: rtl; }
.metric-card {
    background: white;
    padding: 15px;
    border-radius: 12px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.07);
    border-right: 5px solid #0B6B3A;
    text-align:center;
}
</style>
""", unsafe_allow_html=True)

st.title("📊 Aura ERP - النظام المتكامل")

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("erp.db", check_same_thread=False)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        name TEXT,
        nid TEXT,
        address TEXT,
        phone TEXT,
        network TEXT,
        seller TEXT,
        status TEXT
    )
    """)

    conn.commit()
    return conn

conn = init_db()

# ================= OCR HELPERS =================
def preprocess(img):
    img = cv2.resize(img, None, fx=2, fy=2)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    return th

def auto_crop(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)

    for c in cnts:
        x,y,w,h = cv2.boundingRect(c)
        if w*h > 50000:
            return img[y:y+h, x:x+w]
    return img

def normalize(text):
    ar = "٠١٢٣٤٥٦٧٨٩"
    for i in range(10):
        text = text.replace(ar[i], str(i))
    return text

def extract_nid(text):
    text = normalize(text)
    text = text.replace(" ", "")
    match = re.findall(r'[23]\d{13}', text)
    return match[0] if match else ""

def extract_name(text):
    words = text.split()
    return " ".join(words[:5])

def extract_address(text, name, nid):
    return text.replace(name, "").replace(nid, "").strip()

# ================= OCR MAIN =================
def ocr_card(img):
    card = auto_crop(img)
    proc = preprocess(card)

    raw = pytesseract.image_to_string(proc, config='--oem 3 --psm 6 -l ara+eng')
    raw = normalize(raw)

    nid = extract_nid(raw)
    name = extract_name(raw)
    address = extract_address(raw, name, nid)

    return name, nid, address, raw

# ================= UI =================
col1, col2 = st.columns(2)

with col1:
    st.subheader("📸 مسح البطاقة")
    file = st.file_uploader("ارفع الصورة")

    if file:
        img = np.asarray(bytearray(file.read()), dtype=np.uint8)
        img = cv2.imdecode(img, 1)
        st.image(img)

        if st.button("تحليل"):
            name, nid, addr, raw = ocr_card(img)
            st.session_state.data = {
                "name": name,
                "nid": nid,
                "addr": addr
            }

with col2:
    st.subheader("📝 البيانات")

    data = st.session_state.get("data", {"name":"","nid":"","addr":""})

    with st.form("form"):
        name = st.text_input("الاسم", value=data["name"])
        nid = st.text_input("الرقم القومي", value=data["nid"])
        addr = st.text_input("العنوان", value=data["addr"])
        phone = st.text_input("الموبايل")
        net = st.selectbox("الشبكة", ["اتصالات","فودافون","اورانج"])
        seller = st.text_input("البائع")
        status = st.selectbox("الحالة", ["مفعل","موقوف"])

        if st.form_submit_button("حفظ"):
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO customers (date,name,nid,address,phone,network,seller,status)
            VALUES (?,?,?,?,?,?,?,?)
            """, (
                datetime.now().strftime("%Y-%m-%d"),
                name,nid,addr,phone,net,seller,status
            ))
            conn.commit()
            st.success("تم الحفظ")

# ================= TABLE =================
st.subheader("📋 العملاء")

df = pd.read_sql_query("SELECT * FROM customers ORDER BY id DESC", conn)

if not df.empty:
    st.dataframe(df, use_container_width=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)

    st.download_button("تحميل Excel", output.getvalue(), "customers.xlsx")
else:
    st.info("لا يوجد بيانات")
