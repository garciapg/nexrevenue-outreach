"""Google Sheets: Inbox (intake), Leads (mirror), Review (decisions), Dashboard, Do Not Contact."""
from __future__ import annotations

import json
import os
from typing import Any

HEADERS = {
    "inbox": ["Business Name", "Website", "Phone", "Email", "Contact Name", "Address", "City", "State",
              "Category", "Rating", "# Reviews", "Segment", "Notes", "Status"],
    "leads": ["Lead ID", "Segment", "Status", "Business", "Contact", "Email", "Phone", "City", "State",
              "Fit", "Fit Reason", "Emails Sent", "Calls", "Last Touch", "Next Action", "Reply",
              "First Line", "Website", "GHL Contact"],
    "review": ["Lead ID", "Decision", "Segment", "Business", "Fit", "Fit Reason", "Email", "Subject",
               "First Line", "QA", "Website"],
    "dashboard": ["Metric", "Value"],
    "runs": ["Started (local)", "Job", "OK", "Seconds", "Main numbers", "First error"],
    "dnc": ["Value", "Reason", "Added"],
    "call_list": ["Company Name", "City", "Owner Name", "Phone", "Reviews", "Notes", "Website"],
}


class Sheets:
    def __init__(self, spreadsheet, tabs: dict[str, str]):
        self.book = spreadsheet
        self.tabs = tabs

    @classmethod
    def from_env(cls, cfg: dict) -> "Sheets":
        import gspread
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if raw:
            gc = gspread.service_account_from_dict(json.loads(raw))
        else:
            gc = gspread.service_account(filename=os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json"))
        sheet_id = os.environ.get((cfg.get("sheet") or {}).get("id_env", "SHEET_ID"))
        if not sheet_id:
            raise RuntimeError("Missing SHEET_ID")
        return cls(gc.open_by_key(sheet_id), (cfg.get("sheet") or {}).get("tabs", {}))

    def ws(self, key: str):
        title = self.tabs.get(key, key)
        try:
            return self.book.worksheet(title)
        except Exception:
            ws = self.book.add_worksheet(title=title, rows=1000, cols=max(10, len(HEADERS.get(key, []))))
            if HEADERS.get(key):
                ws.update([HEADERS[key]], "A1")
            return ws

    def ensure_tabs(self) -> None:
        for key in self.tabs:
            ws = self.ws(key)
            if HEADERS.get(key) and not ws.row_values(1):
                ws.update([HEADERS[key]], "A1")

    def read(self, key: str) -> list[dict[str, Any]]:
        """Rows as dicts with `_row` (1-based sheet row number)."""
        values = self.ws(key).get_all_values()
        if not values:
            return []
        header = [h.strip() for h in values[0]]
        rows = []
        for i, row in enumerate(values[1:], start=2):
            item = {header[j]: (row[j].strip() if j < len(row) else "") for j in range(len(header)) if header[j]}
            if any(item.values()):
                item["_row"] = i
                rows.append(item)
        return rows

    def set_cells(self, key: str, row: int, values: dict[str, Any]) -> None:
        ws = self.ws(key)
        header = ws.row_values(1)
        for col_name, value in values.items():
            if col_name not in header:
                header.append(col_name)
                ws.update_cell(1, len(header), col_name)
            ws.update_cell(row, header.index(col_name) + 1, "" if value is None else str(value))

    def write_table(self, key: str, header: list[str], rows: list[list[Any]]) -> None:
        ws = self.ws(key)
        ws.clear()
        data = [header] + [["" if v is None else str(v) for v in r] for r in rows]
        if ws.row_count < len(data):
            ws.add_rows(len(data) - ws.row_count)
        ws.update(data, "A1")
