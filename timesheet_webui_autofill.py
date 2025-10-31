
# timesheet_webui_autofill.py
# Streamlit Web UI — ZC-030 Remote Engineer Timesheet
# New feature: Auto-fill details (IC#, Department, Job Title, Reporting Manager)
# when "Employee Name" matches a master directory (CSV upload or built-in sample).

import io
from datetime import time
from typing import Tuple, Optional, Dict

import pandas as pd
import streamlit as st

# ------------------------------ Master Directory Helpers ------------------------------

BUILTIN_EMPLOYEES = [
    # Edit or replace with your real people
    {"Employee Name": "Sarath Gosh", "IC#": "S1234567A", "Department": "Engineering", "Job Title": "Remote Engineer", "Reporting Manager": "Shailesh"},
    {"Employee Name": "Shri Shailesh", "IC#": "S7654321B", "Department": "Operations", "Job Title": "Manager", "Reporting Manager": "—"},
]

REQUIRED_COLS = ["Employee Name", "IC#", "Department", "Job Title", "Reporting Manager"]

def normalize_master(df: pd.DataFrame) -> pd.DataFrame:
    """Make column names flexible; return only needed columns with exact names."""
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
    # Drop empty names
    df2 = df2[df2["Employee Name"].astype(str).str.strip() != ""]
    # Keep last occurrence when duplicates exist
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
    if not s:
        return 0.0
    try:
        parts = s.split(":")
        if len(parts) != 2:
            return 0.0
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
            "Employee Name": "",
            "IC#": "",
            "Department": "",
            "Job Title": "",
            "Reporting Manager": "",
            "Review Month": "",
            "Year": "",
            "Date": "",
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

        if table is None or table.empty:
            table = pd.DataFrame(columns=headers)

        for h in headers:
            if h not in table.columns:
                table[h] = ""

        start_row = 13
        for i, (_, row) in enumerate(table.iterrows()):
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

        total_row = start_row + len(table)
        ws.write(total_row, 4, "Total Hours:", right_fmt)
        ws.write_formula(total_row, 5, f"=SUM(F{start_row+1}:F{start_row+len(table)})", num_fmt)

        ws.merge_range(total_row + 2, 0, total_row + 2, 2, "Emp Signature", box)
        ws.merge_range(total_row + 2, 3, total_row + 2, 4, "RM signature", box)
        ws.merge_range(total_row + 2, 5, total_row + 2, 6, "Date", box)

        readme = wb.add_worksheet("ReadMe")
        readme.write(0,0,"How to use")
        readme.write(1,0,"1) Fill Employee Information. Name can auto-fill from master.")
        readme.write(2,0,"2) Enter Date, Day (dropdown), Start/End, Break. Work Hours auto-calc in app.")
        readme.write(3,0,"3) Export to Excel for sharing.")
        readme.write(5,0,"Master Directory")
        readme.write(6,0,"- Upload a CSV with columns: Employee Name, IC#, Department, Job Title, Reporting Manager.")
        readme.write(7,0,"- Or add current employee to master via sidebar button.")

    output.seek(0)
    return output.read()

# ------------------------------ App ------------------------------

st.set_page_config(page_title="ZC-030 Timesheet (Auto-Fill)", page_icon="🗓️", layout="wide")
init_session()

st.title("🗓️ ZC-030 Remote Engineer Timesheet — Auto-Fill Edition")

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

    st.caption("CSV columns can be flexible; we'll map to: Employee Name, IC#, Department, Job Title, Reporting Manager.")

    st.divider()
    st.subheader("Auto-Fill Settings")
    auto_fill = st.checkbox("Auto-fill when Employee Name matches", value=True)
    overwrite = st.checkbox("Overwrite existing fields on match", value=False)

    st.divider()
    if st.button("➕ Add current form to Master"):
        cur = st.session_state.employee
        if cur["Employee Name"].strip():
            # append or replace
            df = st.session_state.employee_master.copy()
            row = {c: cur.get(c, "") for c in REQUIRED_COLS}
            # Replace any existing entry with same name
            df = df[df["Employee Name"] != row["Employee Name"]]
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            st.session_state.employee_master = df
            st.session_state.employee_master_dict = master_to_dict(df)
            st.success(f"Saved '{row['Employee Name']}' to master.")
        else:
            st.warning("Please enter Employee Name first.")

    st.download_button(
        "⬇️ Download Master (CSV)",
        data=st.session_state.employee_master.to_csv(index=False).encode("utf-8"),
        file_name="employee_master.csv",
        mime="text/csv"
    )

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

# Suggest names from master while allowing free typing
name_options = [""] + sorted(list(st.session_state.employee_master_dict.keys()))
c1, c2 = st.columns([2,1])
emp_name_input = c1.selectbox("Employee Name (type to search)", options=name_options, index=name_options.index(st.session_state.employee.get("Employee Name","")) if st.session_state.employee.get("Employee Name","") in name_options else 0)
manual_name = c2.text_input("Or type a new name", value="" if emp_name_input else st.session_state.employee.get("Employee Name",""))

final_name = manual_name.strip() if manual_name.strip() else emp_name_input.strip()
if final_name != st.session_state.last_emp_name:
    # Name changed
    st.session_state.employee["Employee Name"] = final_name
    if auto_fill and final_name in st.session_state.employee_master_dict:
        master = st.session_state.employee_master_dict[final_name]
        for k,v in master.items():
            if overwrite or not st.session_state.employee.get(k, "").strip():
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
st.caption("Tip: Upload a master CSV once; picking a name will populate IC#, Department, Job Title, Reporting Manager automatically.")

st.divider()

# ------------------------------ Work Log ------------------------------

st.subheader("🧾 Work Log")
edit_df = st.session_state.table.copy()

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

calc_df, total = recalc_hours(edited)
st.session_state.table = calc_df
st.session_state.total_hours = total

st.info(f"**Total Hours:** {total:.2f}")
st.caption("Times can be '9:30' or '0930'. Break as 'HH:MM' (e.g., 00:30). Midnight crossover supported.")
