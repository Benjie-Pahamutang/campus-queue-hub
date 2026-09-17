import customtkinter as ctk
import db_manager as db
import pyttsx3
import threading
import time
import os
import json
import datetime
import serial  # Arduino communication
from tkinter import messagebox, ttk
from login import LoginWindow

# ================================================================
# 💾 PERSISTENCE & COUNTER STATE MANAGER (OPTION 2)
# ================================================================
COUNTER_FILE = "counter_state.json"
counter_lock = threading.Lock()

def load_raw_json():
    """Reads saved JSON file or returns base structure."""
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Counter Error] Failed to read storage: {e}")
    return {
        "last_active_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "daily_walkin_student": 1,
        "daily_walkin_parent": 1,
        "booking_slots": {},
        "paying_queue": [],
        "preparation_queue": [],
        "advance_appointments": [],
        "active_session": {"is_active": False}
    }

def write_raw_json(data):
    """Saves raw state dictionary directly to disk."""
    try:
        with open(COUNTER_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[Counter Error] Failed to write storage: {e}")

def save_current_queues_state():
    """Saves active live queues and advance appointments to disk to prevent loss on restart."""
    with counter_lock:
        data = load_raw_json()
        data["paying_queue"] = db.paying_queue
        data["preparation_queue"] = db.preparation_queue
        data["advance_appointments"] = getattr(db, 'advance_appointments', [])
        write_raw_json(data)

def load_saved_queues_state():
    """Loads saved active live queues back into memory upon restart."""
    data = load_raw_json()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # If same day restart, restore active waiting queues
    if data.get("last_active_date") == today_str:
        db.paying_queue = data.get("paying_queue", [])
        db.preparation_queue = data.get("preparation_queue", [])
        db.advance_appointments = data.get("advance_appointments", [])
    else:
        db.paying_queue = []
        db.preparation_queue = []
        db.advance_appointments = data.get("advance_appointments", [])

def get_next_sequence_number(queue_type="Student"):
    """
    * Keeps the current counter if closed and reopened on the SAME day.
    * Resets to 1 on a NEW calendar day (only offsets if appointments are scheduled for today).
    """
    with counter_lock:
        data = load_raw_json()
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        is_parent = (queue_type == "Parent")
        key = "daily_walkin_parent" if is_parent else "daily_walkin_student"

        # Handle NEW calendar day reset
        if data.get("last_active_date") != today_str:
            data["last_active_date"] = today_str

            # Check if there are appointments explicitly booked for TODAY
            slots = data.get("booking_slots", {})
            stud_slot_key = f"{today_str}_student"
            parent_slot_key = f"{today_str}_parent"

            stud_today_appts = slots.get(stud_slot_key, 0)
            parent_today_appts = slots.get(parent_slot_key, 0)

            # Resets cleanly to 1 if no appointments exist for today
            data["daily_walkin_student"] = stud_today_appts + 1
            data["daily_walkin_parent"] = parent_today_appts + 1
            data["paying_queue"] = []
            data["preparation_queue"] = []

        # Retrieve counter (picks up directly where it left off on same-day restart)
        current_num = data.get(key, 1)

        data[key] = current_num + 1
        write_raw_json(data)
        return current_num

def reset_daily_slot_counter(queue_type="Student"):
    """
    Resets active daily slot sequence back to 1 for TODAY ONLY.
    Does NOT wipe future date appointments inside booking_slots.
    """
    with counter_lock:
        data = load_raw_json()
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        is_parent = (queue_type == "Parent")
        key = "daily_walkin_parent" if is_parent else "daily_walkin_student"
        
        # Calculate baseline (offsetting for today's booked appointments if present)
        slots = data.get("booking_slots", {})
        slot_key = f"{today_str}_{'parent' if is_parent else 'student'}"
        today_appts = slots.get(slot_key, 0)
        
        base_slot = today_appts + 1
        data[key] = base_slot
        
        if is_parent:
            db.parent_ticket_counter = base_slot
            db.today_parent_walkins = 0
        else:
            db.student_ticket_counter = base_slot
            db.today_student_walkins = 0
            
        write_raw_json(data)
        return base_slot

def get_next_booking_slot(target_date_str, is_parent=False):
    """
    Increments and returns the offline booking slot for a target date.
    First booker gets slot 1 for that specific target date without affecting today's sequence.
    """
    with counter_lock:
        data = load_raw_json()
        slots = data.get("booking_slots", {})
        
        slot_key = f"{target_date_str}_{'parent' if is_parent else 'student'}"
        current_slot = slots.get(slot_key, 0) + 1

        slots[slot_key] = current_slot
        data["booking_slots"] = slots
        write_raw_json(data)
        return current_slot

def sync_active_billing(ticket_number, items, payer_name=""):
    """Call whenever cashier adds/removes items to protect against accidental exits."""
    with counter_lock:
        data = load_raw_json()
        data["active_session"] = {
            "is_active": True,
            "ticket_number": ticket_number,
            "payer_name": payer_name,
            "items": items,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        write_raw_json(data)

def clear_active_billing():
    """Call after payment transaction completes to clear crashed session backup."""
    with counter_lock:
        data = load_raw_json()
        data["active_session"] = {"is_active": False}
        write_raw_json(data)

def get_active_session():
    """Checks for interrupted cashier billing session on startup."""
    data = load_raw_json()
    return data.get("active_session", {"is_active": False})

# Synchronize runtime counters and restore queues on startup
_init_data = load_raw_json()
db.student_ticket_counter = _init_data.get("daily_walkin_student", 1)
db.parent_ticket_counter = _init_data.get("daily_walkin_parent", 1)

if not hasattr(db, 'advance_appointments'):
    db.advance_appointments = []
if not hasattr(db, 'today_student_walkins'):
    db.today_student_walkins = 0
if not hasattr(db, 'today_parent_walkins'):
    db.today_parent_walkins = 0

load_saved_queues_state()

# ================================================================
# 🔌 ARDUINO SERIAL INITIALIZATION & THREAD LOCKING
# ================================================================
ARDUINO_PORT = 'COM3'  # Change to match your system's COM port
serial_lock = threading.Lock()

try:
    arduino = serial.Serial(ARDUINO_PORT, 9600, timeout=1)
    time.sleep(2)
    arduino.reset_input_buffer()
    arduino.reset_output_buffer()
except Exception as e:
    print(f"[Arduino Warning] Could not connect on {ARDUINO_PORT}: {e}")
    arduino = None

def trigger_arduino_buzzer():
    """Sends a signal to trigger the dual active-low buzzers on the Arduino safely."""
    def run_buzzer():
        if arduino and arduino.is_open:
            with serial_lock:
                try:
                    arduino.write(b'B\n')
                    arduino.flush()
                except Exception as e:
                    print(f"[Arduino Serial Error]: {e}")
                
    threading.Thread(target=run_buzzer, daemon=True).start()

def print_thermal_receipt(ticket_type_char, ticket_num, student_name, purpose, appt_time=None):
    """Sends styled receipt print command to Arduino over Serial."""
    def run_print():
        if arduino and arduino.is_open:
            with serial_lock:
                try:
                    formatted_num = f"{ticket_num:03d}"
                    now = datetime.datetime.now()
                    date_str = now.strftime("%b %d, %Y")
                    
                    clean_purpose = purpose.replace("₱", "Php ")
                    clean_name = student_name.replace("₱", "Php ")

                    if appt_time and appt_time != "N/A":
                        time_str = appt_time
                        p_appt = appt_time
                    else:
                        time_str = now.strftime("%I:%M %p")
                        p_appt = "N/A"
                    
                    payload = f"P|{ticket_type_char}|{formatted_num}|{clean_name}|{clean_purpose}|{date_str}|{time_str}|{p_appt}\n"
                    
                    arduino.reset_output_buffer()
                    arduino.write(payload.encode('utf-8'))
                    arduino.flush()
                except Exception as e:
                    print(f"[Arduino Thermal Printer Error]: {e}")
        else:
            time_info = f"Appt Time: {appt_time}" if appt_time else "Walk-in"
            print(f"[Printer Offline] Simulating print: {ticket_type_char}-{ticket_num:03d} | Payer: {student_name} | Purpose: {purpose} | {time_info}")

    threading.Thread(target=run_print, daemon=True).start()

db.print_thermal_receipt = print_thermal_receipt

# ================================================================
# 🗣️ TEXT TO SPEECH HELPER
# ================================================================
def speak_text(text):
    def run_speech():
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', 145)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTS Voice Error]: {e}")

    threading.Thread(target=run_speech, daemon=True).start()

def get_ticket_voice_label(ticket_info):
    student_name = ticket_info.get("student", "")
    if "[Parent]" in student_name:
        return f"guardian number {ticket_info['id']:03d}"
    else:
        return f"student number {ticket_info['id']:03d}"

# ================================================================
# 📋 DATABASE MANAGER POPUP
# ================================================================
class DatabaseWindow(ctk.CTkToplevel):
    def __init__(self, master, update_callback):
        super().__init__(master)
        self.title("Live Queue Database Manager")
        self.geometry("850x560")
        self.update_callback = update_callback
        self.attributes("-topmost", True)
        
        ctk.CTkLabel(self, text="📋 Live Queue & Advance Database Records", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=15, pady=5)
        
        self.tab_student = self.tabview.add("🎓 Student Queue")
        self.tab_parent = self.tabview.add("👨‍👩‍👧 Parent / Guardian Queue")
        self.tab_advance = self.tabview.add("📅 Advance Appointments")
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#2d3436", fieldbackground="#2d3436", foreground="white", rowheight=25)
        style.map("Treeview", background=[('selected', '#1a73e8')])

        self.stud_tree = ttk.Treeview(self.tab_student, columns=("Ticket", "ID_Name", "Purpose", "Type", "Phase"), show="headings")
        self.setup_tree_columns(self.stud_tree, "Student ID / Name")
        
        self.parent_tree = ttk.Treeview(self.tab_parent, columns=("Ticket", "ID_Name", "Purpose", "Type", "Phase"), show="headings")
        self.setup_tree_columns(self.parent_tree, "Parent Name")

        self.adv_tree = ttk.Treeview(self.tab_advance, columns=("Ticket", "ID_Name", "Purpose", "Appt_Slot", "Type"), show="headings")
        self.setup_advance_tree_columns(self.adv_tree)
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10, padx=20)
        
        ctk.CTkButton(btn_frame, text="🚫 Invalidate / Delete Selected", fg_color="#e74c3c", hover_color="#c0392b", command=self.delete_selected).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="📊 Open Tab Excel File", fg_color="#27ae60", hover_color="#219a52", command=self.open_excel_app).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="🔄 Refresh Tables", fg_color="#34495e", command=self.load_data).pack(side="right", padx=5)
        
        self.load_data()

    def setup_tree_columns(self, tree_widget, name_header):
        tree_widget.heading("Ticket", text="Ticket No.")
        tree_widget.heading("ID_Name", text=name_header)
        tree_widget.heading("Purpose", text="Purpose")
        tree_widget.heading("Type", text="Booking Type")
        tree_widget.heading("Phase", text="Queue Status")
        
        tree_widget.column("Ticket", width=90, anchor="center")
        tree_widget.column("ID_Name", width=200, anchor="w")
        tree_widget.column("Purpose", width=130, anchor="center")
        tree_widget.column("Type", width=140, anchor="center")
        tree_widget.column("Phase", width=130, anchor="center")
        tree_widget.pack(fill="both", expand=True, padx=5, pady=5)

    def setup_advance_tree_columns(self, tree_widget):
        tree_widget.heading("Ticket", text="Ref Code")
        tree_widget.heading("ID_Name", text="Payer Name")
        tree_widget.heading("Purpose", text="Purpose")
        tree_widget.heading("Appt_Slot", text="Scheduled Slot")
        tree_widget.heading("Type", text="Category")
        
        tree_widget.column("Ticket", width=90, anchor="center")
        tree_widget.column("ID_Name", width=180, anchor="w")
        tree_widget.column("Purpose", width=120, anchor="center")
        tree_widget.column("Appt_Slot", width=180, anchor="center")
        tree_widget.column("Type", width=100, anchor="center")
        tree_widget.pack(fill="both", expand=True, padx=5, pady=5)

    def load_data(self):
        for item in self.stud_tree.get_children():
            self.stud_tree.delete(item)
        for item in self.parent_tree.get_children():
            self.parent_tree.delete(item)
        for item in self.adv_tree.get_children():
            self.adv_tree.delete(item)
            
        for ticket in db.paying_queue:
            is_parent = "[Parent]" in ticket['student']
            b_type = f"Appointment ({ticket['appt_time']})" if ticket.get('is_appointment') else "Walk-In"
            phase = "Paying Phase"
            if is_parent:
                self.parent_tree.insert("", "end", values=(f"G-{ticket['id']:03d}", ticket['student'], ticket['purpose'], b_type, phase))
            else:
                self.stud_tree.insert("", "end", values=(f"S-{ticket['id']:03d}", ticket['student'], ticket['purpose'], b_type, phase))

        for ticket in db.preparation_queue:
            is_parent = "[Parent]" in ticket['student']
            b_type = f"Appointment ({ticket['appt_time']})" if ticket.get('is_appointment') else "Walk-In"
            phase = "Prep Phase"
            if is_parent:
                self.parent_tree.insert("", "end", values=(f"G-{ticket['id']:03d}", ticket['student'], ticket['purpose'], b_type, phase))
            else:
                self.stud_tree.insert("", "end", values=(f"S-{ticket['id']:03d}", ticket['student'], ticket['purpose'], b_type, phase))

        for ticket in db.advance_appointments:
            is_parent = ticket.get("is_parent", False)
            p_type = "Parent" if is_parent else "Student"
            prefix = "G" if is_parent else "S"
            ticket_id_str = f"{prefix}-{ticket['id']:03d}" if 'id' in ticket else f"{prefix}-ADV"
            self.adv_tree.insert("", "end", values=(ticket_id_str, ticket['student'], ticket['purpose'], ticket['appt_time'], p_type))

    def delete_selected(self):
        current_tab = self.tabview.get()
        if "Advance" in current_tab:
            selected_item = self.adv_tree.selection()
            if not selected_item:
                messagebox.showwarning("Selection Missing", "Please select an advance appointment row first.")
                return
            values = self.adv_tree.item(selected_item, "values")
            payer_name = values[1]
            appt_slot = values[3]
            
            for appt in list(db.advance_appointments):
                if appt['student'] == payer_name and appt['appt_time'] == appt_slot:
                    db.advance_appointments.remove(appt)
                    save_current_queues_state()
                    messagebox.showinfo("Appointment Cancelled", f"Advance booking for {payer_name} was removed.")
                    break
            self.load_data()
            return

        is_parent_tab = ("Parent" in current_tab)
        tree = self.parent_tree if is_parent_tab else self.stud_tree
        
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Missing", "Please select a ticket row from the active tab table first.")
            return
            
        values = tree.item(selected_item, "values")
        target_ticket_str = values[0]
        prefix, id_str = target_ticket_str.split("-")
        target_id = int(id_str)
        is_parent_target = (prefix == "G")
        
        removed = False
        for ticket in db.paying_queue:
            ticket_is_parent = "[Parent]" in ticket['student']
            if ticket['id'] == target_id and ticket_is_parent == is_parent_target:
                db.paying_queue.remove(ticket)
                save_current_queues_state()
                status_reason = "Invalidated Appointment Slot" if ticket.get("is_appointment") else "Absent - Invalidated Slot"
                db.log_to_excel(ticket['id'], ticket['student'], ticket['purpose'], status_reason, is_parent=is_parent_target)
                removed = True
                break
                
        if not removed:
            for ticket in db.preparation_queue:
                ticket_is_parent = "[Parent]" in ticket['student']
                if ticket['id'] == target_id and ticket_is_parent == is_parent_target:
                    db.preparation_queue.remove(ticket)
                    save_current_queues_state()
                    status_reason = "Invalidated Appointment Slot" if ticket.get("is_appointment") else "Absent - Invalidated Slot"
                    db.log_to_excel(ticket['id'], ticket['student'], ticket['purpose'], status_reason, is_parent=is_parent_target)
                    break
                    
        messagebox.showinfo("Slot Freed", f"Ticket {target_ticket_str} was invalidated and removed.")
        self.load_data()
        self.update_callback()

    def open_excel_app(self):
        current_tab = self.tabview.get()
        is_parent = ("Parent" in current_tab)
        file_path = getattr(db, 'PARENT_EXCEL_FILE', 'parent_queue_database.xlsx') if is_parent else getattr(db, 'STUDENT_EXCEL_FILE', 'student_queue_database.xlsx')
        
        if os.path.exists(file_path):
            try:
                os.startfile(file_path)
            except Exception as e:
                messagebox.showerror("Error", f"Could not launch Excel: {e}")
        else:
            messagebox.showwarning("File Missing", f"No Excel records found yet for this queue!")

