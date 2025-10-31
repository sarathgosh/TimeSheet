
# timesheet_webui_autofill_v2.py
# Streamlit Web UI — ZC-030 Remote Engineer Timesheet
# Features:
# - Employee master auto-fill (IC#, Department, Job Title, RM)
# - NEW: Auto-fill on new rows only -> Date, Day, Start Time, End Time
#        * Triggered when you append rows via sidebar or add rows inside the editor
#        * Defaults: Date today for first new row (or last date + 1), Day from Date, Start 09:00, End 18:00

import io
from datetime import time, date, datetime, timedelta
from typing import Tuple, Optional, Dict

import pandas as pd
import streamlit as st

# ------------------------------ Master Directory Helpers ------------------------------

BUILTIN_EMPLOYEES = [
    {"Employee Name": "Sarath Gosh", "IC#": "S1234567A", "Department": "Engineering", "Job Title": "Remote Engineer", "Reporting Manager": "Shailesh"},
    {"Employee Name": "Shri Shailesh", "IC#": "S7654321B", "Department": "Operations", "Job Title": "Manager", "Reporting Manager": "—"},
]

REQUIRED_COLS = ["Employee Name", "IC#", "Department", "Job Title", "Reporting Manager"]

def normalize_master(df: pd.DataFrame) -> pd.DataFrame:
    colmap = {}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc in ["employee name", "name", "full name"]:
            colmap[c] = "Employee Name"
        elif lc in ["ic", "ic#", "id", "id#", "nric"]:
            colmap[c] = "IC#"
        elif lc in ["dept", "department"]:
            colmap[c] = "Department"
        elif lc in ["job title", "title", "designation"]:
            colmap[c] = "Job Title"
        elif lc in ["rm", "reporting manager", "manager", "supervisor"]:
            colmap[c] = "Reporting Manager"
    df2 = df.rename(columns=colmap)
    for r in REQUIRED_COLS:
        if r not in df2.columns:
            df2[r] = ""
    df2 = df2[REQUIRED_COLS].copy()
    df2 = df2[df2["Employee Name"].astype(str).str.strip() != ""]
    df2 = df2.drop_duplicates(subset=["Employee Name"], keep="last").reset_index(drop=True)
    return df2

def master_to_dict(df: pd.DataFrame) -> Dict[str, Dict[str, str]]:
    d = {}
    for _, row in df.iterrows():
        name = str(row["Employee Name"]).strip()
        d[name] = {
            "IC#": str(row["IC#"]) if pd.notna(row["IC#"]) else "",
            "Department": str(row["Department"]) if pd.notna(row["Department"]) else "",
            "Job Title": str(row["Job Title"]) if pd.notna(row["Job Title"]) else "",
            "Reporting Manager": str(row["Reporting Manager"]) if pd.notna(row["Reporting Manager"]) else "",
        }
    return d

# ------------------------------ Timesheet Helpers ------------------------------

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def parse_break_to_hours(break_str: str) -> float:
    if not isinstance(break_str, str):
        return 0.0
    s = break_str.strip()
    if not s: return 0.0
    try:
        parts = s.split(":")
        if len(parts) != 2: return 0.0
        h = int(parts[0]); m = int(parts[1])
        return max(0.0, float(h) + float(m)/60.0)
    except Exception:
        return 0.0

def hhmm_or_blank(t) -> str:
    if isinstance(t, time):
        return t.strftime("%H:%M")
    if isinstance(t, str) and t:
        s = t.strip()
        try:
            if ":" in s:
                hh, mm = s.split(":")
                return f"{int(hh):02d}:{int(mm):02d}"
            if len(s) in (3,4):
                s = s.zfill(4)
                return f"{int(s[:2]):02d}:{int(s[2:]):02d}"
        except Exception:
            pass
        return s
    return ""

def to_time_obj(s: str) -> Optional[time]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        if ":" in s:
            hh, mm = s.split(":")
            return time(int(hh), int(mm))
        if len(s) in (3,4):
            s = s.zfill(4)
            return time(int(s[:2]), int(s[2:]))
    except Exception:
        return None
    return None

def calc_row_hours(start_str: str, end_str: str, break_str: str) -> float:
    start_t = to_time_obj(start_str)
    end_t   = to_time_obj(end_str)
    if not start_t or not end_t:
        return 0.0
    start_minutes = start_t.hour * 60 + start_t.minute
    end_minutes   = end_t.hour * 60 + end_t.minute
    if end_minutes < start_minutes:
        end_minutes += 24*60  # crossed midnight
    work_minutes = max(0, end_minutes - start_minutes)
    break_hours = parse_break_to_hours(break_str)
    return round(max(0.0, (work_minutes/60.0) - break_hours), 2)

