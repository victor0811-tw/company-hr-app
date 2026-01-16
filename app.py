import streamlit as st
import pandas as pd
import gspread
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os

# --- ☁️ 雲端設定區 ---
GOOGLE_SHEET_NAME = "company_app_db"
SECRETS_FILE = "secrets.json"

# --- 1. 連線 Google Sheets (加入 ttl 快取機制以減少 429 錯誤) ---
@st.cache_resource(ttl=600)
def get_google_sheet_client():
    try:
        if os.path.exists(SECRETS_FILE):
            gc = gspread.service_account(filename=SECRETS_FILE)
        else:
            if "gcp_service_account" in st.secrets:
                creds = st.secrets["gcp_service_account"]
                gc = gspread.service_account_from_dict(creds)
            else:
                st.error("❌ 找不到金鑰！")
                st.stop()
        
        sh = gc.open(GOOGLE_SHEET_NAME)
        return sh
    except Exception as e:
        st.error(f"連線失敗: {e}")
        st.stop()

# 讀取資料不快取，確保資料最新，但寫入失敗時可重試
def read_data(sheet_name):
    sh = get_google_sheet_client()
    try:
        worksheet = sh.worksheet(sheet_name)
        data = worksheet.get_all_records()
        if not data: return pd.DataFrame()
        return pd.DataFrame(data).astype(str)
    except gspread.WorksheetNotFound:
        st.error(f"找不到分頁：{sheet_name}")
        st.stop()
    except Exception as e:
        # 如果遇到 429 錯誤，顯示友善提示
        if "429" in str(e):
            st.warning("⚠️ 系統忙碌中 (Google API 限流)，請稍等 1 分鐘後再試。")
            st.stop()
        else:
            st.error(f"讀取錯誤: {e}")
            st.stop()

def append_data(sheet_name, row_data_list):
    sh = get_google_sheet_client()
    try:
        worksheet = sh.worksheet(sheet_name)
        worksheet.append_row(row_data_list)
    except Exception as e:
        st.error(f"寫入失敗，請稍後再試: {e}")

def overwrite_data(sheet_name, df):
    sh = get_google_sheet_client()
    try:
        worksheet = sh.worksheet(sheet_name)
        worksheet.clear()
        worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    except Exception as e:
        st.error(f"更新失敗: {e}")

# --- 2. 核心邏輯 ---
def calculate_annual_leave_entitlement(onboard_date_str):
    try:
        onboard = datetime.strptime(str(onboard_date_str), "%Y-%m-%d")
        today = datetime.now()
        diff = relativedelta(today, onboard)
        years = diff.years
        months = diff.months
        if years < 0: return 0
        elif years == 0 and months >= 6: return 3
        elif years == 1: return 7
        elif years == 2: return 10
        elif years >= 3 and years < 5: return 14
        elif years >= 5 and years < 10: return 15
        elif years >= 10: return min(15 + (years - 10), 30)
        else: return 0
    except: return 0

def get_used_annual_leave(username):
    df = read_data("leaves")
    if df.empty: return 0.0
    df['days'] = pd.to_numeric(df['days'], errors='coerce').fillna(0)
    mask = (df['username'] == username) & (df['type'] == '特休') & (df['status'] == '已核准')
    return df[mask]['days'].sum()

def get_balance(username):
    df = read_data("balance")
    if df.empty: return 0.0
    df['balance'] = pd.to_numeric(df['balance'], errors='coerce').fillna(0)
    if username in df['username'].values:
        return df.loc[df['username'] == username, 'balance'].values[0]
    return 0.0

def update_balance(username, days_delta):
    df = read_data("balance")
    if df.empty: df = pd.DataFrame(columns=['username', 'balance'])
    df['balance'] = pd.to_numeric(df['balance'], errors='coerce').fillna(0)
    if username in df['username'].values:
        df.loc[df['username'] == username, 'balance'] += days_delta
    else:
        new_row = pd.DataFrame({'username': [username], 'balance': [days_delta]})
        df = pd.concat([df, new_row], ignore_index=True)
    overwrite_data("balance", df)

def get_user_info_full(username):
    df = read_data("users")
    if not df.empty:
        user = df[df['username'] == username]
        if not user.empty: return user.iloc[0]
    return None

def login(username, password):
    df = read_data("users")
    if not df.empty:
        user = df[(df['username'] == username) & (df['password'] == password)]
        if not user.empty:
            found_user = user.iloc[0]
            if str(found_user.get('status')) == '離職': return "resigned"
            return found_user
    return None

