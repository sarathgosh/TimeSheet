
# timesheet_webui.py
# Single-file Streamlit app for "ZC-030 Remote Engineer Timesheet"
# - Fill Employee Info
# - Edit timesheet rows (Date, Day, Start, End, Break, Description)
# - Auto-calc Work Hours + Total
# - Import from an existing Excel (exported from this app) and continue
# - Export to formatted Excel (template style)

import io
from datetime import datetime, time
from typing import Tuple, Optional

import pandas as pd
import streamlit as st

# ------------------------------ Helpers ------------------------------

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def parse_break_to_hours(break_str: str) -> float:
    """Convert 'HH:MM' or 'H:MM' to hours as float. Return 0 on blank/invalid."""
    if not isinstance(break_str, str):
        return 0.0
    s = break_str.strip()
    if not s:
        return 0.0
    try:
        parts = s.split(":")
        if len(parts) != 2:
            return 0.0
        h = int(parts[0])
        m = int(parts[1])
        return max(0.0, float(h) + float(m)/60.0)
    except Exception:
        return 0.0

def hhmm_or_blank(t: Optional[time]) -> str:
    if isinstance(t, time):
        return t.strftime("%H:%M")
    if isinstance(t, str) and t:
        # try to normalize strings like "930" or "9:30"
        s = t.strip()
        try:
            if ":" in s:
                hh, mm = s.split(":")
                return f"{int(hh):02d}:{int(mm):02d}"
            if len(s) in (3,4):  # "930" or "0930"
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
    """Return hours = (end - start) - break, in hours. Handle wrap past midnight gracefully."""
    start_t = to_time_obj(start_str)
    end_t   = to_time_obj(end_str)
    if not start_t or not end_t:
        return 0.0

    start_minutes = start_t.hour * 60 + start_t.minute
    end_minutes   = end_t.hour * 60 + end_t.minute
    if end_minutes < start_minutes:
        # assume crossed midnight
        end_minutes += 24*60
    work_minutes = max(0, end_minutes - start_minutes)
    break_hours = parse_break_to_hours(break_str)
    hours = (work_minutes / 60.0) - break_hours
    return round(max(0.0, hours), 2)

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

def recalc_hours(df: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
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

def load_from_excel(file_bytes: bytes) -> Tuple[dict, pd.DataFrame]:
    """Try to load employee info + table from an Excel exported by this app."""
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    # Prefer sheet named "Timesheet". Fallback to first sheet.
    sheet = "Timesheet" if "Timesheet" in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=sheet, header=None)

    # Find header row that contains "Date, Day, Start Time, End Time, Break (hh:mm), Work Hours, Description of Work"
    headers = ["Date", "Day", "Start Time", "End Time", "Break (hh:mm)", "Work Hours", "Description of Work"]
    header_row_idx = None
    for i in range(min(60, len(df))):
        row_vals = [str(x).strip() for x in df.iloc[i].tolist()]
        if row_vals[:len(headers)] == headers:
            header_row_idx = i
            break

    # Extract employee info best-effort (positions from our exporter)
    employee = {
        "Employee Name": "",
        "IC#": "",
        "Department": "",
        "Job Title": "",
        "Reporting Manager": "",
        "Review Month": "",
        "Year": "",
        "Date": "",
    }

    try:
        def safe_cell(r,c):
            try:
                v = df.iat[r,c]
                return "" if pd.isna(v) else str(v)
            except Exception:
                return ""
        employee["Employee Name"] = safe_cell(5,1) or ""
        employee["IC#"] = safe_cell(5,5) or ""
        employee["Department"] = safe_cell(6,1) or ""
        employee["Job Title"] = safe_cell(6,5) or ""
        employee["Review Month"] = safe_cell(7,1) or ""
        employee["Year"] = safe_cell(7,5) or ""
        employee["Date"] = safe_cell(8,1) or ""
        employee["Reporting Manager"] = safe_cell(8,5) or ""
    except Exception:
        pass

    table = pd.DataFrame(columns=headers)
    if header_row_idx is not None:
        table = pd.read_excel(xls, sheet_name=sheet, header=header_row_idx)
        table = table[headers].copy()
        table = table.dropna(how="all").fillna("")
    else:
        if len(df.columns) >= 7:
            table = df.iloc[:, :7].copy()
            table.columns = headers
            table = table.dropna(how="all").fillna("")

    for col in ["Start Time", "End Time", "Break (hh:mm)"]:
        table[col] = table[col].apply(lambda x: "" if pd.isna(x) else str(x))

    return employee, table