def init_session():
    if "employee" not in st.session_state:
        st.session_state.employee = {
            "Employee Name": "", "IC#": "", "Department": "", "Job Title": "",
            "Reporting Manager": "", "Review Month": "", "Year": "", "Date": "",
        }
    if "table" not in st.session_state:
        st.session_state.table = pd.DataFrame({
            "Date": ["" for _ in range(10)],
            "Day": ["" for _ in range(10)],
            "Start Time": ["" for _ in range(10)],
            "End Time": ["" for _ in range(10)],
            "Break (hh:mm)": ["" for _ in range(10)],
            "Work Hours": [0.0 for _ in range(10)],
            "Description of Work": ["" for _ in range(10)],
        })
    if "total_hours" not in st.session_state:
        st.session_state.total_hours = 0.0
    if "employee_master" not in st.session_state:
        builtin_df = pd.DataFrame(BUILTIN_EMPLOYEES)
        st.session_state.employee_master = normalize_master(builtin_df)
        st.session_state.employee_master_dict = master_to_dict(st.session_state.employee_master)
    if "last_emp_name" not in st.session_state:
        st.session_state.last_emp_name = ""
    if "last_len" not in st.session_state:
        st.session_state.last_len = len(st.session_state.table)

def recalc_hours(df: pd.DataFrame):
    df = df.copy()
    total = 0.0
    for i, row in df.iterrows():
        hrs = calc_row_hours(
            hhmm_or_blank(row.get("Start Time", "")),
            hhmm_or_blank(row.get("End Time", "")),
            str(row.get("Break (hh:mm)", "") or ""),
        )
        df.at[i, "Work Hours"] = hrs
        total += hrs
    return df, round(total, 2)

# ------------------------------ Auto-fill for NEW rows only ------------------------------

def str_to_date(d: str) -> Optional[date]:
    s = (d or "").strip()
    if not s: return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None

def date_to_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def weekday_abbr(d: date) -> str:
    return DAYS[d.weekday()]  # 0=Mon

def next_date(prev: Optional[date]) -> date:
    return (prev + timedelta(days=1)) if prev else date.today()

def get_last_non_empty_date(df: pd.DataFrame) -> Optional[date]:
    if "Date" not in df.columns: return None
    for v in reversed(df["Date"].tolist()):
        dv = str_to_date(str(v))
        if dv: return dv
    return None

def autofill_new_rows(df: pd.DataFrame, old_len: int) -> pd.DataFrame:
    """Fill Date, Day, Start Time, End Time for rows added beyond old_len ONLY if blank."""
    if df is None or df.empty: return df
    df = df.copy()
    new_len = len(df)
    if new_len <= old_len:  # nothing added
        return df

    # Determine starting reference date
    ref_date = get_last_non_empty_date(df.iloc[:old_len]) or date.today()
    cur = ref_date

    for i in range(old_len, new_len):
        row = df.iloc[i]
        # Only fill if cell is blank
        if not str(row.get("Date", "")).strip():
            cur = next_date(cur) if i > old_len else cur  # first new row uses ref_date; subsequent rows +1
            df.at[i, "Date"] = date_to_str(cur)
        # Day from Date (if day blank)
        if not str(row.get("Day", "")).strip():
            dval = str_to_date(str(df.at[i, "Date"]))
            if dval:
                df.at[i, "Day"] = weekday_abbr(dval)
        # Start/End default
        if not str(row.get("Start Time", "")).strip():
            df.at[i, "Start Time"] = "09:00"
        if not str(row.get("End Time", "")).strip():
            df.at[i, "End Time"] = "18:00"
    return df

# ------------------------------ App ------------------------------

st.set_page_config(page_title="ZC-030 Timesheet (Auto-Fill v2)", page_icon="🗓️", layout="wide")
init_session()

st.title("🗓️ ZC-030 Remote Engineer Timesheet — Auto-Fill v2 (New Rows Only)")