# --- 3. 主程式 ---
def main():
    st.set_page_config(page_title="☁️ 雲端人資系統", page_icon="🌤️")
    if 'user' not in st.session_state: st.session_state['user'] = None

    if st.session_state['user'] is None:
        st.title("🌤️ 雲端員工系統")
        with st.form("login"):
            username = st.text_input("帳號")
            password = st.text_input("密碼", type='password')
            if st.form_submit_button("登入"):
                try:
                    user = login(username, password)
                    if isinstance(user, str) and user == "resigned": st.error("⛔ 已離職")
                    elif user is not None:
                        st.session_state['user'] = user
                        st.rerun()
                    else: st.error("帳號或密碼錯誤")
                except Exception as e: st.error(f"系統錯誤: {e}")
        return

    user = st.session_state['user']
    # 這裡確保每次動作都重新抓取最新個資 (包含到職日)
    user_full = get_user_info_full(user['username']) 
    
    entitled = calculate_annual_leave_entitlement(user_full['onboard_date'])
    used = get_used_annual_leave(user['username'])
    my_balance = get_balance(user['username'])
    
    # --- 側邊欄 ---
    st.sidebar.title(f"👤 {user_full['name']}")
    st.sidebar.text(f"{user_full['title']}")
    # === 新增功能：顯示到職日 ===
    st.sidebar.caption(f"📅 到職日: {user_full.get('onboard_date', '未設定')}")
    st.sidebar.divider()
    
    c1, c2 = st.sidebar.columns(2)
    c1.metric("補休", f"{my_balance}")
    c2.metric("特休剩", f"{entitled - used}", help=f"總 {entitled}")
    
    if st.sidebar.button("登出"):
        st.session_state['user'] = None
        st.rerun()

    menu = st.sidebar.radio("功能", ["打卡作業", "請假申請", "紀錄查詢"] + (["批次加班登錄", "主管審核", "考勤月報表"] if user['role'] in ['manager', 'admin'] else []))

    if menu == "打卡作業":
        st.header("⏰ 打卡")
        c1, c2 = st.columns(2)
        if c1.button("上班 ☀️", use_container_width=True):
            append_data("attendance", [user['username'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '上班'])
            st.success("成功")
        if c2.button("下班 🌙", use_container_width=True):
            append_data("attendance", [user['username'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '下班'])
            st.success("成功")

    elif menu == "請假申請":
        st.header("📝 請假")
        with st.form("l"):
            lt, sd, d = st.selectbox("假別", ["特休", "補休", "病假", "事假"]), st.date_input("日期"), st.number_input("天數", 0.5, step=0.5)
            sess = st.radio("時段", ["上午", "下午"], horizontal=True) if d == 0.5 else "全天"
            rsn = st.text_area("事由")
            if st.form_submit_button("送出"):
                if lt == "補休" and my_balance < d: st.error("餘額不足")
                else: 
                    append_data("leaves", [user['username'], lt, str(sd), d, sess, rsn, '待審核', ''])
                    st.success("已送出")

    elif menu == "紀錄查詢":
        st.header("📅 紀錄")
        target = user['username']
        if user['role'] in ['manager', 'admin']:
            all_u = read_data("users")
            target = st.selectbox("查詢", all_u['username'].tolist(), format_func=lambda x: f"{all_u[all_u['username']==x]['name'].values[0]}")
        
        t1, t2, t3 = st.tabs(["打卡", "請假", "加班"])
        with t1: st.dataframe(read_data("attendance")[lambda d: d['username'] == target] if not read_data("attendance").empty else [])
        with t2: st.dataframe(read_data("leaves")[lambda d: d['username'] == target] if not read_data("leaves").empty else [])
        with t3: st.dataframe(read_data("overtime")[lambda d: d['username'] == target] if not read_data("overtime").empty else [])

    elif menu == "批次加班登錄":
        st.header("🎁 加班發放")
        with st.form("ot"):
            dt, dys, rsn = st.date_input("日期"), st.number_input("天數", 0.5, step=0.5), st.text_input("事由")
            usrs = read_data("users")[lambda d: d['status']=='在職']['username'].tolist()
            sel = st.multiselect("對象", usrs)
            if st.form_submit_button("發放") and sel:
                for u in sel:
                    update_balance(u, dys)
                    append_data("overtime", [u, str(dt), dys, rsn, user['name']])
                st.success("完成")

    elif menu == "主管審核":
        st.header("📑 審核")
        lv = read_data("leaves")
        if not lv.empty:
            for i, r in lv[lv['status']=='待審核'].iterrows():
                with st.expander(f"{r['username']} - {r['type']} {r['days']}天"):
                    st.write(f"{r['reason']}")
                    c1, c2 = st.columns(2)
                    if c1.button("准", key=f"ok_{i}"):
                        lv.at[i, 'status'] = '已核准'
                        if r['type'] == '補休': update_balance(r['username'], -float(r['days']))
                        overwrite_data("leaves", lv)
                        st.rerun()
                    if c2.button("駁", key=f"no_{i}"):
                        lv.at[i, 'status'] = '已駁回'
                        overwrite_data("leaves", lv)
                        st.rerun()

    elif menu == "考勤月報表":
        st.header("📊 月報")
        m = st.text_input("月份", datetime.now().strftime("%Y-%m"))
        att = read_data("attendance")
        if not att.empty: st.dataframe(att[att['time'].str.startswith(m)], use_container_width=True)

if __name__ == "__main__":
    main()