def export_to_excel(employee: dict, table: pd.DataFrame) -> bytes:
    """Export to a formatted Excel bytes object."""
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
        readme.write(1,0,"1) Fill Employee Information boxes (grey headers).")
        readme.write(2,0,"2) Enter Date (yyyy-mm-dd), pick Day from dropdown, type Start/End times (hh:mm).")
        readme.write(3,0,"3) Break as hh:mm (e.g., 00:30). Work Hours auto-calculates in the app; Excel keeps totals.")
        readme.write(4,0,"4) Download and share.")
        readme.write(6,0,"Notes")
        readme.write(7,0,"- Work Hours inside Excel are plain numbers; edit times in the app to recompute if needed.")
        readme.write(8,0,"- You can re-import this file into the app to continue editing.")

    output.seek(0)
    return output.read()

# ------------------------------ App ------------------------------

st.set_page_config(page_title="ZC-030 Remote Engineer Timesheet", page_icon="🗓️", layout="wide")
init_session()

st.title("🗓️ ZC-030 Remote Engineer Timesheet — Web UI")

with st.sidebar:
    st.header("📂 Import / Export")
    up = st.file_uploader("Import from an exported Excel", type=["xlsx"])
    if up is not None:
        try:
            emp, tbl = load_from_excel(up.read())
            expected_cols = ["Date","Day","Start Time","End Time","Break (hh:mm)","Work Hours","Description of Work"]
            if all(c in tbl.columns for c in expected_cols):
                st.session_state.employee.update(emp or {})
                st.session_state.table = tbl[expected_cols].copy()
                st.success("Imported successfully.")
            else:
                st.warning("Couldn't detect the timesheet table reliably. Loaded a best-effort version.")
                st.session_state.table = tbl.copy()
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.divider()
    add_rows = st.number_input("Add rows", min_value=1, max_value=100, value=5, step=1)
    if st.button("➕ Append Rows"):
        extra = pd.DataFrame({c: [""]*add_rows for c in st.session_state.table.columns})
        st.session_state.table = pd.concat([st.session_state.table, extra], ignore_index=True)

    if st.button("🧹 Clear All Rows"):
        st.session_state.table = st.session_state.table.iloc[0:0].copy()

    st.divider()
    if st.button("⬇️ Export to Excel", type="primary"):
        st.session_state.table, st.session_state.total_hours = recalc_hours(st.session_state.table)
        data = export_to_excel(st.session_state.employee, st.session_state.table)
        st.download_button(
            "Download ZC-030 Timesheet.xlsx",
            data=data,
            file_name="ZC-030 Remote Engineer Timesheet (Filled).xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

st.subheader("👤 Employee Information")
col1, col2, col3, col4 = st.columns(4)
st.session_state.employee["Employee Name"] = col1.text_input("Employee Name", st.session_state.employee["Employee Name"])
st.session_state.employee["IC#"] = col2.text_input("IC#", st.session_state.employee["IC#"])
st.session_state.employee["Department"] = col3.text_input("Department", st.session_state.employee["Department"])
st.session_state.employee["Job Title"] = col4.text_input("Job Title", st.session_state.employee["Job Title"])

col5, col6, col7, col8 = st.columns(4)
st.session_state.employee["Reporting Manager"] = col5.text_input("Reporting Manager", st.session_state.employee["Reporting Manager"])
st.session_state.employee["Review Month"] = col6.text_input("Review Month", st.session_state.employee["Review Month"])
st.session_state.employee["Year"] = col7.text_input("Year", st.session_state.employee["Year"])
st.session_state.employee["Date"] = col8.text_input("Date", st.session_state.employee["Date"], placeholder="YYYY-MM-DD")

st.divider()
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
st.caption("Tip: Times can be entered as '9:30' or '0930'. Break as 'HH:MM' (e.g., 00:30). Crossing midnight is supported.")