with st.sidebar:
    st.header("👥 Employee Master")
    up = st.file_uploader("Upload Employee Master (CSV)", type=["csv"])
    if up is not None:
        try:
            df = pd.read_csv(up)
            norm = normalize_master(df)
            st.session_state.employee_master = norm
            st.session_state.employee_master_dict = master_to_dict(norm)
            st.success(f"Loaded {len(norm)} employees from CSV.")
        except Exception as e:
            st.error(f"Failed to parse CSV: {e}")

    st.divider()
    st.subheader("Rows")
    add_rows = st.number_input("Add rows", min_value=1, max_value=100, value=5, step=1)
    if st.button("➕ Append Rows"):
        # Append blank rows then auto-fill ONLY the appended section.
        before = len(st.session_state.table)
        extra = pd.DataFrame({c: [""]*add_rows for c in st.session_state.table.columns})
        st.session_state.table = pd.concat([st.session_state.table, extra], ignore_index=True)
        st.session_state.table = autofill_new_rows(st.session_state.table, before)
        st.session_state.last_len = len(st.session_state.table)

    if st.button("🧹 Clear All Rows"):
        st.session_state.table = st.session_state.table.iloc[0:0].copy()
        st.session_state.last_len = 0

    st.divider()
    st.header("📦 Export")
    if st.button("⬇️ Export to Excel", type="primary"):
        st.session_state.table, st.session_state.total_hours = recalc_hours(st.session_state.table)
        data = export_to_excel(st.session_state.employee, st.session_state.table)
        st.download_button(
            "Download ZC-030 Timesheet.xlsx",
            data=data,
            file_name="ZC-030 Remote Engineer Timesheet (Filled).xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ------------------------------ Employee Form ------------------------------

st.subheader("👤 Employee Information")
# Suggest names from master
name_options = [""] + sorted(list(st.session_state.employee_master_dict.keys()))
c1, c2 = st.columns([2,1])
emp_name_input = c1.selectbox("Employee Name (type to search)", options=name_options, index=name_options.index(st.session_state.employee.get("Employee Name","")) if st.session_state.employee.get("Employee Name","") in name_options else 0)
manual_name = c2.text_input("Or type a new name", value="" if emp_name_input else st.session_state.employee.get("Employee Name",""))
final_name = manual_name.strip() if manual_name.strip() else emp_name_input.strip()

# Auto-fill from master on name change
if "employee_master_dict" not in st.session_state:
    st.session_state.employee_master_dict = {}
if final_name != st.session_state.last_emp_name:
    st.session_state.employee["Employee Name"] = final_name
    if final_name in st.session_state.employee_master_dict:
        master = st.session_state.employee_master_dict[final_name]
        for k,v in master.items():
            if not st.session_state.employee.get(k, "").strip():
                st.session_state.employee[k] = v
    st.session_state.last_emp_name = final_name

col1, col2, col3, col4 = st.columns(4)
st.session_state.employee["IC#"] = col1.text_input("IC#", st.session_state.employee.get("IC#",""))
st.session_state.employee["Department"] = col2.text_input("Department", st.session_state.employee.get("Department",""))
st.session_state.employee["Job Title"] = col3.text_input("Job Title", st.session_state.employee.get("Job Title",""))
st.session_state.employee["Reporting Manager"] = col4.text_input("Reporting Manager", st.session_state.employee.get("Reporting Manager",""))

col5, col6, col7, col8 = st.columns(4)
st.session_state.employee["Review Month"] = col5.text_input("Review Month", st.session_state.employee.get("Review Month",""))
st.session_state.employee["Year"] = col6.text_input("Year", st.session_state.employee.get("Year",""))
st.session_state.employee["Date"] = col7.text_input("Date", st.session_state.employee.get("Date",""), placeholder="YYYY-MM-DD")
st.caption("Auto-fill: picking a name fills IC#/Dept/Title/RM. New rows auto-fill Date/Day/Start/End only.")

st.divider()

# ------------------------------ Work Log ------------------------------

st.subheader("🧾 Work Log")
edit_df = st.session_state.table.copy()

# If user adds rows directly via data_editor's built-in UI, detect length increase and auto-fill new tail only.
pre_len = st.session_state.last_len

try:
    cfg = {
        "Day": st.column_config.SelectboxColumn("Day", options=DAYS, help="Pick day of week", required=False),
        "Date": st.column_config.TextColumn("Date", help="YYYY-MM-DD", required=False),
        "Start Time": st.column_config.TextColumn("Start Time", help="hh:mm (e.g., 09:00)", required=False),
        "End Time": st.column_config.TextColumn("End Time", help="hh:mm (e.g., 18:00)", required=False),
        "Break (hh:mm)": st.column_config.TextColumn("Break (hh:mm)", help="hh:mm (e.g., 00:30)", required=False),
        "Work Hours": st.column_config.NumberColumn("Work Hours", help="Auto-calculated", step=0.25, disabled=True),
        "Description of Work": st.column_config.TextColumn("Description of Work", width="medium"),
    }
except Exception:
    cfg = None

edited = st.data_editor(
    edit_df,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config=cfg,
    key="data_editor",
)

# If editor grew in length, auto-fill new tail
post_len = len(edited)
if post_len > pre_len:
    edited = autofill_new_rows(edited, pre_len)

# Recalc hours and persist
calc_df, total = recalc_hours(edited)
st.session_state.table = calc_df
st.session_state.total_hours = total
st.session_state.last_len = len(calc_df)

st.info(f"**Total Hours:** {total:.2f}")
st.caption("New rows get default Date/Day/Start/End. Existing values are never overwritten.")
