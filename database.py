import os
import openpyxl
from openpyxl import Workbook
from datetime import datetime

# Try importing win32print for thermal printer support
try:
    import win32print
    PRINTER_AVAILABLE = True
except ImportError:
    PRINTER_AVAILABLE = False

# Independent ticket counters
student_ticket_counter = 1
parent_ticket_counter = 1

paying_queue = []
preparation_queue = []

# TWO SEPARATE EXCEL DATABASE FILES
STUDENT_EXCEL_FILE = "student_queue_database.xlsx"
PARENT_EXCEL_FILE = "parent_queue_database.xlsx"


def init_db():
    """Initializes separate Excel workbooks for Students and Parents if they don't exist."""
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
    ticket_str = f"{prefix}-{ticket_id:03d}"
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


def print_thermal_receipt(ticket_str, name, purpose, payment_method="CASH", appt_type="Today", is_parent=False):
    """Sends revised formatted ESC/POS text commands to the connected Windows thermal printer."""
    date_str = datetime.now().strftime("%b %d, %Y")
    time_str = datetime.now().strftime("%I:%M %p")
    
    # 🧾 Formatting the thermal ticket receipt based on Option 1 Layout
    receipt_text = (
        "\x1b\x40"                 # Initialize printer
        "\x1b\x61\x01"             # Center alignment
        "TORRES CAPITOL COLLEGE\n"
        "SCHOOL PAYMENT QUEUE SYSTEM\n"
        "----------------------------------------\n"
        "YOUR QUEUE NUMBER\n\n"
        f"S-{ticket_str.split('-')[-1] if '-' in ticket_str else ticket_str}\n\n"
        "........................................\n"
        "\x1b\x61\x00"             # Left alignment
        f"Payer: {name}\n"
        f"Purpose: {purpose}\n"
        f"Payment Method: {payment_method}\n"
        "........................................\n"
        f"DATE: {date_str}\n"
        f"TIME: {time_str}\n"
        f"Appt: {appt_type}\n"
        "----------------------------------------\n"
        "\x1b\x61\x01"             # Center alignment
        "PLEASE WAIT FOR YOUR NUMBER\n"
        "* THANK YOU! *\n\n\n\n"
        "\x1d\x56\x41\x03"         # Paper cut command
    )

    if PRINTER_AVAILABLE:
        try:
            # Get default Windows printer
            printer_name = win32print.GetDefaultPrinter()
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                hJob = win32print.StartDocPrinter(hPrinter, 1, ("Queue Ticket", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, receipt_text.encode('utf-8'))
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
                print(f"[Printer Success] Ticket {ticket_str} printed on '{printer_name}'")
            finally:
                win32print.ClosePrinter(hPrinter)
        except Exception as e:
            print(f"[Printer Error]: Could not print to thermal printer: {e}")
            print(f"[Simulated Ticket Print Output]:\n{receipt_text}")
    else:
        print("[Printer Note]: 'pywin32' not installed. Simulated Receipt:")
        print(receipt_text)