# ================================================================
# 📺 LOBBY TV MONITOR WINDOW
# ================================================================
class PublicTVMonitor(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Lobby TV Display")
        
        screen_w = self.winfo_screenwidth()
        self.geometry(f"1100x700+{screen_w}+0")
        self.after(200, lambda: self.state('zoomed'))
        
        self.configure(fg_color="#1e272e")
        self.setup_tv_layout()
        self.update_clock()

    def setup_tv_layout(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(15, 0))
        
        ctk.CTkLabel(header_frame, text="CAMPUS QUEUE HUB", font=("Helvetica", 34, "bold"), text_color="#f5cd79").pack(side="left")
        self.clock_lbl = ctk.CTkLabel(header_frame, text="", font=("Helvetica", 18, "bold"), text_color="#ecf0f1")
        self.clock_lbl.pack(side="right")

        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20, pady=10)
        self.main_container.grid_columnconfigure((0, 1), weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        # STUDENTS PANEL
        self.stud_side = ctk.CTkFrame(self.main_container, fg_color="#2c3e50", corner_radius=15)
        self.stud_side.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")

        ctk.CTkLabel(self.stud_side, text="STUDENTS QUEUE", font=("Helvetica", 24, "bold"), text_color="#3498db").pack(pady=(15, 5))
        
        self.tv_stud_rem_lbl = ctk.CTkLabel(self.stud_side, text="Available Today: 130/130", font=("Helvetica", 15, "bold"), text_color="#f1c40f")
        self.tv_stud_rem_lbl.pack(pady=2)

        ctk.CTkLabel(self.stud_side, text="NOW SERVING", font=("Helvetica", 18, "bold"), text_color="#ffffff").pack(pady=(5, 0))
        
        self.tv_stud_serving_lbl = ctk.CTkLabel(self.stud_side, text="S---", font=("Helvetica", 75, "bold"), text_color="#2ecc71")
        self.tv_stud_serving_lbl.pack(pady=5)
        
        self.tv_stud_info_lbl = ctk.CTkLabel(self.stud_side, text="", font=("Helvetica", 14, "bold"), text_color="#f39c12")
        self.tv_stud_info_lbl.pack(pady=(0, 10))

        stud_prep_panel = ctk.CTkFrame(self.stud_side, fg_color="#151d24", corner_radius=12)
        stud_prep_panel.pack(fill="x", padx=15, pady=(5, 15))
        
        ctk.CTkLabel(stud_prep_panel, text="⏱️ UPCOMING STUDENT QUEUE", font=("Helvetica", 13, "bold"), text_color="#bdc3c7").pack(pady=(10, 5))
        
        self.stud_badge_container = ctk.CTkFrame(stud_prep_panel, fg_color="transparent")
        self.stud_badge_container.pack(pady=(0, 10), padx=10, fill="x")
        
        self.stud_prep_badges = []
        for i in range(4):
            self.stud_badge_container.grid_columnconfigure(i, weight=1)
            badge = ctk.CTkLabel(self.stud_badge_container, text="--", font=("Helvetica", 16, "bold"), text_color="#7f8c8d", fg_color="#1e272e", height=45, corner_radius=6)
            badge.grid(row=0, column=i, padx=4, sticky="ew")
            self.stud_prep_badges.append(badge)

        # PARENTS PANEL
        self.parent_side = ctk.CTkFrame(self.main_container, fg_color="#2c3e50", corner_radius=15)
        self.parent_side.grid(row=0, column=1, padx=10, pady=5, sticky="nsew")

        ctk.CTkLabel(self.parent_side, text="PARENTS QUEUE", font=("Helvetica", 24, "bold"), text_color="#e67e22").pack(pady=(15, 5))
        
        self.tv_parent_rem_lbl = ctk.CTkLabel(self.parent_side, text="Available Today: 130/130", font=("Helvetica", 15, "bold"), text_color="#f1c40f")
        self.tv_parent_rem_lbl.pack(pady=2)

        ctk.CTkLabel(self.parent_side, text="NOW SERVING", font=("Helvetica", 18, "bold"), text_color="#ffffff").pack(pady=(5, 0))
        
        self.tv_parent_serving_lbl = ctk.CTkLabel(self.parent_side, text="G---", font=("Helvetica", 75, "bold"), text_color="#e74c3c")
        self.tv_parent_serving_lbl.pack(pady=5)

        self.tv_parent_info_lbl = ctk.CTkLabel(self.parent_side, text="", font=("Helvetica", 14, "bold"), text_color="#f39c12")
        self.tv_parent_info_lbl.pack(pady=(0, 10))

        parent_prep_panel = ctk.CTkFrame(self.parent_side, fg_color="#151d24", corner_radius=12)
        parent_prep_panel.pack(fill="x", padx=15, pady=(5, 15))
        
        ctk.CTkLabel(parent_prep_panel, text="⏱️ UPCOMING PARENTS QUEUE", font=("Helvetica", 13, "bold"), text_color="#bdc3c7").pack(pady=(10, 5))
        
        self.parent_badge_container = ctk.CTkFrame(parent_prep_panel, fg_color="transparent")
        self.parent_badge_container.pack(pady=(0, 10), padx=10, fill="x")
        
        self.parent_prep_badges = []
        for i in range(4):
            self.parent_badge_container.grid_columnconfigure(i, weight=1)
            badge = ctk.CTkLabel(self.parent_badge_container, text="--", font=("Helvetica", 16, "bold"), text_color="#7f8c8d", fg_color="#1e272e", height=45, corner_radius=6)
            badge.grid(row=0, column=i, padx=4, sticky="ew")
            self.parent_prep_badges.append(badge)

    def update_clock(self):
        now_str = datetime.datetime.now().strftime("%a, %b %d %Y  |  %I:%M:%S %p")
        self.clock_lbl.configure(text=now_str)
        self.after(1000, self.update_clock)

    def flash_serving_label(self, label_widget, original_color, times=6):
        if times > 0:
            current_col = label_widget.cget("text_color")
            next_col = "#f1c40f" if current_col == original_color else original_color
            label_widget.configure(text_color=next_col)
            self.after(250, lambda: self.flash_serving_label(label_widget, original_color, times - 1))
        else:
            label_widget.configure(text_color=original_color)

    def update_tv_screen(self, flash_type=None):
        stud_queue = [t for t in db.paying_queue if "[Parent]" not in t['student']]
        parent_queue = [t for t in db.paying_queue if "[Parent]" in t['student']]

        stud_prep_queue = [t for t in db.preparation_queue if "[Parent]" not in t['student']]
        parent_prep_queue = [t for t in db.preparation_queue if "[Parent]" in t['student']]

        stud_issued = db.today_student_walkins
        stud_max = self.master.max_student_tickets
        stud_rem = max(0, stud_max - stud_issued)
        
        parent_issued = db.today_parent_walkins
        parent_max = self.master.max_parent_tickets
        parent_rem = max(0, parent_max - parent_issued)
        
        now_time = datetime.datetime.now().time()
        
        if now_time >= self.master.cutoff_time:
            self.tv_stud_rem_lbl.configure(text="⏰ CUT-OFF REACHED (CLOSED)", text_color="#e74c3c")
        elif stud_rem <= 0:
            self.tv_stud_rem_lbl.configure(text="🚫 DAILY LIMIT REACHED (0 LEFT)", text_color="#e74c3c")
        else:
            self.tv_stud_rem_lbl.configure(text=f"Available Today: {stud_rem} / {stud_max}", text_color="#f1c40f")

        if now_time >= self.master.cutoff_time:
            self.tv_parent_rem_lbl.configure(text="⏰ CUT-OFF REACHED (CLOSED)", text_color="#e74c3c")
        elif parent_rem <= 0:
            self.tv_parent_rem_lbl.configure(text="🚫 DAILY LIMIT REACHED (0 LEFT)", text_color="#e74c3c")
        else:
            self.tv_parent_rem_lbl.configure(text=f"Available Today: {parent_rem} / {parent_max}", text_color="#f1c40f")

        # STUDENT QUEUE DISPLAY
        if getattr(self.master, "student_paused", False):
            self.tv_stud_serving_lbl.configure(text="PAUSED", text_color="#e74c3c")
            self.tv_stud_info_lbl.configure(text="")
            stud_upcoming = []
        elif stud_queue:
            active_stud = stud_queue[0]
            self.tv_stud_serving_lbl.configure(text=f"S-{active_stud['id']:03d}", text_color="#2ecc71")
            
            if active_stud.get("is_appointment"):
                self.tv_stud_info_lbl.configure(text=f"📅 APPOINTMENT SLOT ({active_stud['appt_time']})", text_color="#f39c12")
            else:
                self.tv_stud_info_lbl.configure(text="")
                
            stud_upcoming = stud_queue[1:] + stud_prep_queue
            if flash_type == "Student":
                self.flash_serving_label(self.tv_stud_serving_lbl, "#2ecc71")
        else:
            self.tv_stud_serving_lbl.configure(text="S---", text_color="#2ecc71")
            self.tv_stud_info_lbl.configure(text="")
            stud_upcoming = []

        for idx in range(4):
            if idx < len(stud_upcoming):
                t_data = stud_upcoming[idx]
                tag = f"S-{t_data['id']:03d}"
                if t_data.get("is_appointment"):
                    tag += " 📅"
                self.stud_prep_badges[idx].configure(text=tag, text_color="#2ecc71", fg_color="#273c75")
            else:
                self.stud_prep_badges[idx].configure(text="--", text_color="#7f8c8d", fg_color="#1e272e")

        # PARENT QUEUE DISPLAY
        if getattr(self.master, "parent_paused", False):
            self.tv_parent_serving_lbl.configure(text="PAUSED", text_color="#e74c3c")
            self.tv_parent_info_lbl.configure(text="")
            parent_upcoming = []
        elif parent_queue:
            active_parent = parent_queue[0]
            self.tv_parent_serving_lbl.configure(text=f"G-{active_parent['id']:03d}", text_color="#e74c3c")
            
            if active_parent.get("is_appointment"):
                self.tv_parent_info_lbl.configure(text=f"📅 APPOINTMENT SLOT ({active_parent['appt_time']})", text_color="#f39c12")
            else:
                self.tv_parent_info_lbl.configure(text="")

            parent_upcoming = parent_queue[1:] + parent_prep_queue
            if flash_type == "Parent":
                self.flash_serving_label(self.tv_parent_serving_lbl, "#e74c3c")
        else:
            self.tv_parent_serving_lbl.configure(text="G---", text_color="#e74c3c")
            self.tv_parent_info_lbl.configure(text="")
            parent_upcoming = []

        for idx in range(4):
            if idx < len(parent_upcoming):
                t_data = parent_upcoming[idx]
                tag = f"G-{t_data['id']:03d}"
                if t_data.get("is_appointment"):
                    tag += " 📅"
                self.parent_prep_badges[idx].configure(text=tag, text_color="#e67e22", fg_color="#273c75")
            else:
                self.parent_prep_badges[idx].configure(text="--", text_color="#7f8c8d", fg_color="#1e272e")

# ================================================================
# ⌨️ ENHANCED VIRTUAL KEYBOARD FRAME
# ================================================================
class EmbeddedVirtualKeyboard(ctk.CTkFrame):
    def __init__(self, master, get_target_func, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.get_target_func = get_target_func
        self.is_caps = True
        self.keys_layout = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '.'],
            ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
            ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
            ['CAPS', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', 'CLEAR'],
            ['SPACE', '⌫']
        ]
        self.button_widgets = {}
        self.build_keyboard()

    def build_keyboard(self):
        for row in self.keys_layout:
            row_frame = ctk.CTkFrame(self, fg_color="transparent")
            row_frame.pack(pady=2, fill="x", expand=True)
            for key in row:
                btn_width = 160 if key == "SPACE" else (65 if key in ["⌫", "CLEAR", "CAPS"] else 34)
                fg_col = "#c0392b" if key in ["⌫", "CLEAR"] else ("#2980b9" if key in ["SPACE", "CAPS"] else "#34495e")
                hover_col = "#e74c3c" if key in ["⌫", "CLEAR"] else ("#3498db" if key in ["SPACE", "CAPS"] else "#2c3e50")

                btn = ctk.CTkButton(
                    row_frame, text=key, width=btn_width, height=38,
                    font=("Helvetica", 12, "bold"), fg_color=fg_col, hover_color=hover_col,
                    command=lambda k=key: self.on_key_press(k)
                )
                btn.pack(side="left", padx=2, expand=True)
                self.button_widgets[key] = btn

    def on_key_press(self, key):
        target_entry = self.get_target_func()
        if not target_entry:
            return

        if key == "⌫":
            current_text = target_entry.get()
            target_entry.delete(0, 'end')
            target_entry.insert(0, current_text[:-1])
        elif key == "CLEAR":
            target_entry.delete(0, 'end')
        elif key == "CAPS":
            self.is_caps = not self.is_caps
            for k_text, btn_widget in self.button_widgets.items():
                if len(k_text) == 1 and k_text.isalpha():
                    btn_widget.configure(text=k_text.upper() if self.is_caps else k_text.lower())
        elif key == "SPACE":
            target_entry.insert('end', ' ')
        else:
            char_to_add = key.upper() if self.is_caps else key.lower()
            target_entry.insert('end', char_to_add)

# ================================================================
# 🎫 TOUCH-OPTIMIZED KIOSK
# ================================================================
class CombinedKioskWindow(ctk.CTkToplevel):
    def __init__(self, master_app):
        super().__init__(master_app)
        self.master_app = master_app
        self.title("Kiosk Ticketing & Advance Appointment Terminal")
        
        self.geometry("1100x750+0+0")
        self.after(100, lambda: self.state('zoomed'))
        
        self.active_stud_entry = None
        self.active_parent_entry = None

        header_frame = ctk.CTkFrame(self, fg_color="#1a252f", height=50)
        header_frame.pack(fill="x", padx=10, pady=(10, 0))
        
        self.typewriter_lbl = ctk.CTkLabel(header_frame, text="", font=("Helvetica", 16, "bold"), text_color="#f1c40f")
        self.typewriter_lbl.pack(pady=10)
        
        self.welcome_msg = "👋 Welcome to Campus Queue Kiosk! Book appointments for upcoming days or pay today."
        self.typewriter_idx = 0
        self.animate_typewriter()

        self.available_days = self.get_next_days_list()

        main_content = ctk.CTkFrame(self, fg_color="transparent")
        main_content.pack(fill="both", expand=True, padx=10, pady=10)
        main_content.grid_columnconfigure((0, 1), weight=1)
        main_content.grid_rowconfigure(0, weight=1)
        
        # 🎓 STUDENT PANEL
        self.student_panel = ctk.CTkFrame(main_content, corner_radius=15)
        self.student_panel.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        
        ctk.CTkLabel(self.student_panel, text="🎓 Student Kiosk Terminal", font=("Helvetica", 18, "bold")).pack(pady=(10, 5))
        
        ctk.CTkLabel(self.student_panel, text="ID / Name:", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=25)
        self.stud_num_entry = ctk.CTkEntry(self.student_panel, placeholder_text="Enter ID Number or Name", height=35)
        self.stud_num_entry.pack(fill="x", padx=25, pady=(0, 5))
        self.stud_num_entry.bind("<FocusIn>", lambda e: self.set_active_stud_entry(self.stud_num_entry))
        self.active_stud_entry = self.stud_num_entry

        ctk.CTkLabel(self.student_panel, text="Purpose & Payment Amount:", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=25)
        stud_opts_frame = ctk.CTkFrame(self.student_panel, fg_color="transparent")
        stud_opts_frame.pack(fill="x", padx=25, pady=2)
        
        self.stud_purpose_var = ctk.StringVar(value="Tuition")
        ctk.CTkOptionMenu(stud_opts_frame, variable=self.stud_purpose_var, values=["Tuition", "Books", "Documents", "Other"], width=130, height=35).pack(side="left")
        
        self.stud_pay_amount_entry = ctk.CTkEntry(stud_opts_frame, placeholder_text="Amount (e.g. 1000)", height=35)
        self.stud_pay_amount_entry.pack(side="right", fill="x", expand=True, padx=(10, 0))
        self.stud_pay_amount_entry.bind("<FocusIn>", lambda e: self.set_active_stud_entry(self.stud_pay_amount_entry))

        ctk.CTkLabel(self.student_panel, text="📅 Appointment Target Day:", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=25, pady=(5, 0))
        self.stud_day_var = ctk.StringVar(value=self.available_days[0])
        ctk.CTkOptionMenu(self.student_panel, variable=self.stud_day_var, values=self.available_days, height=35).pack(fill="x", padx=25, pady=2)

        EmbeddedVirtualKeyboard(self.student_panel, lambda: self.active_stud_entry).pack(pady=5, padx=10, fill="x")

        btn_stud_frame = ctk.CTkFrame(self.student_panel, fg_color="transparent")
        btn_stud_frame.pack(pady=5)
        ctk.CTkButton(btn_stud_frame, text="🎟️ Pay Today (Walk-In)", command=lambda: self.generate_student_ticket(is_appointment=False), fg_color="#2ecc71", hover_color="#27ae60", height=40, width=170).pack(side="left", padx=5)
        ctk.CTkButton(btn_stud_frame, text="📅 Book Appointment", command=lambda: self.generate_student_ticket(is_appointment=True), fg_color="#f39c12", hover_color="#d35400", height=40, width=170).pack(side="right", padx=5)

        # 👨‍👩‍👧 PARENT PANEL
        self.parent_panel = ctk.CTkFrame(main_content, corner_radius=15)
        self.parent_panel.grid(row=0, column=1, padx=10, pady=5, sticky="nsew")
        
        ctk.CTkLabel(self.parent_panel, text="👨‍👩‍👧 Parent / Guardian Terminal", font=("Helvetica", 18, "bold")).pack(pady=(10, 5))
        
        ctk.CTkLabel(self.parent_panel, text="Parent Name:", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=25)
        self.parent_num_entry = ctk.CTkEntry(self.parent_panel, placeholder_text="Enter Parent / Guardian Name", height=35)
        self.parent_num_entry.pack(fill="x", padx=25, pady=(0, 5))
        self.parent_num_entry.bind("<FocusIn>", lambda e: self.set_active_parent_entry(self.parent_num_entry))
        self.active_parent_entry = self.parent_num_entry

        ctk.CTkLabel(self.parent_panel, text="Purpose & Payment Amount:", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=25)
        parent_opts_frame = ctk.CTkFrame(self.parent_panel, fg_color="transparent")
        parent_opts_frame.pack(fill="x", padx=25, pady=2)
        
        self.parent_purpose_var = ctk.StringVar(value="Tuition")
        ctk.CTkOptionMenu(parent_opts_frame, variable=self.parent_purpose_var, values=["Tuition", "Books", "Documents", "Other"], width=130, height=35).pack(side="left")
        
        self.parent_pay_amount_entry = ctk.CTkEntry(parent_opts_frame, placeholder_text="Amount (e.g. 2000)", height=35)
        self.parent_pay_amount_entry.pack(side="right", fill="x", expand=True, padx=(10, 0))
        self.parent_pay_amount_entry.bind("<FocusIn>", lambda e: self.set_active_parent_entry(self.parent_pay_amount_entry))

        ctk.CTkLabel(self.parent_panel, text="📅 Appointment Target Day:", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=25, pady=(5, 0))
        self.parent_day_var = ctk.StringVar(value=self.available_days[0])
        ctk.CTkOptionMenu(self.parent_panel, variable=self.parent_day_var, values=self.available_days, height=35).pack(fill="x", padx=25, pady=2)

        EmbeddedVirtualKeyboard(self.parent_panel, lambda: self.active_parent_entry).pack(pady=5, padx=10, fill="x")

        btn_parent_frame = ctk.CTkFrame(self.parent_panel, fg_color="transparent")
        btn_parent_frame.pack(pady=5)
        ctk.CTkButton(btn_parent_frame, text="🎟️ Pay Today (Walk-In)", command=lambda: self.generate_parent_ticket(is_appointment=False), fg_color="#2ecc71", hover_color="#27ae60", height=40, width=170).pack(side="left", padx=5)
        ctk.CTkButton(btn_parent_frame, text="📅 Book Appointment", command=lambda: self.generate_parent_ticket(is_appointment=True), fg_color="#f39c12", hover_color="#d35400", height=40, width=170).pack(side="right", padx=5)

    def set_active_stud_entry(self, widget):
        self.active_stud_entry = widget

    def set_active_parent_entry(self, widget):
        self.active_parent_entry = widget

    def animate_typewriter(self):
        if self.typewriter_idx <= len(self.welcome_msg):
            self.typewriter_lbl.configure(text=self.welcome_msg[:self.typewriter_idx])
            self.typewriter_idx += 1
            self.after(60, self.animate_typewriter)
        else:
            self.after(4000, self.reset_typewriter)

    def reset_typewriter(self):
        self.typewriter_idx = 0
        self.animate_typewriter()

    def get_next_days_list(self):
        days = []
        now = datetime.datetime.now()
        for i in range(7):
            target_date = now + datetime.timedelta(days=i)
            if i == 0:
                label = f"Today ({target_date.strftime('%Y-%m-%d')})"
            elif i == 1:
                label = f"Tomorrow ({target_date.strftime('%Y-%m-%d')})"
            else:
                label = target_date.strftime("%Y-%m-%d (%A)")
            days.append(label)
        return days

    def calculate_projected_time(self, current_queue_size):
        est_minutes = (current_queue_size + 1) * 6
        projected = datetime.datetime.now() + datetime.timedelta(minutes=est_minutes)
        return projected.strftime("%I:%M %p")

    def show_toast_popup(self, ticket_code, title="Ticket Issued", color="#2ecc71"):
        toast = ctk.CTkToplevel(self)
        toast.title(title)
        toast.geometry("420x220")
        toast.attributes("-topmost", True)
        toast.configure(fg_color="#2c3e50")
        
        ctk.CTkLabel(toast, text=f"✅ {title}", font=("Helvetica", 18, "bold"), text_color=color).pack(pady=(20, 5))
        ctk.CTkLabel(toast, text=ticket_code, font=("Helvetica", 14, "bold"), text_color="#ffffff").pack(pady=5)
        toast.after(3500, toast.destroy)

    def generate_student_ticket(self, is_appointment=False):
        now_time = datetime.datetime.now().time()
        target_day_str = self.stud_day_var.get()
        is_for_today = ("today" in target_day_str.lower())

        if not is_appointment and now_time >= self.master_app.cutoff_time:
            self.show_toast_popup("Queue is Closed for Today!\nCut-off time has passed.", title="Cut-off Reached", color="#e74c3c")
            return

        if not is_appointment and db.today_student_walkins >= self.master_app.max_student_tickets:
            self.show_toast_popup("Daily Walk-in Quota Reached!\nPlease book an advance appointment.", title="Limit Reached", color="#e74c3c")
            return

        student_input = self.stud_num_entry.get().strip() or "Walk-In Student"
        purpose = self.stud_purpose_var.get()
        amount_str = self.stud_pay_amount_entry.get().strip()
        full_purpose = f"{purpose} (Php {amount_str})" if amount_str else purpose

        if is_appointment and not is_for_today:
            target_date_clean = target_day_str.split("(")[1].replace(")", "").strip() if "(" in target_day_str else target_day_str
            slot_num = get_next_booking_slot(target_date_clean, is_parent=False)
            appt_time_info = f"{target_date_clean} @ Slot #{slot_num:03d}"
            
            adv_ticket = {
                "id": slot_num,
                "student": f"[Student] {student_input}",
                "purpose": full_purpose,
                "appt_time": appt_time_info,
                "is_parent": False
            }
            db.advance_appointments.append(adv_ticket)
            save_current_queues_state()
            db.log_to_excel(slot_num, student_input, full_purpose, f"Advance Appointment Reserved ({appt_time_info})", is_parent=False)
            
            print_thermal_receipt("S", slot_num, student_input, full_purpose, appt_time=appt_time_info)
            msg_str = f"Ticket: S-{slot_num:03d}\nPayer: {student_input}\nDetails: {full_purpose}\n📅 Slot Reserved: {appt_time_info}"
            self.show_toast_popup(msg_str, title="Appointment Ticket Issued", color="#f39c12")
        else:
            ticket_num = get_next_sequence_number(queue_type="Student")
            db.today_student_walkins += 1
            
            all_studs = [t for t in db.paying_queue + db.preparation_queue if "[Parent]" not in t['student']]
            appt_time_info = f"Today @ {self.calculate_projected_time(len(all_studs))}" if is_appointment else "N/A"

            ticket_data = {
                "id": ticket_num, 
                "student": f"[Student] {student_input}", 
                "purpose": full_purpose,
                "is_appointment": is_appointment,
                "appt_time": appt_time_info
            }
            
            active_stud_queue = [t for t in db.paying_queue if "[Parent]" not in t['student']]
            status_text = f"Today's Appointment ({appt_time_info})" if is_appointment else "Queued for Payment (Student)"

            if len(active_stud_queue) < 3:
                db.paying_queue.append(ticket_data)
            else:
                db.preparation_queue.append(ticket_data)

            save_current_queues_state()
            db.log_to_excel(ticket_num, student_input, full_purpose, status_text, is_parent=False)
            print_thermal_receipt("S", ticket_num, student_input, full_purpose, appt_time=appt_time_info if is_appointment else None)
            
            msg_str = f"Ticket: S-{ticket_num:03d}\nPayer: {student_input}\nDetails: {full_purpose}"
            self.show_toast_popup(msg_str, title="Today's Ticket Issued")

        self.stud_num_entry.delete(0, 'end')
        self.stud_pay_amount_entry.delete(0, 'end')
        self.master_app.update_ui_displays()

    def generate_parent_ticket(self, is_appointment=False):
        now_time = datetime.datetime.now().time()
        target_day_str = self.parent_day_var.get()
        is_for_today = ("today" in target_day_str.lower())

        if not is_appointment and now_time >= self.master_app.cutoff_time:
            self.show_toast_popup("Queue is Closed for Today!\nCut-off time has passed.", title="Cut-off Reached", color="#e74c3c")
            return

        if not is_appointment and db.today_parent_walkins >= self.master_app.max_parent_tickets:
            self.show_toast_popup("Daily Walk-in Quota Reached!\nPlease book an advance appointment.", title="Limit Reached", color="#e74c3c")
            return

        parent_input = self.parent_num_entry.get().strip() or "Walk-In Parent"
        purpose = self.parent_purpose_var.get()
        amount_str = self.parent_pay_amount_entry.get().strip()
        full_purpose = f"{purpose} (Php {amount_str})" if amount_str else purpose

        if is_appointment and not is_for_today:
            target_date_clean = target_day_str.split("(")[1].replace(")", "").strip() if "(" in target_day_str else target_day_str
            slot_num = get_next_booking_slot(target_date_clean, is_parent=True)
            appt_time_info = f"{target_date_clean} @ Slot #{slot_num:03d}"
            
            adv_ticket = {
                "id": slot_num,
                "student": f"[Parent] {parent_input}",
                "purpose": full_purpose,
                "appt_time": appt_time_info,
                "is_parent": True
            }
            db.advance_appointments.append(adv_ticket)
            save_current_queues_state()
            db.log_to_excel(slot_num, parent_input, full_purpose, f"Advance Appointment Reserved ({appt_time_info})", is_parent=True)
            print_thermal_receipt("G", slot_num, parent_input, full_purpose, appt_time=appt_time_info)
            
            msg_str = f"Ticket: G-{slot_num:03d}\nPayer: {parent_input}\nDetails: {full_purpose}\n📅 Slot Reserved: {appt_time_info}"
            self.show_toast_popup(msg_str, title="Appointment Ticket Issued", color="#f39c12")
        else:
            ticket_num = get_next_sequence_number(queue_type="Parent")
            db.today_parent_walkins += 1

            all_parents = [t for t in db.paying_queue + db.preparation_queue if "[Parent]" in t['student']]
            appt_time_info = f"Today @ {self.calculate_projected_time(len(all_parents))}" if is_appointment else "N/A"

            ticket_data = {
                "id": ticket_num, 
                "student": f"[Parent] {parent_input}", 
                "purpose": full_purpose,
                "is_appointment": is_appointment,
                "appt_time": appt_time_info
            }
            
            active_parent_queue = [t for t in db.paying_queue if "[Parent]" in t['student']]
            status_text = f"Today's Appointment ({appt_time_info})" if is_appointment else "Queued for Payment (Parent)"

            if len(active_parent_queue) < 3:
                db.paying_queue.append(ticket_data)
            else:
                db.preparation_queue.append(ticket_data)

            save_current_queues_state()
            db.log_to_excel(ticket_num, parent_input, full_purpose, status_text, is_parent=True)
            print_thermal_receipt("G", ticket_num, parent_input, full_purpose, appt_time=appt_time_info if is_appointment else None)
            
            msg_str = f"Ticket: G-{ticket_num:03d}\nPayer: {parent_input}\nDetails: {full_purpose}"
            self.show_toast_popup(msg_str, title="Today's Ticket Issued")

        self.parent_num_entry.delete(0, 'end')
        self.parent_pay_amount_entry.delete(0, 'end')
        self.master_app.update_ui_displays()

# ================================================================
# 💼 CASHIER OPERATION DESK
# ================================================================
class CashierDeskApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Cashier Operation Desk")
        self.geometry("980x780+50+50")
        
        db.init_db()
        self.last_completed_student = None
        self.last_completed_parent = None
        
        self.student_paused = False
        self.parent_paused = False
        
        self.max_student_tickets = 130
        self.max_parent_tickets = 130
        self.max_student_appts = 50
        self.max_parent_appts = 50
        self.cutoff_time = datetime.time(16, 0)

        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # STUDENT CASHIER DESK
        self.student_cashier_panel = ctk.CTkFrame(self, corner_radius=15)
        self.student_cashier_panel.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        
        ctk.CTkLabel(self.student_cashier_panel, text="💼 Student Cashier Desk", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        self.stud_badge_lbl = ctk.CTkLabel(self.student_cashier_panel, text="Waiting in Line: 0", font=("Helvetica", 13, "bold"), text_color="#f1c40f")
        self.stud_badge_lbl.pack(pady=2)

        self.student_handling_lbl = ctk.CTkLabel(self.student_cashier_panel, text="No Student Active\nReady for next call.", font=("Helvetica", 14), text_color="#3498db")
        self.student_handling_lbl.pack(pady=10)
        
        ctk.CTkButton(self.student_cashier_panel, text="📢 Call Current Ticket", command=lambda: self.call_ticket("Student"), fg_color="#3498db", hover_color="#2980b9").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.student_cashier_panel, text="⏭️ Next / Free Ticket Slot", command=lambda: self.next_ticket("Student"), fg_color="#e67e22", hover_color="#d35400").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.student_cashier_panel, text="🚫 Mark Absent & Free Slot", command=lambda: self.invalidate_ticket_slot("Student"), fg_color="#e74c3c", hover_color="#c0392b").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.student_cashier_panel, text="🔄 Recall Last Ticket", command=lambda: self.recall_ticket("Student"), fg_color="#2c3e50", hover_color="#1a252f").pack(pady=4, padx=30, fill="x")
        
        self.btn_pause_student = ctk.CTkButton(self.student_cashier_panel, text="⏸️ Pause Desk", command=lambda: self.toggle_pause("Student"), fg_color="#d35400", hover_color="#e67e22")
        self.btn_pause_student.pack(pady=4, padx=30, fill="x")
        
        ctk.CTkButton(self.student_cashier_panel, text="📊 Open Queue Database", command=self.open_database_view, fg_color="#9b59b6", hover_color="#8e44ad").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.student_cashier_panel, text="🔄 Reset Daily Queue Slot (Today Only)", command=lambda: self.confirm_and_reset_slot("Student"), fg_color="#900C3F", hover_color="#581845").pack(pady=10, padx=30, fill="x")

        # PARENTS CASHIER DESK
        self.parent_cashier_panel = ctk.CTkFrame(self, corner_radius=15)
        self.parent_cashier_panel.grid(row=0, column=1, padx=15, pady=15, sticky="nsew")
        
        ctk.CTkLabel(self.parent_cashier_panel, text="💼 Parents Cashier Desk", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        self.parent_badge_lbl = ctk.CTkLabel(self.parent_cashier_panel, text="Waiting in Line: 0", font=("Helvetica", 13, "bold"), text_color="#f1c40f")
        self.parent_badge_lbl.pack(pady=2)

        self.parent_handling_lbl = ctk.CTkLabel(self.parent_cashier_panel, text="No Parent Active\nReady for next call.", font=("Helvetica", 14), text_color="#3498db")
        self.parent_handling_lbl.pack(pady=10)
        
        ctk.CTkButton(self.parent_cashier_panel, text="📢 Call Current Ticket", command=lambda: self.call_ticket("Parent"), fg_color="#3498db", hover_color="#2980b9").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.parent_cashier_panel, text="⏭️ Next / Free Ticket Slot", command=lambda: self.next_ticket("Parent"), fg_color="#e67e22", hover_color="#d35400").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.parent_cashier_panel, text="🚫 Mark Absent & Free Slot", command=lambda: self.invalidate_ticket_slot("Parent"), fg_color="#e74c3c", hover_color="#c0392b").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.parent_cashier_panel, text="🔄 Recall Last Ticket", command=lambda: self.recall_ticket("Parent"), fg_color="#2c3e50", hover_color="#1a252f").pack(pady=4, padx=30, fill="x")
        
        self.btn_pause_parent = ctk.CTkButton(self.parent_cashier_panel, text="⏸️ Pause Desk", command=lambda: self.toggle_pause("Parent"), fg_color="#d35400", hover_color="#e67e22")
        self.btn_pause_parent.pack(pady=4, padx=30, fill="x")
        
        ctk.CTkButton(self.parent_cashier_panel, text="📊 Open Queue Database", command=self.open_database_view, fg_color="#9b59b6", hover_color="#8e44ad").pack(pady=4, padx=30, fill="x")
        ctk.CTkButton(self.parent_cashier_panel, text="🔄 Reset Daily Queue Slot (Today Only)", command=lambda: self.confirm_and_reset_slot("Parent"), fg_color="#900C3F", hover_color="#581845").pack(pady=10, padx=30, fill="x")

        # CASHIER CONTROLS PANEL
        self.control_panel = ctk.CTkFrame(self, corner_radius=15, fg_color="#2c3e50")
        self.control_panel.grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 15), sticky="ew")
        
        ctk.CTkLabel(self.control_panel, text="⚙️ Cashier Flow & Daily Limits Configuration", font=("Helvetica", 15, "bold"), text_color="#f5cd79").pack(pady=(10, 5))
        
        input_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        input_frame.pack(pady=5, padx=10)
        
        ctk.CTkLabel(input_frame, text="Max Student Walk-ins:", font=("Helvetica", 11, "bold")).grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.entry_stud_limit = ctk.CTkEntry(input_frame, width=65)
        self.entry_stud_limit.insert(0, "130")
        self.entry_stud_limit.grid(row=0, column=1, padx=4, pady=4)

        ctk.CTkLabel(input_frame, text="Max Parent Walk-ins:", font=("Helvetica", 11, "bold")).grid(row=0, column=2, padx=4, pady=4, sticky="e")
        self.entry_parent_limit = ctk.CTkEntry(input_frame, width=65)
        self.entry_parent_limit.insert(0, "130")
        self.entry_parent_limit.grid(row=0, column=3, padx=4, pady=4)

        ctk.CTkLabel(input_frame, text="Cut-off Time (HH:MM):", font=("Helvetica", 11, "bold")).grid(row=0, column=4, padx=4, pady=4, sticky="e")
        self.entry_cutoff = ctk.CTkEntry(input_frame, width=70)
        self.entry_cutoff.insert(0, "16:00")
        self.entry_cutoff.grid(row=0, column=5, padx=4, pady=4)

        ctk.CTkLabel(input_frame, text="Max Student Appts:", font=("Helvetica", 11, "bold")).grid(row=1, column=0, padx=4, pady=4, sticky="e")
        self.entry_stud_appt_limit = ctk.CTkEntry(input_frame, width=65)
        self.entry_stud_appt_limit.insert(0, "50")
        self.entry_stud_appt_limit.grid(row=1, column=1, padx=4, pady=4)

        ctk.CTkLabel(input_frame, text="Max Parent Appts:", font=("Helvetica", 11, "bold")).grid(row=1, column=2, padx=4, pady=4, sticky="e")
        self.entry_parent_appt_limit = ctk.CTkEntry(input_frame, width=65)
        self.entry_parent_appt_limit.insert(0, "50")
        self.entry_parent_appt_limit.grid(row=1, column=3, padx=4, pady=4)

        ctk.CTkButton(input_frame, text="💾 Save Settings", command=self.apply_flow_settings, fg_color="#27ae60", hover_color="#219a52", width=120).grid(row=1, column=4, columnspan=2, padx=10, pady=4)

        self.tv_window = PublicTVMonitor(self)
        self.kiosk_window = CombinedKioskWindow(self)
        self.update_ui_displays()
        
        # Check for crashed or interrupted billing sessions
        self.after(500, self.check_interrupted_session)

    def confirm_and_reset_slot(self, queue_type):
        """Displays confirmation dialog before resetting today's queue slot counter."""
        confirm = messagebox.askyesno(
            "Confirm Queue Slot Reset",
            f"Are you sure you want to reset today's active {queue_type} slot counter back to Slot 1?\n\n"
            "This will only reset today's queue sequence and will NOT affect future date appointments.",
            icon='warning'
        )
        if confirm:
            new_slot = reset_daily_slot_counter(queue_type)
            messagebox.showinfo(
                "Slot Counter Reset",
                f"Today's {queue_type} daily sequence counter has been successfully reset back to Slot #{new_slot:03d}."
            )
            self.update_ui_displays()

    def check_interrupted_session(self):
        """Restores billing screen state if app crashed or closed mid-transaction."""
        session = get_active_session()
        if session.get("is_active"):
            ticket = session.get("ticket_number", "Unknown")
            payer = session.get("payer_name", "Unknown Payer")
            messagebox.showwarning(
                "Billing Restored", 
                f"An interrupted billing session was detected!\n\nTicket: {ticket}\nPayer: {payer}\nRestoring active transaction..."
            )

    def apply_flow_settings(self):
        try:
            s_limit = int(self.entry_stud_limit.get().strip())
            p_limit = int(self.entry_parent_limit.get().strip())
            s_appt_limit = int(self.entry_stud_appt_limit.get().strip())
            p_appt_limit = int(self.entry_parent_appt_limit.get().strip())
            cutoff_str = self.entry_cutoff.get().strip()
            parsed_time = datetime.datetime.strptime(cutoff_str, "%H:%M").time()

            self.max_student_tickets = s_limit
            self.max_parent_tickets = p_limit
            self.max_student_appts = s_appt_limit
            self.max_parent_appts = p_appt_limit
            self.cutoff_time = parsed_time

            messagebox.showinfo("Settings Saved", 
                f"Daily Limits & Cut-off Updated!\n"
                f"Student Walk-ins: {s_limit} | Appts: {s_appt_limit}\n"
                f"Parent Walk-ins: {p_limit} | Appts: {p_appt_limit}\n"
                f"Cut-off Time: {parsed_time.strftime('%I:%M %p')}"
            )
            self.update_ui_displays()
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numeric limit counts and time format (HH:MM e.g., 16:00).")

    def toggle_pause(self, queue_type):
        voice_label = "Student" if queue_type == "Student" else "Guardian"
        if queue_type == "Student":
            self.student_paused = not self.student_paused
            if self.student_paused:
                self.btn_pause_student.configure(text="▶️ Resume Desk", fg_color="#27ae60", hover_color="#2ecc71")
                speak_text(f"{voice_label} desk is now paused.")
            else:
                self.btn_pause_student.configure(text="⏸️ Pause Desk", fg_color="#d35400", hover_color="#e67e22")
                speak_text(f"{voice_label} desk is now resumed.")
        else:
            self.parent_paused = not self.parent_paused
            if self.parent_paused:
                self.btn_pause_parent.configure(text="▶️ Resume Desk", fg_color="#27ae60", hover_color="#2ecc71")
                speak_text(f"{voice_label} desk is now paused.")
            else:
                self.btn_pause_parent.configure(text="⏸️ Pause Desk", fg_color="#d35400", hover_color="#e67e22")
                speak_text(f"{voice_label} desk is now resumed.")
        self.update_ui_displays()

    def get_first_ticket_of_type(self, target_type):
        for ticket in db.paying_queue:
            is_parent = "[Parent]" in ticket['student']
            if (target_type == "Parent" and is_parent) or (target_type == "Student" and not is_parent):
                return ticket
        return None

    def update_ui_displays(self, flash_type=None):
        stud_ticket = self.get_first_ticket_of_type("Student")
        parent_ticket = self.get_first_ticket_of_type("Parent")

        all_queue = db.paying_queue + db.preparation_queue
        stud_count = len([t for t in all_queue if "[Parent]" not in t['student']])
        parent_count = len([t for t in all_queue if "[Parent]" in t['student']])

        self.stud_badge_lbl.configure(text=f"Waiting in Line: {stud_count}")
        self.parent_badge_lbl.configure(text=f"Waiting in Line: {parent_count}")

        if self.student_paused:
            self.student_handling_lbl.configure(text="⛔ DESK PAUSED\nCounter closed temporarily.", text_color="#e74c3c")
        elif stud_ticket:
            appt_str = f"\n📅 Appt Time: {stud_ticket['appt_time']}" if stud_ticket.get('is_appointment') else ""
            self.student_handling_lbl.configure(text=f"Active Queue: S-{stud_ticket['id']:03d}{appt_str}\nID/Name: {stud_ticket['student']}\nPurpose: {stud_ticket['purpose']}", text_color="#3498db")
        else:
            self.student_handling_lbl.configure(text="No Student Active\nReady for next call.", text_color="#3498db")

        if self.parent_paused:
            self.parent_handling_lbl.configure(text="⛔ DESK PAUSED\nCounter closed temporarily.", text_color="#e74c3c")
        elif parent_ticket:
            appt_str = f"\n📅 Appt Time: {parent_ticket['appt_time']}" if parent_ticket.get('is_appointment') else ""
            self.parent_handling_lbl.configure(text=f"Active Queue: G-{parent_ticket['id']:03d}{appt_str}\nID/Name: {parent_ticket['student']}\nPurpose: {parent_ticket['purpose']}", text_color="#3498db")
        else:
            self.parent_handling_lbl.configure(text="No Parent Active\nReady for next call.", text_color="#3498db")
            
        self.tv_window.update_tv_screen(flash_type=flash_type)

    def call_ticket(self, queue_type):
        is_paused = self.student_paused if queue_type == "Student" else self.parent_paused
        if is_paused:
            messagebox.showwarning("Desk Paused", f"The {queue_type} Desk is currently paused.")
            return

        current = self.get_first_ticket_of_type(queue_type)
        if current:
            prefix = "G" if queue_type == "Parent" else "S"
            sync_active_billing(f"{prefix}-{current['id']:03d}", current['purpose'], payer_name=current['student'])
            
            trigger_arduino_buzzer()
            label = get_ticket_voice_label(current)
            speak_text(f"Calling {label}, Calling {label}")
            self.update_ui_displays(flash_type=queue_type)
        else:
            speak_text(f"There are no active {queue_type.lower()} numbers to call.")

    def next_ticket(self, queue_type):
        is_paused = self.student_paused if queue_type == "Student" else self.parent_paused
        if is_paused:
            messagebox.showwarning("Desk Paused", f"The {queue_type} Desk is currently paused.")
            return

        is_parent_type = (queue_type == "Parent")
        current = self.get_first_ticket_of_type(queue_type)
        if current:
            db.paying_queue.remove(current)
            save_current_queues_state()
            status_text = f"{queue_type} Appointment Completed" if current.get('is_appointment') else f"{queue_type} Payment Completed"
            db.log_to_excel(current['id'], current['student'], current['purpose'], status_text, is_parent=is_parent_type)
            
            clear_active_billing()

            if queue_type == "Student":
                self.last_completed_student = current
            else:
                self.last_completed_parent = current
            
            for prep in list(db.preparation_queue):
                is_parent = "[Parent]" in prep['student']
                if (queue_type == "Parent" and is_parent) or (queue_type == "Student" and not is_parent):
                    db.preparation_queue.remove(prep)
                    db.paying_queue.append(prep)
                    save_current_queues_state()
                    db.log_to_excel(prep['id'], prep['student'], prep['purpose'], f"Promoted to Paying ({queue_type})", is_parent=is_parent_type)
                    break
                
            next_one = self.get_first_ticket_of_type(queue_type)
            if next_one:
                trigger_arduino_buzzer()
                label = get_ticket_voice_label(next_one)
                speak_text(f"Next {label}, Next {label}")
                self.update_ui_displays(flash_type=queue_type)
            else:
                speak_text(f"{queue_type} queue line is now empty.")
                self.update_ui_displays()
        else:
            speak_text(f"No {queue_type.lower()}s are currently waiting.")

    def invalidate_ticket_slot(self, queue_type):
        is_paused = self.student_paused if queue_type == "Student" else self.parent_paused
        if is_paused:
            messagebox.showwarning("Desk Paused", f"The {queue_type} Desk is currently paused.")
            return

        is_parent_type = (queue_type == "Parent")
        current = self.get_first_ticket_of_type(queue_type)
        if current:
            prefix = "G" if is_parent_type else "S"
            ticket_code = f"{prefix}-{current['id']:03d}"
            
            db.paying_queue.remove(current)
            save_current_queues_state()
            db.log_to_excel(current['id'], current['student'], current['purpose'], "Invalidated Slot - Absent", is_parent=is_parent_type)
            clear_active_billing()

            for prep in list(db.preparation_queue):
                is_parent = "[Parent]" in prep['student']
                if (queue_type == "Parent" and is_parent) or (queue_type == "Student" and not is_parent):
                    db.preparation_queue.remove(prep)
                    db.paying_queue.append(prep)
                    save_current_queues_state()
                    db.log_to_excel(prep['id'], prep['student'], prep['purpose'], f"Promoted to Paying ({queue_type})", is_parent=is_parent_type)
                    break

            speak_text(f"Ticket {ticket_code} has been marked absent and invalidated.")
            self.update_ui_displays()
        else:
            messagebox.showinfo("No Ticket", f"No active {queue_type.lower()} ticket to invalidate.")

    def recall_ticket(self, queue_type):
        is_paused = self.student_paused if queue_type == "Student" else self.parent_paused
        if is_paused:
            messagebox.showwarning("Desk Paused", f"The {queue_type} Desk is currently paused.")
            return

        is_parent_type = (queue_type == "Parent")
        last_ticket = self.last_completed_student if queue_type == "Student" else self.last_completed_parent
        if last_ticket:
            db.paying_queue.insert(0, last_ticket)
            save_current_queues_state()
            db.log_to_excel(last_ticket['id'], last_ticket['student'], last_ticket['purpose'], f"Recalled to Desk ({queue_type})", is_parent=is_parent_type)
            
            label = get_ticket_voice_label(last_ticket)
            if queue_type == "Student":
                self.last_completed_student = None
            else:
                self.last_completed_parent = None

            self.update_ui_displays(flash_type=queue_type)
            trigger_arduino_buzzer()
            speak_text(f"Recall {label}, Recall {label}")
        else:
            messagebox.showinfo("Recall Empty", f"No recently closed {queue_type.lower()} transactions to recall.")

    def open_database_view(self):
        DatabaseWindow(self, self.update_ui_displays)

def launch_main_system():
    app = CashierDeskApp()
    app.mainloop()

if __name__ == "__main__":
    login_screen = LoginWindow(on_success_bridge=launch_main_system)
    login_screen.mainloop()