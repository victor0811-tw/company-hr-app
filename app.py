import streamlit as st
import pandas as pd
import gspread
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os
import time
import calendar

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
def calculate_tenure(onboard_date_str):
    """計算年資 (回傳字串: X年Y個月)"""
    try:
        onboard = datetime.strptime(str(onboard_date_str), "%Y-%m-%d")
        today = datetime.now()
        diff = relativedelta(today, onboard)
        return f"{diff.years}年 {diff.months}個月"
    except:
        return "未設定"

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
        if col not in df.columns: df[col] = 0.0
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

def update_user_profile(user_data):
    """更新使用者個人資料"""
    df = read_data("users")
    username = user_data['username']
    
    # 確保所有欄位都存在
    cols = ['username', 'password', 'role', 'name', 'title', 'onboard_date', 'status', 
            'gender', 'dept', 'birthday', 'id_card', 'mobile', 'phone', 'address', 'email', 'school', 'resign_date']
    for c in cols:
        if c not in df.columns: df[c] = ""
            
    if username in df['username'].values:
        # 更新現有資料
        idx = df[df['username'] == username].index[0]
        for key, value in user_data.items():
            if key in df.columns:
                df.at[idx, key] = str(value)
    else:
        # 新增使用者 (append)
        new_row = pd.DataFrame([user_data])
        df = pd.concat([df, new_row], ignore_index=True)
        
    overwrite_data("users", df)

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

def render_calendar_ui(df_leaves, df_users):
    if 'cal_year' not in st.session_state:
        st.session_state['cal_year'] = datetime.now().year
        st.session_state['cal_month'] = datetime.now().month
    def change_month(amount):
        st.session_state['cal_month'] += amount
        if st.session_state['cal_month'] > 12:
            st.session_state['cal_month'] = 1
            st.session_state['cal_year'] += 1
        elif st.session_state['cal_month'] < 1:
            st.session_state['cal_month'] = 12
            st.session_state['cal_year'] -= 1
    
    col_prev, col_date, col_next = st.columns([1, 5, 1])
    with col_prev: st.button("◀", on_click=change_month, args=(-1,), use_container_width=True)
    with col_date: st.markdown(f"<h3 style='text-align: center;'>{st.session_state['cal_year']} 年 {st.session_state['cal_month']} 月</h3>", unsafe_allow_html=True)
    with col_next: st.button("▶", on_click=change_month, args=(1,), use_container_width=True)

    target_ym = f"{st.session_state['cal_year']}-{st.session_state['cal_month']:02d}"
    name_map = dict(zip(df_users['username'], df_users['name']))
    events_map = {}
    if not df_leaves.empty:
        approved = df_leaves[df_leaves['status'] == '已核准']
        for _, row in approved.iterrows():
            if str(row['start_date']).startswith(target_ym):
                try:
                    day_int = int(str(row['start_date']).split('-')[2])
                    u_name = name_map.get(row['username'], row['username'])
                    info = f"{u_name}: {row['type']} {row['days']}天 ({row['session']})"
                    if day_int not in events_map: events_map[day_int] = []
                    events_map[day_int].append(info)
                except: pass

    cols = st.columns(7)
    weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    for i, w in enumerate(weekdays): cols[i].markdown(f"**{w}**", unsafe_allow_html=True)
    cal = calendar.monthcalendar(st.session_state['cal_year'], st.session_state['cal_month'])
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            with cols[i]:
                if day != 0:
                    if day in events_map:
                        tooltip_text = "\n".join(events_map[day])
                        st.markdown(f"<div style='background-color:#ffebee;border-radius:5px;padding:5px;text-align:center;border:1px solid #ffcdd2;' title='{tooltip_text}'><strong>{day}</strong><br><span style='color:red;font-size:0.8em;'>🔴 {len(events_map[day])}人</span></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding:5px;text-align:center;'>{day}</div>", unsafe_allow_html=True)
    st.markdown("---")

