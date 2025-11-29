import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from io import BytesIO

# --- CONFIGURATION ---
ADMIN_PASSWORD = "auction_admin"  # <--- YOUR ADMIN PASSWORD
TOTAL_PURSE = 100000
MIN_SQUAD = 18
MAX_SQUAD = 25
MIN_BID_R1 = 1000
MIN_BID_R2 = 500
TEAMS = ["CSK", "MI", "RCB", "KKR"]

# --- GOOGLE SHEETS SETUP ---
SPREADSHEET_NAME = "Auction" 
SHEET_TAB_NAME = "Sheet1"

# --- STREAMLIT CONFIG ---
st.set_page_config(page_title="Cricket Auction 2025", layout="wide", page_icon="🏏")

# --- CONNECTION HANDLING ---
@st.cache_resource
def get_sheet():
    # Try Cloud Secrets first (Production)
    try:
        if "gcp_service_account" in st.secrets:
            dict_creds = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict_creds, ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
            client = gspread.authorize(creds)
            return client.open(SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)
    except:
        pass
    # Fallback to Local JSON (Testing)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)
    return sheet

try:
    sheet = get_sheet()
except Exception as e:
    st.error(f"❌ Connection Failed: {e}")
    st.stop()

# --- HELPER: IMAGE LOADER ---
@st.cache_data(show_spinner=False) 
def load_image_from_drive(url):
    if pd.isna(url) or not isinstance(url, str): return None
    file_id = None
    if "id=" in url: file_id = url.split("id=")[-1].split("&")[0]
    elif "/d/" in url:
        try: file_id = url.split("/d/")[1].split("/")[0]
        except: pass
    if file_id:
        try:
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            response = requests.get(download_url)
            if response.status_code == 200: return BytesIO(response.content)
        except: return None
    return None

# --- LOGIC: TEAM STATS ---
def calculate_team_stats(df, current_min_bid):
    stats = {team: {'spent': 0, 'count': 0} for team in TEAMS}
    sold_df = df[df['Status'] == 'Sold'].copy()
    if not sold_df.empty:
        sold_df['Sold Price'] = pd.to_numeric(sold_df['Sold Price'], errors='coerce').fillna(0)
        grouped = sold_df.groupby('Team Name').agg({'Sold Price': 'sum', 'Player Name': 'count'})
        for team in grouped.index:
            if team in stats:
                stats[team]['spent'] = grouped.loc[team, 'Sold Price']
                stats[team]['count'] = grouped.loc[team, 'Player Name']
    
    final_stats = []
    for team, data in stats.items():
        spent = data['spent']
        count = data['count']
        remaining = TOTAL_PURSE - spent
        needed = max(0, MIN_SQUAD - count)
        can_pick = count < MAX_SQUAD
        if count >= MAX_SQUAD: max_bid = 0
        elif count >= MIN_SQUAD: max_bid = remaining
        else: max_bid = remaining - ((needed - 1) * current_min_bid)
            
        final_stats.append({
            "Team": team,
            "Purse Left": remaining,
            "Players": count,
            "Max Bid": max_bid,
            "Status": "Active" if can_pick else "FULL"
        })
    return pd.DataFrame(final_stats).set_index("Team")

