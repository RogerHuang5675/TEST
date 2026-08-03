import os
import streamlit as st
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium

# --- 1. 設定網頁標題與排版 ---
st.set_page_config(page_title="臺灣熱危害指數即時分布儀表板", layout="wide")
st.title("🌡️ 臺灣特定地區 熱危害指數 (WBGT) 即時分布儀表板")
st.markdown("每日／每小時定時更新氣象署自動站資料，並依高溫熱危害等級即時標示。")

# --- 2. 氣象署資料擷取與計算 WBGT ---
@st.cache_data(ttl=3600)  # 快取 1 小時 (3600秒)，確保每日自動取得新紀錄
def fetch_weather_and_calculate_wbgt(api_key):
    # 使用 CWA 自動氣象站資料 API (O-A0003-001)
    url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001?Authorization={api_key}&format=JSON"
    response = requests.get(url, verify=False, timeout=15)
    if response.status_code != 200:
        return pd.DataFrame()
    
    data = response.json()
    stations = data["records"]["Station"]
    
    records = []
    for stn in stations:
        try:
            name = stn["StationName"]
            county = stn["GeoInfo"]["CountyName"]
            lat = float(stn["GeoInfo"]["Coordinates"][1]["StationLatitude"])
            lon = float(stn["GeoInfo"]["Coordinates"][1]["StationLongitude"])
            
            # 讀取溫度與濕度
            temp = float(stn["WeatherElement"]["AirTemperature"])
            rh = float(stn["WeatherElement"]["RelativeHumidity"]) / 100.0  # 轉為百分比
            
            # 過濾無效觀測值 (-99 / -999)
            if temp < -50 or rh < 0:
                continue
                
            # 估算水氣壓 e (hPa)
            e = rh * 6.105 * np.exp((17.27 * temp) / (237.7 + temp))
            # 簡化版戶外熱危害指數 (WBGT) 估算
            wbgt = 0.567 * temp + 0.393 * e + 3.94
            
            # 判斷熱危害等級與顏色
            if wbgt >= 33:
                level, color = "第四級：極限危險", "purple"
            elif wbgt >= 31:
                level, color = "第三級：警戒高危", "red"
            elif wbgt >= 28:
                level, color = "第二級：注意防範", "orange"
            else:
                level, color = "第一級：一般正常", "green"
                
            records.append({
                "站名": name, "縣市": county,
                "緯度": lat, "經度": lon,
                "氣溫(°C)": round(temp, 1), "相對濕度": round(rh*100, 1),
                "WBGT指數": round(wbgt, 1), "危害等級": level, "地圖顏色": color
            })
        except (KeyError, ValueError, TypeError):
            continue
            
    return pd.DataFrame(records)

# --- 3. 自動辨識金鑰與側邊欄設定 ---
st.sidebar.header("🗺️ 查詢條件設定")

# 1. 優先從後台 Secrets 或 Linux 系統環境變數讀取
api_key_from_secrets = st.secrets.get("CWA_API_KEY", "") if "CWA_API_KEY" in st.secrets else ""
api_key_from_env = os.getenv("CWA_API_KEY", "")
backend_api_key = api_key_from_secrets or api_key_from_env

# 2. 【安全關鍵機制】絕對不把 backend_api_key 放入前端 HTML 的 value 中！
if backend_api_key:
    # 情境 A：若雲端後台已有設定，直接後端使用，前端僅顯示綠色安全狀態提示
    st.sidebar.success("✅ 系統已安全載入中央氣象署授權碼")
    API_KEY = backend_api_key
else:
    # 情境 B：若後台未設定，才顯示空白密碼輸入框，供外部使用者手動輸入「自己的」金鑰
    st.sidebar.info("💡 目前系統未偵測到後台金鑰，請手動輸入")
    API_KEY = st.sidebar.text_input(
        "請輸入氣象署 API Key", 
        value="", 
        type="password",
        help="輸入您個人申請的 CWA API Key 以載入即時地圖資料。"
    )

# --- 4. 檢查金鑰並顯示地圖或錯誤訊息 ---
# 判斷授權碼是否已成功取得且不為空白
if API_KEY:
    df = fetch_weather_and_calculate_wbgt(API_KEY)
    
    if not df.empty:
        # 特定區域篩選
        all_counties = df["縣市"].unique().tolist()
        selected_counties = st.sidebar.multiselect(
            "選擇關注縣市 (留空顯示全臺灣)",
            options=all_counties,
            default=["臺北市", "新北市", "臺中市", "高雄市"]
        )
        
        if selected_counties:
            df = df[df["縣市"].isin(selected_counties)]
            
        # 建立臺灣 Folium 地圖 (預設焦點：臺灣中部)
        m = folium.Map(location=[23.6, 120.9], zoom_start=8, tiles="CartoDB positron")
        
        # 加上站點標記
        for _, row in df.iterrows():
            popup_text = f"""
            <b>站名：{row['站名']} ({row['縣市']})</b><br>
            WBGT 數值：<b>{row['WBGT指數']}</b> ({row['危害等級']})<br>
            實際氣溫：{row['氣溫(°C)']} °C<br>
            相對濕度：{row['相對濕度']} %
            """
            folium.CircleMarker(
                location=[row["緯度"], row["經度"]],
                radius=8,
                color=row["地圖顏色"],
                fill=True,
                fill_color=row["地圖顏色"],
                fill_opacity=0.8,
                popup=folium.Popup(popup_text, max_width=250),
                tooltip=f"{row['站名']}: WBGT {row['WBGT指數']}"
            ).add_to(m)
            
        # 前端圖表與資料呈現
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("📍 臺灣熱危害指數即時地圖")
            st_folium(m, width=700, height=550)
            
        with col2:
            st.subheader("⚠️ 區域危險站點排行")
            top_hazard = df.sort_values(by="WBGT指數", ascending=False)[
                ["縣市", "站名", "WBGT指數", "危害等級"]
            ].head(10)
            st.dataframe(top_hazard, hide_index=True)
            
    else:
        st.error("無法正確下載氣象資料！請確認 API Key 是否有效，或氣象署連線是否正常。")
else:
    st.warning("⚠️ 請至左側邊欄輸入有效的中央氣象署授權 API Key 以載入熱危害即時分布地圖。")
