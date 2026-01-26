import streamlit as st
import pandas as pd
import gspread
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
import time
import calendar  # 新增引用：用來畫月曆

# --- ☁️ 雲端設定區 ---
GOOGLE_SHEET_NAME = "company_app_db"
SECRETS_FILE = "secrets.json"
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

def get_used_leave_stats(username):
    df = read_data("leaves")
    stats = {'特休': 0.0, '病假': 0.0, '補休': 0.0, '婚假': 0.0, '喪假': 0.0, '產假': 0.0}
    
    if df.empty: return stats
    if 'days' not in df.columns: return stats

    df['days'] = pd.to_numeric(df['days'], errors='coerce').fillna(0)
    
    mask = (df['username'] == username) & (df['status'] == '已核准')
    user_leaves = df[mask]
    
    for l_type in stats.keys():
        stats[l_type] = user_leaves[user_leaves['type'] == l_type]['days'].sum()
        
    return stats

def get_balances(username):
    df = read_data("balance")
    balances = {'balance': 0.0, 'marriage': 0.0, 'funeral': 0.0, 'maternity': 0.0}
    
    if df.empty: return balances
    
    for col in balances.keys():
        if col not in df.columns:
            df[col] = 0.0
            
    if username in df['username'].values:
        row = df[df['username'] == username].iloc[0]
        for col in balances.keys():
            balances[col] = float(row.get(col, 0.0))
            
    return balances

def update_balance_multi(username, type_col, days_delta):
    df = read_data("balance")
    if df.empty: df = pd.DataFrame(columns=['username', 'balance', 'marriage', 'funeral', 'maternity'])
    
    cols = ['balance', 'marriage', 'funeral', 'maternity']
    for c in cols:
        if c not in df.columns: df[c] = 0.0
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        
    if username in df['username'].values:
        df.loc[df['username'] == username, type_col] += days_delta
    else:
        new_data = {'username': username, 'balance': 0, 'marriage': 0, 'funeral': 0, 'maternity': 0}
        new_data[type_col] = days_delta
        new_row = pd.DataFrame([new_data])
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