# --- 3. 新增功能：生成 A4 HTML ---
def generate_a4_html(info):
    """產生符合 A4 列印格式的 HTML"""
    html_content = f"""
    <style>
        @media print {{
            @page {{ size: A4; margin: 1cm; }}
            header, footer, aside, .stAppHeader {{ display: none !important; }}
            body {{ font-family: "Microsoft JhengHei", sans-serif; -webkit-print-color-adjust: exact; }}
        }}
        .a4-container {{
            width: 21cm; min-height: 29.7cm; padding: 1cm; margin: auto; background: white; 
            border: 1px solid #ddd; box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        .card-title {{ text-align: center; font-size: 24px; font-weight: bold; margin-bottom: 20px; border-bottom: 2px solid #000; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        td, th {{ border: 1px solid #333; padding: 10px; font-size: 14px; vertical-align: middle; }}
        .label {{ background-color: #f0f0f0; font-weight: bold; width: 15%; }}
        .value {{ width: 35%; }}
        .photo-area {{ width: 20%; text-align: center; color: #999; }}
        .section-header {{ background-color: #e0e0e0; text-align: center; font-weight: bold; padding: 5px; }}
    </style>
    
    <div class="a4-container">
        <div class="card-title">員工資料卡</div>
        
        <div class="section-header">個人資料</div>
        <table>
            <tr>
                <td class="label">姓名</td><td class="value">{info.get('name', '')}</td>
                <td class="label">到職日期</td><td class="value">{info.get('onboard_date', '')}</td>
                <td rowspan="4" class="photo-area">照片</td>
            </tr>
            <tr>
                <td class="label">身份證字號</td><td class="value">{info.get('id_card', '')}</td>
                <td class="label">出生年月日</td><td class="value">{info.get('birthday', '')}</td>
            </tr>
            <tr>
                <td class="label">性別</td><td class="value">{info.get('gender', '')}</td>
                <td class="label">年資</td><td class="value">{calculate_tenure(info.get('onboard_date', ''))}</td>
            </tr>
             <tr>
                <td class="label">通訊地址</td><td colspan="3">{info.get('address', '')}</td>
            </tr>
            <tr>
                <td class="label">聯絡電話</td><td class="value">{info.get('phone', '')}</td>
                <td class="label">手機</td><td class="value">{info.get('mobile', '')}</td>
                <td>電子郵件</td>
            </tr>
            <tr>
                <td class="label">最高學歷</td><td class="value">{info.get('school', '')}</td>
                <td class="label">電子郵件</td><td colspan="2">{info.get('email', '')}</td>
            </tr>
             <tr>
                <td class="label">離職日期</td><td class="value">{info.get('resign_date', '')}</td>
                <td class="label">狀態</td><td colspan="2">{info.get('status', '')}</td>
            </tr>
        </table>
        
        <br>
        <div class="section-header">部門與薪資</div>
        <table>
            <tr>
                <td class="label">部門</td><td class="value">{info.get('dept', '')}</td>
                <td class="label">職稱</td><td class="value">{info.get('title', '')}</td>
            </tr>
            <tr>
                <td class="label">勞保投保日</td><td class="value">{info.get('onboard_date', '')} (預設)</td>
                <td class="label">約定薪資</td><td class="value">******</td>
            </tr>
        </table>
        
        <br><br><br>
        <div style="text-align: right; margin-top: 50px; font-size: 16px;">
            <p>已確認以上資料無誤，於 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 年 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 月 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 日 親自填寫</p>
            <br>
            <p>簽章：__________________________</p>
        </div>
    </div>
    """
    return html_content

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

    pending_count = 0
    if user['role'] in ['manager', 'admin']:
        try:
            df_leaves = read_data("leaves")
            if not df_leaves.empty:
                pending_count = len(df_leaves[df_leaves['status'] == '待審核'])
                if pending_count > 0: st.toast(f"🔔 有 {pending_count} 筆假單待審核！", icon="⚠️")
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
    c2.metric("特休剩", f"{remaining_annual}", help=f"總額: {entitled_annual}")
    c3, c4 = st.sidebar.columns(2)
    c3.metric("病假剩", f"{remaining_sick}", help="半薪上限 30 天")
    
    if balances['balance'] > 0: st.sidebar.warning("⚠️ 補休請於一年內休畢")
    if st.sidebar.button("登出"):
        st.session_state['user'] = None
        st.rerun()

    # 選單
    menu_options = ["打卡作業", "請假申請", "紀錄查詢"]
    if user['role'] in ['manager', 'admin']:
        # 新增 "人事資料卡" 功能
        menu_options += ["權限管理/給假", "主管審核", "人事資料卡", "考勤月報表"]
    
    menu = st.sidebar.radio("功能", menu_options)

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
                st.info("💡 選擇半天請記得選時段")
                sess = st.radio("時段", ["上午", "下午"], horizontal=True)
            rsn = st.text_area("事由")
            st.markdown(f"**確認申請：** `{sd}` `({sess})` - `{lt}` `{d} 天`")
            if st.form_submit_button("送出"):
                err = ""
                if lt == "補休" and balances['balance'] < d: err = "補休不足"
                elif lt == "婚假" and balances['marriage'] < d: err = "婚假不足"
                elif lt == "喪假" and balances['funeral'] < d: err = "喪假不足"
                elif lt == "產假" and balances['maternity'] < d: err = "產假不足"
                elif lt == "病假" and remaining_sick < d: st.warning("⚠️ 病假超過30天")
                if err: st.error(err)
                else:
                    append_data("leaves", [user['username'], lt, str(sd), d, sess, rsn, '待審核', ''])
                    st.success("已送出")

    elif menu == "紀錄查詢":
        st.header("📅 紀錄")
        df_users = read_data("users")
        name_map = dict(zip(df_users['username'], df_users['name']))
        t_cal, t1, t2, t3 = st.tabs(["🗓️ 行事曆", "打卡", "請假", "加班"])
        with t_cal:
            st.markdown("#### 📅 請假概況")
            render_calendar_ui(read_data("leaves"), df_users)
        
        target = user['username']
        if user['role'] in ['manager', 'admin']:
            all_u = df_users['username'].tolist()
            target = st.selectbox("查詢對象", all_u, format_func=lambda x: name_map.get(x, x), index=all_u.index(user['username']) if user['username'] in all_u else 0)
        
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
        st.header("🎁 假勤給予")
        with st.form("ot"):
            grant = st.selectbox("項目", ["補休 (加班)", "婚假", "喪假", "產假"])
            dt = st.date_input("日期")
            dys = st.number_input("天數", 0.5, step=0.5)
            rsn = st.text_input("事由")
            df_users = read_data("users")
            active = df_users[df_users['status']=='在職']
            u_map = {r['username']: f"{r['name']} ({r['username']})" for i, r in active.iterrows()}
            sel = st.multiselect("對象", active['username'].tolist(), format_func=lambda x: u_map.get(x, x))
            if st.form_submit_button("發放") and sel:
                col_map = {"補休 (加班)": "balance", "婚假": "marriage", "喪假": "funeral", "產假": "maternity"}
                for u in sel:
                    update_balance_multi(u, col_map[grant], dys)
                    append_data("overtime", [u, str(dt), dys, f"[{grant}] {rsn}", user['name']])
                st.success("完成")

    # === 新增功能：人事資料卡 ===
    elif menu == "人事資料卡":
        st.header("📇 人事資料管理")
        
        # 1. 選擇要操作的員工
        df_users = read_data("users")
        user_list = df_users['username'].tolist()
        # 顯示中文名供選擇
        u_options = {r['username']: f"{r['name']} ({r['username']})" for i, r in df_users.iterrows()}
        
        c_sel, c_act = st.columns([3, 1])
        with c_sel:
            target_u = st.selectbox("選擇員工", user_list, format_func=lambda x: u_options.get(x, x))
        
        # 取得該員工目前資料
        current_info = df_users[df_users['username'] == target_u].iloc[0].to_dict()
        
        tab_edit, tab_print = st.tabs(["✏️ 編輯資料", "🖨️ 預覽與列印"])
        
        with tab_edit:
            with st.form("profile_form"):
                st.subheader(f"編輯：{current_info.get('name')}")
                c1, c2 = st.columns(2)
                with c1:
                    new_name = st.text_input("姓名", current_info.get('name'))
                    new_gender = st.selectbox("性別", ["男", "女", "其他"], index=["男", "女", "其他"].index(current_info.get('gender')) if current_info.get('gender') in ["男", "女", "其他"] else 0)
                    new_id = st.text_input("身份證字號", current_info.get('id_card'))
                    new_birth = st.date_input("生日", datetime.strptime(current_info.get('birthday'), "%Y-%m-%d") if current_info.get('birthday') else None)
                with c2:
                    new_dept = st.text_input("部門", current_info.get('dept'))
                    new_title = st.text_input("職稱", current_info.get('title'))
                    new_onboard = st.date_input("到職日", datetime.strptime(current_info.get('onboard_date'), "%Y-%m-%d") if current_info.get('onboard_date') else datetime.now())
                    new_status = st.selectbox("狀態", ["在職", "離職"], index=0 if current_info.get('status')=="在職" else 1)
                
                st.markdown("---")
                c3, c4 = st.columns(2)
                with c3:
                    new_phone = st.text_input("電話", current_info.get('phone'))
                    new_mobile = st.text_input("手機", current_info.get('mobile'))
                    new_email = st.text_input("Email", current_info.get('email'))
                with c4:
                    new_addr = st.text_input("地址", current_info.get('address'))
                    new_school = st.text_input("最高學歷", current_info.get('school'))
                    new_resign = st.text_input("離職日 (選填)", current_info.get('resign_date'))

                if st.form_submit_button("💾 儲存資料"):
                    updated_data = {
                        'username': target_u, # Key
                        'name': new_name, 'gender': new_gender, 'id_card': new_id, 
                        'birthday': str(new_birth), 'dept': new_dept, 'title': new_title,
                        'onboard_date': str(new_onboard), 'status': new_status,
                        'phone': new_phone, 'mobile': new_mobile, 'email': new_email,
                        'address': new_addr, 'school': new_school, 'resign_date': new_resign
                    }
                    update_user_profile(updated_data)
                    st.success("資料已更新！請切換到「預覽與列印」分頁查看。")
                    time.sleep(1)
                    st.rerun()

        with tab_print:
            st.info("💡 提示：此畫面模擬 A4 紙張。請按瀏覽器的「列印 (Ctrl+P)」並選擇「儲存為 PDF」或直接列印。")
            # 產生 HTML
            html_code = generate_a4_html(current_info)
            # 顯示 HTML (使用 unsafe_allow_html 渲染 CSS)
            st.markdown(html_code, unsafe_allow_html=True)

    elif menu == "主管審核":
        st.header("📑 審核")
        lv = read_data("leaves")
        df_users = read_data("users")
        name_map = dict(zip(df_users['username'], df_users['name']))
        if not lv.empty:
            pending = lv[lv['status']=='待審核']
            if pending.empty: st.info("無待審核")
            else:
                for i, r in pending.iterrows():
                    emp = name_map.get(r['username'], r['username'])
                    t_str = f"{emp}：{r['type']} {r['days']} 天 ({r['start_date']})"
                    with st.expander(t_str):
                        st.write(f"事由: {r['reason']}")
                        c1, c2 = st.columns(2)
                        if c1.button("准", key=f"ok_{i}"):
                            lv.at[i, 'status'] = '已核准'
                            d_val = -float(r['days'])
                            col_map = {'補休':'balance','婚假':'marriage','喪假':'funeral','產假':'maternity'}
                            if r['type'] in col_map: update_balance_multi(r['username'], col_map[r['type']], d_val)
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
