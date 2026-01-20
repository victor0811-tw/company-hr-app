import streamlit as st
import pandas as pd
import gspread
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os

# --- ☁️ 雲端設定區 ---
GOOGLE_SHEET_NAME = "company_app_db"
SECRETS_FILE = "secrets.json"
# === 設定顯示名稱 ===
ORG_NAME = "社團法人為你社區服務協會"

# --- 1. 連線設定 ---
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
        st.error(f"寫入失敗: {e}")

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
    if 'days' not in df.columns: return 0.0
    
    df['days'] = pd.to_numeric(df['days'], errors='coerce').fillna(0)
    if 'username' in df.columns and 'type' in df.columns and 'status' in df.columns:
        mask = (df['username'] == username) & (df['type'] == '特休') & (df['status'] == '已核准')
        return df[mask]['days'].sum()
    return 0.0

def get_balance(username):
    df = read_data("balance")
    if df.empty: return 0.0
    if 'balance' not in df.columns: return 0.0
    df['balance'] = pd.to_numeric(df['balance'], errors='coerce').fillna(0)
    if username in df['username'].values:
        return df.loc[df['username'] == username, 'balance'].values[0]
    return 0.0

def update_balance(username, days_delta):
    df = read_data("balance")
    if df.empty: df = pd.DataFrame(columns=['username', 'balance'])
    if 'balance' not in df.columns: df['balance'] = 0.0
    
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

def rename_columns_to_chinese(df):
    if df.empty: return df
    map_dict = {
        'username': '員工帳號', 'name': '姓名', 'time': '打卡時間', 'action': '動作',
        'type': '假別', 'start_date': '日期', 'days': '天數', 'session': '時段',
        'reason': '事由', 'status': '狀態', 'manager_note': '主管備註',
        'date': '日期', 'operator': '操作人'
    }
    return df.rename(columns=map_dict)

# --- 3. 主程式 ---
def main():
    # 設定網頁標題 (瀏覽器籤頁顯示的文字)
    st.set_page_config(page_title=ORG_NAME, page_icon="🏢")
    
    if 'user' not in st.session_state: st.session_state['user'] = None

    # === 登入畫面 ===
    if st.session_state['user'] is None:
        st.title(ORG_NAME) # 大標題改為協會名稱
        st.subheader("☁️ 雲端人資系統")
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

    # === 登入後畫面 ===
    user = st.session_state['user']
    user_full = get_user_info_full(user['username'])
    
    entitled = calculate_annual_leave_entitlement(user_full.get('onboard_date'))
    used = get_used_annual_leave(user['username'])
    my_balance = get_balance(user['username'])
    
    # 側邊欄顯示協會名稱
    st.sidebar.markdown(f"### {ORG_NAME}")
    st.sidebar.divider()
    
    st.sidebar.title(f"👤 {user_full['name']}")
    st.sidebar.text(f"{user_full['title']}")
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
        df_users = read_data("users")
        name_map = dict(zip(df_users['username'], df_users['name']))
        
        if user['role'] in ['manager', 'admin']:
            all_u_list = df_users['username'].tolist()
            target = st.selectbox("查詢", all_u_list, format_func=lambda x: f"{name_map.get(x, x)}", index=all_u_list.index(user['username']) if user['username'] in all_u_list else 0)
        
        t1, t2, t3 = st.tabs(["打卡", "請假", "加班"])
        with t1: 
            df = read_data("attendance")
            if not df.empty:
                df_show = df[df['username'] == target].copy()
                st.dataframe(rename_columns_to_chinese(df_show), use_container_width=True)
        with t2: 
            df = read_data("leaves")
            if not df.empty:
                df_show = df[df['username'] == target].copy()
                st.dataframe(rename_columns_to_chinese(df_show), use_container_width=True)
        with t3: 
            df = read_data("overtime")
            if not df.empty:
                df_show = df[df['username'] == target].copy()
                st.dataframe(rename_columns_to_chinese(df_show), use_container_width=True)

    elif menu == "批次加班登錄":
        st.header("🎁 加班發放")
        with st.form("ot"):
            dt, dys, rsn = st.date_input("日期"), st.number_input("天數", 0.5, step=0.5), st.text_input("事由")
            df_users = read_data("users")
            active_users = df_users[df_users['status']=='在職']
            user_options = {row['username']: f"{row['name']} ({row['username']})" for i, row in active_users.iterrows()}
            sel = st.multiselect("對象", active_users['username'].tolist(), format_func=lambda x: user_options.get(x, x))
            if st.form_submit_button("發放") and sel:
                for u in sel:
                    update_balance(u, dys)
                    append_data("overtime", [u, str(dt), dys, rsn, user['name']])
                st.success("完成")

    elif menu == "主管審核":
        st.header("📑 審核")
        lv = read_data("leaves")
        df_users = read_data("users")
        name_map = dict(zip(df_users['username'], df_users['name']))

        if not lv.empty:
            pending = lv[lv['status']=='待審核']
            if pending.empty:
                st.info("目前無待審核假單")
            else:
                for i, r in pending.iterrows():
                    emp_name = name_map.get(r['username'], r['username'])
                    title_str = f"{emp_name}：{r['type']} {r['days']} 天 ({r['start_date']})"
                    if r['days'] == '0.5': title_str += f" - {r['session']}"
                    with st.expander(title_str):
                        st.write(f"事由: {r['reason']}")
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
        df_users = read_data("users")
        name_map = dict(zip(df_users['username'], df_users['name']))
        if not att.empty: 
            mask = att['time'].astype(str).str.startswith(m)
            df_month = att[mask].copy()
            if not df_month.empty:
                df_month['姓名'] = df_month['username'].map(name_map).fillna(df_month['username'])
                df_final = df_month[['time', '姓名', 'action']].rename(columns={'time': '時間', 'action': '動作'})
                st.dataframe(df_final, use_container_width=True)
            else: st.info("無資料")

if __name__ == "__main__":
    main()