# --- 3. 新增功能：月曆繪製 ---
def render_calendar_ui(df_leaves, df_users):
    """繪製互動式月曆，標示請假狀況"""
    # 狀態管理：目前的年/月
    if 'cal_year' not in st.session_state:
        st.session_state['cal_year'] = datetime.now().year
        st.session_state['cal_month'] = datetime.now().month

    # 切換月份的函式
    def change_month(amount):
        st.session_state['cal_month'] += amount
        if st.session_state['cal_month'] > 12:
            st.session_state['cal_month'] = 1
            st.session_state['cal_year'] += 1
        elif st.session_state['cal_month'] < 1:
            st.session_state['cal_month'] = 12
            st.session_state['cal_year'] -= 1

    # 月曆控制列
    col_prev, col_date, col_next = st.columns([1, 5, 1])
    with col_prev:
        st.button("◀", on_click=change_month, args=(-1,), use_container_width=True)
    with col_date:
        st.markdown(f"<h3 style='text-align: center;'>{st.session_state['cal_year']} 年 {st.session_state['cal_month']} 月</h3>", unsafe_allow_html=True)
    with col_next:
        st.button("▶", on_click=change_month, args=(1,), use_container_width=True)

    # 準備資料：篩選當月已核准的假單
    target_ym = f"{st.session_state['cal_year']}-{st.session_state['cal_month']:02d}"
    
    # 建立 帳號 -> 中文名 對照表
    name_map = dict(zip(df_users['username'], df_users['name']))
    
    # 建立 {日期: [請假字串, ...]} 的字典
    events_map = {}
    if not df_leaves.empty:
        # 只看已核准
        approved = df_leaves[df_leaves['status'] == '已核准']
        for _, row in approved.iterrows():
            s_date = row['start_date'] # 格式 YYYY-MM-DD
            if s_date.startswith(target_ym):
                # 取得這天的 key (去掉前面的 0, e.g., 2024-05-05 -> 5)
                day_int = int(s_date.split('-')[2])
                
                u_name = name_map.get(row['username'], row['username'])
                info = f"{u_name}: {row['type']} {row['days']}天 ({row['session']})"
                
                if day_int not in events_map:
                    events_map[day_int] = []
                events_map[day_int].append(info)

    # 繪製月曆網格
    # 星期幾標題
    cols = st.columns(7)
    weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    for i, w in enumerate(weekdays):
        cols[i].markdown(f"**{w}**", unsafe_allow_html=True)

    # 取得當月日曆矩陣
    # monthcalendar 回傳一個矩陣，0 代表該位置是上個月或下個月的日子
    cal = calendar.monthcalendar(st.session_state['cal_year'], st.session_state['cal_month'])

    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            with cols[i]:
                if day == 0:
                    st.write("") # 空白
                else:
                    # 檢查這天有沒有活動
                    has_event = day in events_map
                    
                    # 顯示日期
                    if has_event:
                        # 組合提示訊息
                        tooltip_text = "\n".join(events_map[day])
                        # 用紅色顯示，並加上 tooltip
                        st.markdown(f"""
                        <div style='background-color: #ffebee; border-radius: 5px; padding: 5px; text-align: center; border: 1px solid #ffcdd2;' title='{tooltip_text}'>
                            <strong>{day}</strong><br>
                            <span style='color: red; font-size: 0.8em;'>🔴 {len(events_map[day])}人</span>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding: 5px; text-align: center;'>{day}</div>", unsafe_allow_html=True)
    st.markdown("---")


# --- 4. 主程式 ---
def main():
    st.set_page_config(page_title=ORG_NAME, page_icon="🏢")
    
    if 'user' not in st.session_state: st.session_state['user'] = None

    # === 登入畫面 ===
    if st.session_state['user'] is None:
        st.title(ORG_NAME)
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
    
    entitled_annual = calculate_annual_leave_entitlement(user_full.get('onboard_date'))
    used_stats = get_used_leave_stats(user['username'])
    balances = get_balances(user['username'])
    
    remaining_annual = entitled_annual - used_stats['特休']
    remaining_sick = 30.0 - used_stats['病假']

    # 主管通知
    pending_count = 0
    if user['role'] in ['manager', 'admin']:
        try:
            df_leaves = read_data("leaves")
            if not df_leaves.empty:
                pending_count = len(df_leaves[df_leaves['status'] == '待審核'])
                if pending_count > 0:
                    st.toast(f"🔔 您有 {pending_count} 筆假單待審核！", icon="⚠️")
        except: pass

    # --- 側邊欄 ---
    st.sidebar.markdown(f"### {ORG_NAME}")
    if pending_count > 0: st.sidebar.error(f"⚠️ 待審案件: {pending_count} 筆")
    st.sidebar.divider()
    
    st.sidebar.title(f"👤 {user_full['name']}")
    st.sidebar.text(f"{user_full['title']}")
    st.sidebar.caption(f"📅 到職日: {user_full.get('onboard_date', '未設定')}")
    st.sidebar.divider()
    
    st.sidebar.markdown("#### 假勤存摺")
    c1, c2 = st.sidebar.columns(2)
    c1.metric("補休", f"{balances['balance']}", help="請於一年內休畢")
    c2.metric("特休剩", f"{remaining_annual}", help=f"年度總額: {entitled_annual}")
    c3, c4 = st.sidebar.columns(2)
    c3.metric("病假剩", f"{remaining_sick}", help="法定半薪病假上限 30 天")
    
    if balances['marriage'] > 0: st.sidebar.info(f"💍 婚假餘額: {balances['marriage']} 天")
    if balances['funeral'] > 0: st.sidebar.info(f"🙏 喪假餘額: {balances['funeral']} 天")
    if balances['maternity'] > 0: st.sidebar.info(f"👶 產假餘額: {balances['maternity']} 天")
    
    if balances['balance'] > 0:
        st.sidebar.warning("⚠️ 溫馨提醒：補休請於產生後一年內休畢。")

    if st.sidebar.button("登出"):
        st.session_state['user'] = None
        st.rerun()

    menu = st.sidebar.radio("功能", ["打卡作業", "請假申請", "紀錄查詢"] + (["權限管理/給假", "主管審核", "考勤月報表"] if user['role'] in ['manager', 'admin'] else []))

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
        st.info(f"目前額度：特休 {remaining_annual}天 | 補休 {balances['balance']}天 | 病假剩 {remaining_sick}天")
        with st.form("l"):
            lt = st.selectbox("假別", ["特休", "補休", "病假", "事假", "婚假", "喪假", "產假"])
            sd = st.date_input("日期")
            d = st.number_input("天數", 0.5, step=0.5)
            sess = "全天"
            if d == 0.5:
                st.info("💡 您選擇了半天，請記得選擇下方「時段」喔！")
                sess = st.radio("時段", ["上午", "下午"], horizontal=True)
            rsn = st.text_area("事由")
            st.markdown(f"**確認申請內容：** `{sd}` `({sess})` - `{lt}` `{d} 天`")
            
            if st.form_submit_button("送出申請"):
                error_msg = ""
                if lt == "補休" and balances['balance'] < d: error_msg = "補休餘額不足"
                elif lt == "婚假" and balances['marriage'] < d: error_msg = "婚假餘額不足"
                elif lt == "喪假" and balances['funeral'] < d: error_msg = "喪假餘額不足"
                elif lt == "產假" and balances['maternity'] < d: error_msg = "產假餘額不足"
                elif lt == "病假" and remaining_sick < d: st.warning("⚠️ 病假已超過法定 30 天，請確認。")
                
                if error_msg:
                    st.error(f"❌ {error_msg}")
                else:
                    append_data("leaves", [user['username'], lt, str(sd), d, sess, rsn, '待審核', ''])
                    st.success("已送出申請！")

    elif menu == "紀錄查詢":
        st.header("📅 紀錄")
        df_users = read_data("users") # 讀取使用者名單供對照
        name_map = dict(zip(df_users['username'], df_users['name']))
        
        # === v9.0 新增月曆分頁 ===
        t_cal, t1, t2, t3 = st.tabs(["🗓️ 行事曆", "打卡明細", "請假明細", "加班/給假明細"])
        
        with t_cal:
            st.markdown("#### 📅 員工請假概況")
            df_all_leaves = read_data("leaves")
            render_calendar_ui(df_all_leaves, df_users)

        # 查詢列表邏輯
        target = user['username']
        if user['role'] in ['manager', 'admin']:
            all_u_list = df_users['username'].tolist()
            target = st.selectbox("查詢特定員工", all_u_list, format_func=lambda x: f"{name_map.get(x, x)}", index=all_u_list.index(user['username']) if user['username'] in all_u_list else 0)
        
        with t1: 
            df = read_data("attendance")
            if not df.empty: st.dataframe(rename_columns_to_chinese(df[df['username'] == target]), use_container_width=True)
        with t2: 
            df = read_data("leaves")
            if not df.empty: st.dataframe(rename_columns_to_chinese(df[df['username'] == target]), use_container_width=True)
        with t3: 
            df = read_data("overtime")
            if not df.empty: st.dataframe(rename_columns_to_chinese(df[df['username'] == target]), use_container_width=True)

    elif menu == "權限管理/給假":
        st.header("🎁 假勤給予 / 加班登錄")
        with st.form("ot"):
            grant_type = st.selectbox("給予項目", ["補休 (加班)", "婚假", "喪假", "產假"])
            dt = st.date_input("日期")
            dys = st.number_input("天數", 0.5, step=0.5)
            rsn = st.text_input("事由 / 備註")
            
            df_users = read_data("users")
            active_users = df_users[df_users['status']=='在職']
            user_options = {row['username']: f"{row['name']} ({row['username']})" for i, row in active_users.iterrows()}
            sel = st.multiselect("對象", active_users['username'].tolist(), format_func=lambda x: user_options.get(x, x))
            
            if st.form_submit_button("確認發放") and sel:
                col_map = {"補休 (加班)": "balance", "婚假": "marriage", "喪假": "funeral", "產假": "maternity"}
                target_col = col_map[grant_type]
                for u in sel:
                    update_balance_multi(u, target_col, dys)
                    log_reason = f"[{grant_type}] {rsn}"
                    append_data("overtime", [u, str(dt), dys, log_reason, user['name']])
                st.success(f"已成功發放 {grant_type} 給 {len(sel)} 人！")

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
                            l_type = r['type']
                            d_val = -float(r['days'])
                            if l_type == '補休': update_balance_multi(r['username'], 'balance', d_val)
                            elif l_type == '婚假': update_balance_multi(r['username'], 'marriage', d_val)
                            elif l_type == '喪假': update_balance_multi(r['username'], 'funeral', d_val)
                            elif l_type == '產假': update_balance_multi(r['username'], 'maternity', d_val)
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
                st.dataframe(df_month[['time', '姓名', 'action']].rename(columns={'time': '時間', 'action': '動作'}), use_container_width=True)
            else: st.info("無資料")

if __name__ == "__main__":
    main()