# --- MAIN APP ---
def main():
    # 1. Fetch & Clean Data
    data = sheet.get_all_values()
    headers = data.pop(0)
    df = pd.DataFrame(data, columns=headers)
    df.columns = df.columns.str.strip() 
    
    # Priority Cleaning
    if "Set Priority" not in df.columns: df["Set Priority"] = 100
    df["Set Priority"] = pd.to_numeric(df["Set Priority"], errors='coerce').fillna(100)
    if "Unsold Priority" not in df.columns: df["Unsold Priority"] = 2
    df["Unsold Priority"] = pd.to_numeric(df["Unsold Priority"], errors='coerce').fillna(2)

    # Phase Detection
    r1_mask = (df['Status'] != 'Sold') & (df['Status'] != 'Unsold')
    pool_r1 = df[r1_mask]
    pool_r2 = df[df['Status'] == 'Unsold']
    pool_r2_p1 = pool_r2[pool_r2["Unsold Priority"] == 1]
    
    current_phase = "UNKNOWN"
    active_pool = pd.DataFrame()
    min_bid = 0
    phase_color = "grey"
    
    if not pool_r1.empty:
        current_set = pool_r1["Set Priority"].min()
        active_pool = pool_r1[pool_r1["Set Priority"] == current_set]
        current_phase = f"ROUND 1 (SET {int(current_set)})"
        min_bid = MIN_BID_R1
        phase_color = "green"
    elif not pool_r2_p1.empty:
        current_phase = "ROUND 2 (PRIORITY UNSOLD)"
        active_pool = pool_r2_p1
        min_bid = MIN_BID_R2
        phase_color = "red"
    elif not pool_r2.empty:
        current_phase = "ROUND 2 (STANDARD UNSOLD)"
        active_pool = pool_r2
        min_bid = MIN_BID_R2
        phase_color = "orange"
    else:
        current_phase = "AUCTION COMPLETE"
        phase_color = "grey"

    # Calculate Stats
    team_stats = calculate_team_stats(df, min_bid)

    # --- SIDEBAR (Visible to ALL) ---
    with st.sidebar:
        # 1. Admin Login
        with st.expander("🔐 Admin Access", expanded=False):
            password = st.text_input("Password", type="password")
            is_admin = (password == ADMIN_PASSWORD)
            if is_admin: st.success("Admin Active")
        
        st.divider()
        
        # 2. Standings
        st.header("🏆 Standings")
        st.dataframe(team_stats[['Players', 'Purse Left', 'Max Bid']], height=200)
        
        st.divider()

        # 3. Squad Lists
        st.header("📋 Squads")
        sold_players = df[df['Status'] == 'Sold'].copy()
        for team in TEAMS:
            team_squad = sold_players[sold_players['Team Name'] == team]
            with st.expander(f"{team} ({len(team_squad)})"):
                for _, row in team_squad.iterrows():
                    st.write(f"• {row['Player Name']} (**{row['Sold Price']}**)")
        
        # 4. Unsold List
        st.divider()
        unsold_df = df[df['Status'] == 'Unsold'].copy().sort_values(['Unsold Priority', 'Player Name'])
        with st.expander(f"🚫 Unsold ({len(unsold_df)})"):
            for _, row in unsold_df.iterrows():
                icon = "🔥" if row['Unsold Priority'] == 1 else ""
                st.write(f"• {icon} {row['Player Name']}")

    # --- MAIN PAGE ---
    st.title("🏏 Saturday Premier League 2025")
    st.markdown(f":{phase_color}[**PHASE: {current_phase} | Min Bid: ₹{min_bid}**]")

    # --- ADMIN VIEW ---
    if is_admin:
        col1, col2 = st.columns([1, 2])
        if 'current_idx' not in st.session_state: st.session_state.current_idx = None

        with col1:
            disabled = active_pool.empty
            if st.button("🎲 PICK NEXT PLAYER", type="primary", disabled=disabled):
                if not active_pool.empty:
                    st.session_state.current_idx = active_pool.sample(1).index[0]
                else:
                    st.session_state.current_idx = None
                    st.balloons()
                    st.success("Phase Complete")

        if st.session_state.current_idx is not None:
            idx = st.session_state.current_idx
            if idx not in df.index: st.session_state.current_idx = None; st.rerun()
            player = df.loc[idx]

            st.divider()
            c1, c2 = st.columns([1, 1])
            
            with c1:
                img_data = load_image_from_drive(player.get('Upload your image', ''))
                if img_data: st.image(img_data)
                else: st.image("https://via.placeholder.com/300?text=No+Image")
                
                st.subheader(player['Player Name'])
                st.caption(f"{player['Primary Role']} | {player['Batting Style']}")
                
                if player.get('Status') == 'Unsold': st.warning("⚠️ Round 2: Unsold")
                if pd.notna(player.get('Set Priority')) and player.get('Status') != 'Unsold':
                     st.info(f"Set: {int(player['Set Priority'])}")

            with c2:
                st.info("💰 BIDDING CONSOLE")
                sel_team = st.selectbox("Buying Team", TEAMS)
                curr_stat = team_stats.loc[sel_team]
                
                m1, m2 = st.columns(2)
                m1.metric("Purse Left", f"{curr_stat['Purse Left']:,}")
                m2.metric("Max Bid", f"{curr_stat['Max Bid']:,}")
                
                with st.form("bid"):
                    bid = st.number_input("Price", min_value=0, step=500)
                    
                    b1, b2 = st.columns(2)
                    sold = b1.form_submit_button("✅ SOLD", type="primary")
                    unsold = b2.form_submit_button("❌ UNSOLD")

                    if sold:
                        errs = []
                        if bid < min_bid: errs.append("Bid too low")
                        if bid > curr_stat['Max Bid']: errs.append("Exceeds Max Bid")
                        
                        if not errs:
                            r = idx + 2
                            sheet.update_cell(r, headers.index("Status")+1, "Sold")
                            sheet.update_cell(r, headers.index("Sold Price")+1, bid)
                            sheet.update_cell(r, headers.index("Team Name")+1, sel_team)
                            st.success("Sold!")
                            st.session_state.current_idx = None
                            st.rerun()
                        else: st.error(errs[0])
                    
                    if unsold:
                         r = idx + 2
                         sheet.update_cell(r, headers.index("Status")+1, "Unsold")
                         st.warning("Unsold")
                         st.session_state.current_idx = None
                         st.rerun()
    
    # --- VIEWER VIEW ---
    else:
        st.divider()
        st.info("👋 Welcome! The auction is live. Use the sidebar 👈 to check Team Standings and Squads.")
        # Fixed: Removed width argument entirely to use default safe settings
        st.image("https://images.unsplash.com/photo-1531415074968-036ba1b575da?q=80&w=2067&auto=format&fit=crop", caption="Live Auction") 

if __name__ == "__main__":
    main()