
# timesheet_webui_autofill_v3.py
# Streamlit Web UI — ZC-030 Remote Engineer Timesheet
# Robust NEW-ROW auto-fill using hidden Row IDs (works for both sidebar append + editor "Add row").

import io
import uuid
from datetime import time, date, datetime, timedelta
from typing import Tuple, Optional, Dict, List

import pandas as pd
import streamlit as st

# ------------------------------ Employee Master ------------------------------

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

# ------------------------------ Time helpers ------------------------------

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

# ------------------------------ Session init ------------------------------

BASE_COLUMNS = ["Row ID","Date","Day","Start Time","End Time","Break (hh:mm)","Work Hours","Description of Work"]

def ensure_row_ids(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "Row ID" not in df.columns:
        df.insert(0, "Row ID", [str(uuid.uuid4()) for _ in range(len(df))])
    else:
        # Fill missing IDs (new editor rows)
        df["Row ID"] = df["Row ID"].apply(lambda x: str(x) if isinstance(x, str) and x.strip() else str(uuid.uuid4()))
    return df

def init_session():
    if "employee" not in st.session_state:
        st.session_state.employee = {
            "Employee Name": "", "IC#": "", "Department": "", "Job Title": "",
            "Reporting Manager": "", "Review Month": "", "Year": "", "Date": "",
        }
    if "table" not in st.session_state:
        st.session_state.table = pd.DataFrame({
            "Row ID": [str(uuid.uuid4()) for _ in range(10)],
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

# ------------------------------ Export ------------------------------

def export_to_excel(employee: dict, table: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="hh:mm", date_format="yyyy-mm-dd") as writer:
        sheet_name = "Timesheet"
        wb  = writer.book
        ws  = wb.add_worksheet(sheet_name)

        title_fmt = wb.add_format({"bold": True, "font_size": 16, "align": "center", "valign": "vcenter"})
        subtitle_fmt = wb.add_format({"bold": True, "font_size": 14, "align": "center"})
        sub_fmt   = wb.add_format({"bold": True, "font_size": 10})
        box_fmt   = wb.add_format({"border": 1, "valign": "vcenter"})
        label_fmt = wb.add_format({"bold": True})
        right_fmt = wb.add_format({"align": "right"})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#E6F3FF", "border": 1, "align": "center"})
        num_fmt = wb.add_format({"num_format": "0.00", "border": 1})
        time_fmt = wb.add_format({"num_format": "hh:mm", "border": 1})
        box = wb.add_format({"border": 1})

        ws.set_column("A:A", 12)
        ws.set_column("B:B", 10)
        ws.set_column("C:D", 12)
        ws.set_column("E:E", 13)
        ws.set_column("F:F", 12)
        ws.set_column("G:G", 60)

        ws.merge_range("A1:G1", "ZEALCORPS PTE LTD", title_fmt)
        ws.merge_range("A2:G2", "REMOTE ENGINEER TIMESHEET", subtitle_fmt)
        ws.write("A3", "Form No: ZC-030", sub_fmt)
        ws.write("B3", "Rev. No: 00", sub_fmt)

        ws.merge_range("A5:G5", "Employee Information", wb.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1}))
        ws.write("A6", "Employee Name:", label_fmt); ws.merge_range("B6:D6", employee.get("Employee Name",""), box_fmt)
        ws.write("E6", "IC#:", label_fmt);           ws.merge_range("F6:G6", employee.get("IC#",""), box_fmt)
        ws.write("A7", "Department:", label_fmt);    ws.merge_range("B7:D7", employee.get("Department",""), box_fmt)
        ws.write("E7", "Job Title:", label_fmt);     ws.merge_range("F7:G7", employee.get("Job Title",""), box_fmt)
        ws.write("A8", "Review Month:", label_fmt);  ws.merge_range("B8:D8", employee.get("Review Month",""), box_fmt)
        ws.write("E8", "Year:", label_fmt);          ws.merge_range("F8:G8", employee.get("Year",""), box_fmt)
        ws.write("A9", "Date:", label_fmt);          ws.merge_range("B9:D9", employee.get("Date",""), box_fmt)
        ws.write("E9", "Reporting Manager:", label_fmt); ws.merge_range("F9:G9", employee.get("Reporting Manager",""), box_fmt)

        headers = ["Date", "Day", "Start Time", "End Time", "Break (hh:mm)", "Work Hours", "Description of Work"]
        for col, h in enumerate(headers):
            ws.write(12, col, h, header_fmt)

        # Drop Row ID before export
        exp = table.copy()
        if "Row ID" in exp.columns:
            exp = exp.drop(columns=["Row ID"])
        if exp.empty:
            exp = pd.DataFrame(columns=headers)

        # Ensure all columns exist
        for h in headers:
            if h not in exp.columns:
                exp[h] = ""

        start_row = 13
        for i, (_, row) in enumerate(exp.iterrows()):
            r = start_row + i
            ws.write(r, 0, row.get("Date", ""), box)
            ws.write(r, 1, row.get("Day", ""), box)
            ws.write(r, 2, hhmm_or_blank(row.get("Start Time","")), time_fmt)
            ws.write(r, 3, hhmm_or_blank(row.get("End Time","")), time_fmt)
            ws.write(r, 4, str(row.get("Break (hh:mm)","")), box)
            try:
                wh = float(row.get("Work Hours", 0.0) or 0.0)
            except Exception:
                wh = 0.0
            ws.write(r, 5, wh, num_fmt)
            ws.write(r, 6, row.get("Description of Work",""), box)

        total_row = start_row + len(exp)
        ws.write(total_row, 4, "Total Hours:", right_fmt)
        ws.write_formula(total_row, 5, f"=SUM(F{start_row+1}:F{start_row+len(exp)})", num_fmt)

        ws.merge_range(total_row + 2, 0, total_row + 2, 2, "Emp Signature", box)
        ws.merge_range(total_row + 2, 3, total_row + 2, 4, "RM signature", box)
        ws.merge_range(total_row + 2, 5, total_row + 2, 6, "Date", box)

        readme = wb.add_worksheet("ReadMe")
        readme.write(0,0,"How to use")
        readme.write(1,0,"1) Employee Name can auto-fill details using a master CSV.")
        readme.write(2,0,"2) Add rows — new rows auto-fill Date/Day/Start/End.")
        readme.write(3,0,"3) Export to Excel.")
    output.seek(0)
    return output.read()

# ------------------------------ Calc ------------------------------

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

# ------------------------------ Autofill new rows (ID-based) ------------------------------

def detect_new_ids(old_df: pd.DataFrame, new_df: pd.DataFrame) -> List[str]:
    old_ids = set((old_df.get("Row ID") or []).tolist()) if "Row ID" in old_df.columns else set()
    new_ids = set((new_df.get("Row ID") or []).tolist()) if "Row ID" in new_df.columns else set()
    return [rid for rid in new_ids if rid not in old_ids]

def get_last_non_empty_date(df: pd.DataFrame) -> Optional[date]:
    if "Date" not in df.columns: return None
    for v in reversed(df["Date"].tolist()):
        dv = str_to_date(str(v))
        if dv: return dv
    return None

def autofill_rows_by_ids(df: pd.DataFrame, id_list: List[str]) -> pd.DataFrame:
    if not id_list: return df
    df = df.copy()
    # Determine base date from rows that are NOT new
    non_new = df[~df["Row ID"].isin(id_list)]
    ref_date = get_last_non_empty_date(non_new) or date.today()
    cur = ref_date
    for idx, rid in enumerate(id_list):
        rmask = df["Row ID"] == rid
        # first new row uses ref_date; subsequent +1 day
        cur = (ref_date if idx == 0 else cur + timedelta(days=1))
        # apply only if blank
        if df.loc[rmask, "Date"].astype(str).str.strip().eq("").all():
            df.loc[rmask, "Date"] = date_to_str(cur)
        if df.loc[rmask, "Day"].astype(str).str.strip().eq("").all():
            df.loc[rmask, "Day"] = weekday_abbr(cur)
        if df.loc[rmask, "Start Time"].astype(str).str.strip().eq("").all():
            df.loc[rmask, "Start Time"] = "09:00"
        if df.loc[rmask, "End Time"].astype(str).str.strip().eq("").all():
            df.loc[rmask, "End Time"] = "18:00"
    return df

# ------------------------------ App ------------------------------

st.set_page_config(page_title="ZC-030 Timesheet (Auto-Fill v3)", page_icon="🗓️", layout="wide")
init_session()

st.title("🗓️ ZC-030 Remote Engineer Timesheet — Auto-Fill v3")

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
        before_df = st.session_state.table.copy()
        extra = pd.DataFrame({c: [""]*add_rows for c in BASE_COLUMNS})
        extra = ensure_row_ids(extra)
        st.session_state.table = pd.concat([ensure_row_ids(before_df), extra], ignore_index=True)
        # mark new ids
        new_ids = detect_new_ids(before_df, st.session_state.table)
        st.session_state.table = autofill_rows_by_ids(st.session_state.table, new_ids)

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
name_options = [""] + sorted(list(st.session_state.employee_master_dict.keys()))
c1, c2 = st.columns([2,1])
emp_name_input = c1.selectbox("Employee Name (type to search)", options=name_options, index=name_options.index(st.session_state.employee.get("Employee Name","")) if st.session_state.employee.get("Employee Name","") in name_options else 0)
manual_name = c2.text_input("Or type a new name", value="" if emp_name_input else st.session_state.employee.get("Employee Name",""))
final_name = manual_name.strip() if manual_name.strip() else emp_name_input.strip()

if final_name != st.session_state.employee.get("Employee Name",""):
    st.session_state.employee["Employee Name"] = final_name
    if final_name in st.session_state.employee_master_dict:
        master = st.session_state.employee_master_dict[final_name]
        for k,v in master.items():
            if not st.session_state.employee.get(k, "").strip():
                st.session_state.employee[k] = v

col1, col2, col3, col4 = st.columns(4)
st.session_state.employee["IC#"] = col1.text_input("IC#", st.session_state.employee.get("IC#",""))
st.session_state.employee["Department"] = col2.text_input("Department", st.session_state.employee.get("Department",""))
st.session_state.employee["Job Title"] = col3.text_input("Job Title", st.session_state.employee.get("Job Title",""))
st.session_state.employee["Reporting Manager"] = col4.text_input("Reporting Manager", st.session_state.employee.get("Reporting Manager",""))

col5, col6, col7 = st.columns(3)
st.session_state.employee["Review Month"] = col5.text_input("Review Month", st.session_state.employee.get("Review Month",""))
st.session_state.employee["Year"] = col6.text_input("Year", st.session_state.employee.get("Year",""))
st.session_state.employee["Date"] = col7.text_input("Date", st.session_state.employee.get("Date",""), placeholder="YYYY-MM-DD")

st.divider()

# ------------------------------ Work Log ------------------------------

st.subheader("🧾 Work Log")
base = ensure_row_ids(st.session_state.table)

# Keep a copy of old IDs to detect new ones after editing
old_df = base.copy()

cfg = {
    "Date": st.column_config.TextColumn("Date", help="YYYY-MM-DD", required=False),
    "Day": st.column_config.SelectboxColumn("Day", options=DAYS, help="Auto from Date; editable", required=False),
    "Start Time": st.column_config.TextColumn("Start Time", help="hh:mm (e.g., 09:00)", required=False),
    "End Time": st.column_config.TextColumn("End Time", help="hh:mm (e.g., 18:00)", required=False),
    "Break (hh:mm)": st.column_config.TextColumn("Break (hh:mm)", help="hh:mm (e.g., 00:30)", required=False),
    "Work Hours": st.column_config.NumberColumn("Work Hours", help="Auto-calculated", step=0.25, disabled=True),
    "Description of Work": st.column_config.TextColumn("Description of Work", width="medium"),
    "Row ID": st.column_config.TextColumn("Row ID", help="Hidden technical id", disabled=True),
}

edited = st.data_editor(
    base,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config=cfg,
    column_order=[c for c in BASE_COLUMNS if c != "Row ID"] + ["Row ID"],  # keep ID but push to end
    key="data_editor",
)

# Ensure Row IDs exist for any newly added editor rows
edited = ensure_row_ids(edited)

# Detect brand-new rows by Row ID
new_ids = detect_new_ids(old_df, edited)

# Autofill only those new rows
if new_ids:
    edited = autofill_rows_by_ids(edited, new_ids)

# Derive Day from Date if Day blank (for all rows; does not overwrite non-blank)
for i, row in edited.iterrows():
    if not str(row.get("Day","")).strip():
        dval = str_to_date(str(row.get("Date","")))
        if dval:
            edited.at[i, "Day"] = weekday_abbr(dval)

# Recalc hours and persist
calc_df, total = recalc_hours(edited)
st.session_state.table = calc_df
st.session_state.total_hours = total

st.info(f"**Total Hours:** {total:.2f}")
st.caption("Add rows via the sidebar or the grid ➜ new rows auto-fill Date/Day/Start/End. Existing values are never overwritten.")
