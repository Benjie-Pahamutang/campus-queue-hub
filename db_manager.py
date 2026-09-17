import os
import json
import openpyxl
from openpyxl import Workbook
from datetime import datetime
import mysql.connector
import pandas as pd
import threading

# Try importing win32print for thermal printer support
try:
    import win32print
    PRINTER_AVAILABLE = True
except ImportError:
    PRINTER_AVAILABLE = False

# ==========================================
# COUNTER PERSISTENCE & STATE MANAGEMENT
# ==========================================
COUNTER_FILE = "counter_state.json"
counter_lock = threading.Lock()


def load_raw_json():
    """Reads saved JSON file from disk or returns base default structure."""
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Counter Error] Failed to read storage: {e}")

    return {
        "last_active_date": datetime.now().strftime("%Y-%m-%d"),
        "daily_walkin_student": 1,
        "daily_walkin_parent": 1,
        "booking_slots": {},
        "active_session": {"is_active": False}
    }


def write_raw_json(data):
    """Saves raw state dictionary directly to disk with thread safety."""
    try:
        with open(COUNTER_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[Counter Error] Failed to write storage: {e}")


def get_next_walkin_ticket(is_parent=False):
    """
    Generates continuous daily ticket numbers (1, 2, 3...).
    * Resets to 1 automatically when a new calendar day starts.
    * Has NO upper limit (runs as far as cashier processes).
    * Saves state instantly to prevent sequence loss on accidental app exit.
    """
    with counter_lock:
        data = load_raw_json()
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Automatically reset walk-in counters on new day
        if data.get("last_active_date") != today_str:
            data["last_active_date"] = today_str
            data["daily_walkin_student"] = 1
            data["daily_walkin_parent"] = 1

        key = "daily_walkin_parent" if is_parent else "daily_walkin_student"
        prefix = "G" if is_parent else "S"
        
        current_num = data.get(key, 1)

        # Increment for next request and save
        data[key] = current_num + 1
        write_raw_json(data)

        return f"{prefix}-{current_num:03d}"


def get_next_booking_slot(target_date_str, prefix="SLOT"):
    """
    Allocates slot numbers sequentially (1, 2, 3...) per target date.
    * target_date_str format: 'YYYY-MM-DD'
    * First person to book for a date gets Slot 1, second gets Slot 2.
    """
    with counter_lock:
        data = load_raw_json()
        slots = data.get("booking_slots", {})

        current_slot = slots.get(target_date_str, 0) + 1

        slots[target_date_str] = current_slot
        data["booking_slots"] = slots
        write_raw_json(data)

        return f"{prefix}-{current_slot:03d}"


# ==========================================
# ACCIDENTAL APP CLOSE / BILLING SESSION RECOVERY
# ==========================================

def sync_active_billing(ticket_number, current_items, cashier_id="Default"):
    """Call whenever cashier adds/removes items to protect mid-billing state against crashes."""
    with counter_lock:
        data = load_raw_json()
        data["active_session"] = {
            "is_active": True,
            "ticket_number": ticket_number,
            "items": current_items,
            "cashier_id": cashier_id
        }
        write_raw_json(data)


def clear_active_billing():
    """Call after payment is completed or cancelled to clear saved session state."""
    with counter_lock:
        data = load_raw_json()
        data["active_session"] = {"is_active": False}
        write_raw_json(data)


def get_active_billing_session():
    """Call during app boot to check for an interrupted transaction screen."""
    data = load_raw_json()
    return data.get("active_session", {"is_active": False})


# ==========================================
# QUEUE MEMORY & EXCEL FILE SETUP
# ==========================================
paying_queue = []
preparation_queue = []

STUDENT_EXCEL_FILE = "student_queue_database.xlsx"
PARENT_EXCEL_FILE = "parent_queue_database.xlsx"


# ==========================================
# DATABASE CONNECTIONS & QUERIES
# ==========================================

def get_db_connection():
    """Connects to MySQL Workbench database."""
    return mysql.connector.connect(
        host="localhost",
        user="root",        # Replace with your MySQL username
        password="",        # Replace with your MySQL password
        database="campus_queue_db"
    )


def get_today_lobby_queue():
    """Fetch ONLY today's active tickets for the Lobby TV."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    today_str = datetime.now().strftime("%A (%b %d)")
    
    query = """
        SELECT ticket_number, ticket_type, student_or_parent_name, purpose, appt_time_slot, queue_status
        FROM queue_tickets
        WHERE (target_date = CURRENT_DATE() OR target_date LIKE %s)
          AND queue_status IN ('WAITING', 'PREP', 'PAYING')
        ORDER BY ticket_id ASC;
    """
    cursor.execute(query, (f"%{today_str}%",))
    tickets = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return tickets


def sync_to_excel_audit(ticket_number, name, purpose, status, payment_method="CASH", appt_type="Today", is_parent=False):
    """Background export to Excel whenever a ticket status changes."""
    filename = PARENT_EXCEL_FILE if is_parent else STUDENT_EXCEL_FILE
    
    try:
        num = int(str(ticket_number).replace("S-", "").replace("G-", ""))
    except ValueError:
        num = 0

    new_data = {
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Ticket Number": f"{'G' if is_parent else 'S'}-{num:03d}",
        "Name": name,
        "Purpose": purpose,
        "Payment Method": payment_method,
        "Appt Status": appt_type,
        "Status": status
    }
    
    if os.path.exists(filename):
        df = pd.read_excel(filename)
        df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
    else:
        df = pd.DataFrame([new_data])
        
    df.to_excel(filename, index=False)


# ==========================================
# EXCEL INITIALIZATION & LOGGING
# ==========================================

def init_db():
    """Initializes separate Excel workbooks for Students and Parents if missing."""
    targets = [
        (STUDENT_EXCEL_FILE, "Student ID / Name"),
        (PARENT_EXCEL_FILE, "Parent / Guardian Name")
    ]
    for file_path, name_header in targets:
        if not os.path.exists(file_path):
            wb = Workbook()
            ws = wb.active
            ws.title = "Queue Logs"
            ws.append(["Ticket No.", name_header, "Purpose", "Payment Method", "Appt Status", "Status / Event", "Timestamp"])
            wb.save(file_path)


def log_to_excel(ticket_id, name, purpose, status="WAITING", payment_method="CASH", appt_type="Today", is_parent=False, *args, **kwargs):
    """Saves student records strictly to student_queue_database.xlsx 
       and parent records strictly to parent_queue_database.xlsx."""
    file_path = PARENT_EXCEL_FILE if is_parent else STUDENT_EXCEL_FILE
    prefix = "G" if is_parent else "S"
    
    try:
        clean_id = int(str(ticket_id).replace("S-", "").replace("G-", ""))
    except ValueError:
        clean_id = 0

    ticket_str = f"{prefix}-{clean_id:03d}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        if not os.path.exists(file_path):
            init_db()
            
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active
        ws.append([ticket_str, name, purpose, payment_method, appt_type, status, timestamp])
        wb.save(file_path)
    except Exception as e:
        print(f"[Excel Logging Error]: {e}")


# ==========================================
# PRINTER SERVICES
# ==========================================

def print_thermal_receipt(ticket_str, name, purpose, payment_method="CASH", appt_type="Today", is_parent=False):
    """Sends raw formatted ESC/POS byte commands to the thermal printer using the updated layout."""
    date_str = datetime.now().strftime("%b %d, %Y")
    time_str = datetime.now().strftime("%I:%M %p")
    
    raw_data = bytearray()
    raw_data.extend(b"\x1b\x40")                 # Initialize printer
    raw_data.extend(b"\x1b\x61\x01")             # Center align
    raw_data.extend(b"TORRES CAPITOL COLLEGE\n")
    raw_data.extend(b"SCHOOL PAYMENT QUEUE SYSTEM\n")
    raw_data.extend(b"----------------------------------------\n")
    raw_data.extend(b"YOUR QUEUE NUMBER\n\n")
    
    # Large Ticket Number Display
    raw_data.extend(f"{ticket_str}\n\n".encode('utf-8'))
    
    raw_data.extend(b"........................................\n")
    raw_data.extend(b"\x1b\x61\x00")             # Left align
    raw_data.extend(f"Payer: {name}\n".encode('utf-8'))
    raw_data.extend(f"Purpose: {purpose}\n".encode('utf-8'))
    raw_data.extend(f"Payment Method: {payment_method}\n".encode('utf-8'))
    raw_data.extend(b"........................................\n")
    raw_data.extend(f"DATE: {date_str}\n".encode('utf-8'))
    raw_data.extend(f"TIME: {time_str}\n".encode('utf-8'))
    raw_data.extend(f"Appt: {appt_type}\n".encode('utf-8'))
    raw_data.extend(b"----------------------------------------\n")
    raw_data.extend(b"\x1b\x61\x01")             # Center align
    raw_data.extend(b"PLEASE WAIT FOR YOUR NUMBER\n")
    raw_data.extend(b"* THANK YOU! *\n\n\n\n")
    raw_data.extend(b"\x1d\x56\x41\x03")         # Cut paper

    if PRINTER_AVAILABLE:
        try:
            printer_name = win32print.GetDefaultPrinter()
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                hJob = win32print.StartDocPrinter(hPrinter, 1, ("Queue Ticket", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, raw_data)
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
                print(f"[Printer Success] Ticket {ticket_str} printed on '{printer_name}'")
            finally:
                win32print.ClosePrinter(hPrinter)
        except Exception as e:
            print(f"[Printer Error]: Could not print to thermal printer: {e}")
            print(f"[Simulated Print Output]:\n{raw_data.decode('utf-8', errors='ignore')}")
    else:
        print("[Printer Note]: 'pywin32' not installed. Simulated print action complete.")
        print(raw_data.decode('utf-8', errors='ignore'))