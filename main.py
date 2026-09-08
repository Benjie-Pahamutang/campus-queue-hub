import customtkinter as ctk
import database as db
import pyttsx3
import threading
import time
import os
import datetime
import serial  # Added for Arduino communication
from tkinter import messagebox, ttk
from login import LoginWindow

# ================================================================
# 🔌 ARDUINO SERIAL INITIALIZATION & THREAD LOCKING
# ================================================================
ARDUINO_PORT = 'COM3'  # Change to match your system's COM port
serial_lock = threading.Lock()  # Protects COM3 from overlapping writes

try:
    arduino = serial.Serial(ARDUINO_PORT, 9600, timeout=1)
    time.sleep(2)  # Give Arduino time to reset after opening connection
    
    # Clear any junk initialization bytes sent by bootloader to avoid printer gibberish
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
                    arduino.write(b'B\n')  # Send byte 'B' to trigger playQueueChime()
                    arduino.flush()
                except Exception as e:
                    print(f"[Arduino Serial Error]: {e}")
                
    threading.Thread(target=run_buzzer, daemon=True).start()

def print_thermal_receipt(ticket_type_char, ticket_num, student_name, purpose):
    """Sends styled receipt print command to Arduino over Serial (Format: P|TYPE|NUM|NAME|PURPOSE|DATE|TIME)."""
    def run_print():
        if arduino and arduino.is_open:
            with serial_lock:
                try:
                    formatted_num = f"{ticket_num:03d}"
                    now = datetime.datetime.now()
                    date_str = now.strftime("%b %d, %Y")
                    time_str = now.strftime("%I:%M %p")
                    
                    # Format: P|TYPE|NUM|NAME|PURPOSE|DATE|TIME
                    payload = f"P|{ticket_type_char}|{formatted_num}|{student_name}|{purpose}|{date_str}|{time_str}\n"
                    
                    # Flush before write to ensure clean payload execution
                    arduino.reset_output_buffer()
                    arduino.write(payload.encode('utf-8'))
                    arduino.flush()
                except Exception as e:
                    print(f"[Arduino Thermal Printer Error]: {e}")
        else:
            print(f"[Printer Offline] Simulating receipt print: {ticket_type_char}-{ticket_num:03d} | Payer: {student_name} | Purpose: {purpose}")

    threading.Thread(target=run_print, daemon=True).start()

# Ensure separate ticket counters exist in database or initialize them here
if not hasattr(db, 'student_ticket_counter'):
    db.student_ticket_counter = 1
if not hasattr(db, 'parent_ticket_counter'):
    db.parent_ticket_counter = 1

# Attach thermal print function to db module dynamically if needed
db.print_thermal_receipt = print_thermal_receipt

# ================================================================
# 🗣️ TEXT TO SPEECH HELPER
# ================================================================
def speak_text(text):
    """Spawns an asynchronous TTS voice announcement without freezing the UI thread."""
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
    """Helper function to parse whether a ticket belongs to a Student or Guardian/Parent for TTS."""
    student_name = ticket_info.get("student", "")
    if "[Parent]" in student_name:
        return f"guardian number {ticket_info['id']:03d}"
    else:
        return f"student number {ticket_info['id']:03d}"

# ================================================================
# 📋 DATABASE MANAGER POPUP (SEPARATED STUDENT & PARENT TABS)
# ================================================================
class DatabaseWindow(ctk.CTkToplevel):
    def __init__(self, master, update_callback):
        super().__init__(master)
        self.title("Live Queue Database Manager")
        self.geometry("780x540")
        self.update_callback = update_callback
        self.attributes("-topmost", True)
        
        ctk.CTkLabel(self, text="📋 Live Queue Database Records", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=15, pady=5)
        
        self.tab_student = self.tabview.add("🎓 Student Queue")
        self.tab_parent = self.tabview.add("👨‍👩‍👧 Parent / Guardian Queue")
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#2d3436", fieldbackground="#2d3436", foreground="white", rowheight=25)
        style.map("Treeview", background=[('selected', '#1a73e8')])

        self.stud_tree = ttk.Treeview(self.tab_student, columns=("Ticket", "ID_Name", "Purpose", "Phase"), show="headings")
        self.setup_tree_columns(self.stud_tree, "Student ID / Name")
        
        self.parent_tree = ttk.Treeview(self.tab_parent, columns=("Ticket", "ID_Name", "Purpose", "Phase"), show="headings")
        self.setup_tree_columns(self.parent_tree, "Parent Name")
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10, padx=20)
        
        ctk.CTkButton(btn_frame, text="❌ Delete Selected Ticket", fg_color="#e74c3c", hover_color="#c0392b", command=self.delete_selected).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="📊 Open Tab Excel File", fg_color="#27ae60", hover_color="#219a52", command=self.open_excel_app).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="🔄 Refresh Tables", fg_color="#34495e", command=self.load_data).pack(side="right", padx=5)
        
        self.load_data()

    def setup_tree_columns(self, tree_widget, name_header):
        tree_widget.heading("Ticket", text="Ticket No.")
        tree_widget.heading("ID_Name", text=name_header)
        tree_widget.heading("Purpose", text="Purpose")
        tree_widget.heading("Phase", text="Queue Status")
        
        tree_widget.column("Ticket", width=110, anchor="center")
        tree_widget.column("ID_Name", width=220, anchor="w")
        tree_widget.column("Purpose", width=150, anchor="center")
        tree_widget.column("Phase", width=150, anchor="center")
        tree_widget.pack(fill="both", expand=True, padx=5, pady=5)

    def load_data(self):
        for item in self.stud_tree.get_children():
            self.stud_tree.delete(item)
        for item in self.parent_tree.get_children():
            self.parent_tree.delete(item)
            
        for ticket in db.paying_queue:
            is_parent = "[Parent]" in ticket['student']
            phase = "Paying Phase"
            if is_parent:
                self.parent_tree.insert("", "end", values=(f"G-{ticket['id']:03d}", ticket['student'], ticket['purpose'], phase))
            else:
                self.stud_tree.insert("", "end", values=(f"S-{ticket['id']:03d}", ticket['student'], ticket['purpose'], phase))

        for ticket in db.preparation_queue:
            is_parent = "[Parent]" in ticket['student']
            phase = "Prep Phase"
            if is_parent:
                self.parent_tree.insert("", "end", values=(f"G-{ticket['id']:03d}", ticket['student'], ticket['purpose'], phase))
            else:
                self.stud_tree.insert("", "end", values=(f"S-{ticket['id']:03d}", ticket['student'], ticket['purpose'], phase))

    def delete_selected(self):
        current_tab = self.tabview.get()
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
                db.log_to_excel(ticket['id'], ticket['student'], ticket['purpose'], "Absent - Removed by Cashier", is_parent=is_parent_target)
                removed = True
                break
                
        if not removed:
            for ticket in db.preparation_queue:
                ticket_is_parent = "[Parent]" in ticket['student']
                if ticket['id'] == target_id and ticket_is_parent == is_parent_target:
                    db.preparation_queue.remove(ticket)
                    db.log_to_excel(ticket['id'], ticket['student'], ticket['purpose'], "Absent - Removed by Cashier", is_parent=is_parent_target)
                    break
                    
        messagebox.showinfo("Success", f"Ticket {target_ticket_str} has been cleared out.")
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
            messagebox.showwarning("File Missing", f"No Excel records found yet for this queue. Print a ticket first!")

# ================================================================
# 📺 LOBBY TV MONITOR WINDOW (WITH ANIMATIONS & LIVE CLOCK)
# ================================================================
class PublicTVMonitor(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Lobby TV Display")
        
        # Position automatically on Display 2 (or offset screen)
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
        ctk.CTkLabel(self.stud_side, text="NOW SERVING", font=("Helvetica", 18, "bold"), text_color="#ffffff").pack(pady=(5, 0))
        
        self.tv_stud_serving_lbl = ctk.CTkLabel(self.stud_side, text="S---", font=("Helvetica", 75, "bold"), text_color="#2ecc71")
        self.tv_stud_serving_lbl.pack(pady=10)

        stud_prep_panel = ctk.CTkFrame(self.stud_side, fg_color="#151d24", corner_radius=12)
        stud_prep_panel.pack(fill="x", padx=15, pady=(10, 15))
        
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
        ctk.CTkLabel(self.parent_side, text="NOW SERVING", font=("Helvetica", 18, "bold"), text_color="#ffffff").pack(pady=(5, 0))
        
        self.tv_parent_serving_lbl = ctk.CTkLabel(self.parent_side, text="G---", font=("Helvetica", 75, "bold"), text_color="#e74c3c")
        self.tv_parent_serving_lbl.pack(pady=10)

        parent_prep_panel = ctk.CTkFrame(self.parent_side, fg_color="#151d24", corner_radius=12)
        parent_prep_panel.pack(fill="x", padx=15, pady=(10, 15))
        
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
        """Flashes the ticket label to draw visual attention when called."""
        if times > 0:
            current_col = label_widget.cget("text_color")
            next_col = "#f1c40f" if current_col == original_color else original_color
            label_widget.configure(text_color=next_col)
            self.after(250, lambda: self.flash_serving_label(label_widget, original_color, times - 1))
        else:
            label_widget.configure(text_color=original_color)

    def update_tv_screen(self, flash_type=None):
        all_queue = db.paying_queue + db.preparation_queue
        
        stud_queue = [t for t in all_queue if "[Parent]" not in t['student']]
        parent_queue = [t for t in all_queue if "[Parent]" in t['student']]

        if getattr(self.master, "student_paused", False):
            self.tv_stud_serving_lbl.configure(text="PAUSED", text_color="#e74c3c")
            stud_upcoming = []
        elif stud_queue:
            self.tv_stud_serving_lbl.configure(text=f"S-{stud_queue[0]['id']:03d}", text_color="#2ecc71")
            stud_upcoming = stud_queue[1:5]
            if flash_type == "Student":
                self.flash_serving_label(self.tv_stud_serving_lbl, "#2ecc71")
        else:
            self.tv_stud_serving_lbl.configure(text="S---", text_color="#2ecc71")
            stud_upcoming = []

        for idx in range(4):
            if idx < len(stud_upcoming):
                self.stud_prep_badges[idx].configure(text=f"S-{stud_upcoming[idx]['id']:03d}", text_color="#2ecc71", fg_color="#273c75")
            else:
                self.stud_prep_badges[idx].configure(text="--", text_color="#7f8c8d", fg_color="#1e272e")

        if getattr(self.master, "parent_paused", False):
            self.tv_parent_serving_lbl.configure(text="PAUSED", text_color="#e74c3c")
            parent_upcoming = []
        elif parent_queue:
            self.tv_parent_serving_lbl.configure(text=f"G-{parent_queue[0]['id']:03d}", text_color="#e74c3c")
            parent_upcoming = parent_queue[1:5]
            if flash_type == "Parent":
                self.flash_serving_label(self.tv_parent_serving_lbl, "#e74c3c")
        else:
            self.tv_parent_serving_lbl.configure(text="G---", text_color="#e74c3c")
            parent_upcoming = []

        for idx in range(4):
            if idx < len(parent_upcoming):
                self.parent_prep_badges[idx].configure(text=f"G-{parent_upcoming[idx]['id']:03d}", text_color="#e67e22", fg_color="#273c75")
            else:
                self.parent_prep_badges[idx].configure(text="--", text_color="#7f8c8d", fg_color="#1e272e")

# ================================================================
# ⌨️ ENHANCED VIRTUAL KEYBOARD FRAME (WITH CAPS & CLEAR)
# ================================================================
class EmbeddedVirtualKeyboard(ctk.CTkFrame):
    def __init__(self, master, target_entry, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.target_entry = target_entry
        self.is_caps = True
        self.keys_layout = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
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
                btn_width = 160 if key == "SPACE" else (70 if key in ["⌫", "CLEAR", "CAPS"] else 38)
                fg_col = "#c0392b" if key in ["⌫", "CLEAR"] else ("#2980b9" if key in ["SPACE", "CAPS"] else "#34495e")
                hover_col = "#e74c3c" if key in ["⌫", "CLEAR"] else ("#3498db" if key in ["SPACE", "CAPS"] else "#2c3e50")

                btn = ctk.CTkButton(
                    row_frame, text=key, width=btn_width, height=46,
                    font=("Helvetica", 13, "bold"), fg_color=fg_col, hover_color=hover_col,
                    command=lambda k=key: self.on_key_press(k)
                )
                btn.pack(side="left", padx=2, expand=True)
                self.button_widgets[key] = btn

    def on_key_press(self, key):
        if key == "⌫":
            current_text = self.target_entry.get()
            self.target_entry.delete(0, 'end')
            self.target_entry.insert(0, current_text[:-1])
        elif key == "CLEAR":
            self.target_entry.delete(0, 'end')
        elif key == "CAPS":
            self.is_caps = not self.is_caps
            for k_text, btn_widget in self.button_widgets.items():
                if len(k_text) == 1 and k_text.isalpha():
                    new_text = k_text.upper() if self.is_caps else k_text.lower()
                    btn_widget.configure(text=new_text)
        elif key == "SPACE":
            self.target_entry.insert('end', ' ')
        else:
            char_to_add = key.upper() if self.is_caps else key.lower()
            self.target_entry.insert('end', char_to_add)

# ================================================================
# 🎫 TOUCH-OPTIMIZED COMBINED KIOSK TERMINAL WINDOW
# ================================================================
class CombinedKioskWindow(ctk.CTkToplevel):
    def __init__(self, master_app):
        super().__init__(master_app)
        self.master_app = master_app
        self.title("Kiosk Ticketing Terminal")
        
        # Open maximized on touchscreen monitor
        self.geometry("1100x700+0+0")
        self.after(100, lambda: self.state('zoomed'))
        
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # STUDENT PANEL
        self.student_panel = ctk.CTkFrame(self, corner_radius=18)
        self.student_panel.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        
        ctk.CTkLabel(self.student_panel, text="🎓 Student Kiosk Terminal", font=("Helvetica", 22, "bold")).pack(pady=(15, 5))
        
        self.stud_num_entry = ctk.CTkEntry(
            self.student_panel, placeholder_text="Enter ID Number or Name", 
            width=380, height=45, font=("Helvetica", 16)
        )
        self.stud_num_entry.pack(pady=5)
        
        EmbeddedVirtualKeyboard(self.student_panel, self.stud_num_entry).pack(pady=5, padx=5, fill="x")
        
        ctk.CTkLabel(self.student_panel, text="Select Purpose:", font=("Helvetica", 15, "bold")).pack(pady=(10, 2))
        self.stud_purpose_var = ctk.StringVar(value="Tuition")
        ctk.CTkOptionMenu(
            self.student_panel, variable=self.stud_purpose_var, 
            values=["Tuition", "Books", "Documents", "Other"], 
            width=280, height=40, font=("Helvetica", 15)
        ).pack(pady=2)
        
        ctk.CTkButton(
            self.student_panel, text="🎟️ Get Student Ticket", 
            font=("Helvetica", 16, "bold"), command=self.generate_student_ticket, 
            fg_color="#2ecc71", hover_color="#27ae60", height=50, width=280
        ).pack(pady=15)

        # PARENT PANEL
        self.parent_panel = ctk.CTkFrame(self, corner_radius=18)
        self.parent_panel.grid(row=0, column=1, padx=15, pady=15, sticky="nsew")
        
        ctk.CTkLabel(self.parent_panel, text="👨‍👩‍👧 Parents Kiosk Terminal", font=("Helvetica", 22, "bold")).pack(pady=(15, 5))
        
        self.parent_num_entry = ctk.CTkEntry(
            self.parent_panel, placeholder_text="Enter Parent / Guardian Name", 
            width=380, height=45, font=("Helvetica", 16)
        )
        self.parent_num_entry.pack(pady=5)
        
        EmbeddedVirtualKeyboard(self.parent_panel, self.parent_num_entry).pack(pady=5, padx=5, fill="x")
        
        ctk.CTkLabel(self.parent_panel, text="Select Purpose:", font=("Helvetica", 15, "bold")).pack(pady=(10, 2))
        self.parent_purpose_var = ctk.StringVar(value="Tuition")
        ctk.CTkOptionMenu(
            self.parent_panel, variable=self.parent_purpose_var, 
            values=["Tuition", "Books", "Documents", "Other"], 
            width=280, height=40, font=("Helvetica", 15)
        ).pack(pady=2)
        
        ctk.CTkButton(
            self.parent_panel, text="🎟️ Get Parent Ticket", 
            font=("Helvetica", 16, "bold"), command=self.generate_parent_ticket, 
            fg_color="#2ecc71", hover_color="#27ae60", height=50, width=280
        ).pack(pady=15)

    def show_toast_popup(self, ticket_code):
        toast = ctk.CTkToplevel(self)
        toast.title("Ticket Issued")
        toast.geometry("320x160")
        toast.attributes("-topmost", True)
        toast.configure(fg_color="#2c3e50")
        
        ctk.CTkLabel(toast, text="✅ Ticket Issued!", font=("Helvetica", 18, "bold"), text_color="#2ecc71").pack(pady=(20, 5))
        ctk.CTkLabel(toast, text=f"Your Ticket Number:\n{ticket_code}", font=("Helvetica", 20, "bold"), text_color="#ffffff").pack(pady=5)
        
        toast.after(2000, toast.destroy)

    def generate_student_ticket(self):
        student_input = self.stud_num_entry.get().strip() or "Walk-In Student"
        purpose = self.stud_purpose_var.get()
        ticket_num = db.student_ticket_counter
        db.student_ticket_counter += 1
        
        ticket_data = {"id": ticket_num, "student": f"[Student] {student_input}", "purpose": purpose}
        
        active_stud_queue = [t for t in db.paying_queue if "[Parent]" not in t['student']]
        if len(active_stud_queue) < 3:
            db.paying_queue.append(ticket_data)
            db.log_to_excel(ticket_num, student_input, purpose, "Queued for Payment (Student)", is_parent=False)
        else:
            db.preparation_queue.append(ticket_data)
            db.log_to_excel(ticket_num, student_input, purpose, "In Preparation Pool (Student)", is_parent=False)
            
        print_thermal_receipt("S", ticket_num, student_input, purpose)
        self.show_toast_popup(f"S-{ticket_num:03d}")
        self.stud_num_entry.delete(0, 'end')
        self.master_app.update_ui_displays()

    def generate_parent_ticket(self):
        parent_input = self.parent_num_entry.get().strip() or "Walk-In Parent"
        purpose = self.parent_purpose_var.get()
        ticket_num = db.parent_ticket_counter
        db.parent_ticket_counter += 1
        
        ticket_data = {"id": ticket_num, "student": f"[Parent] {parent_input}", "purpose": purpose}
        
        active_parent_queue = [t for t in db.paying_queue if "[Parent]" in t['student']]
        if len(active_parent_queue) < 3:
            db.paying_queue.append(ticket_data)
            db.log_to_excel(ticket_num, parent_input, purpose, "Queued for Payment (Parent)", is_parent=True)
        else:
            db.preparation_queue.append(ticket_data)
            db.log_to_excel(ticket_num, parent_input, purpose, "In Preparation Pool (Parent)", is_parent=True)
            
        print_thermal_receipt("G", ticket_num, parent_input, purpose)
        self.show_toast_popup(f"G-{ticket_num:03d}")
        self.parent_num_entry.delete(0, 'end')
        self.master_app.update_ui_displays()

# ================================================================
# 💼 CASHIER OPERATION DESK MAIN APP
# ================================================================
class CashierDeskApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Cashier Operation Desk")
        self.geometry("860x640+50+50")
        
        db.init_db()
        self.last_completed_student = None
        self.last_completed_parent = None
        
        self.student_paused = False
        self.parent_paused = False
        
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # STUDENT CASHIER DESK
        self.student_cashier_panel = ctk.CTkFrame(self, corner_radius=15)
        self.student_cashier_panel.grid(row=0, column=0, padx=15, pady=20, sticky="nsew")
        
        ctk.CTkLabel(self.student_cashier_panel, text="💼 Student Cashier Desk", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        self.stud_badge_lbl = ctk.CTkLabel(self.student_cashier_panel, text="Waiting in Line: 0", font=("Helvetica", 13, "bold"), text_color="#f1c40f")
        self.stud_badge_lbl.pack(pady=2)

        self.student_handling_lbl = ctk.CTkLabel(self.student_cashier_panel, text="No Student Active\nReady for next call.", font=("Helvetica", 14), text_color="#3498db")
        self.student_handling_lbl.pack(pady=15)
        
        ctk.CTkButton(self.student_cashier_panel, text="📢 Call Current Ticket", command=lambda: self.call_ticket("Student"), fg_color="#3498db", hover_color="#2980b9").pack(pady=5, padx=30, fill="x")
        ctk.CTkButton(self.student_cashier_panel, text="⏭️ Next Ticket", command=lambda: self.next_ticket("Student"), fg_color="#e67e22", hover_color="#d35400").pack(pady=5, padx=30, fill="x")
        ctk.CTkButton(self.student_cashier_panel, text="🔄 Recall Last Ticket", command=lambda: self.recall_ticket("Student"), fg_color="#2c3e50", hover_color="#1a252f").pack(pady=5, padx=30, fill="x")
        
        self.btn_pause_student = ctk.CTkButton(self.student_cashier_panel, text="⏸️ Pause Desk", command=lambda: self.toggle_pause("Student"), fg_color="#d35400", hover_color="#e67e22")
        self.btn_pause_student.pack(pady=5, padx=30, fill="x")
        
        ctk.CTkButton(self.student_cashier_panel, text="📊 Open Queue Database", command=self.open_database_view, fg_color="#9b59b6", hover_color="#8e44ad").pack(pady=15, padx=30, fill="x")

        # PARENTS CASHIER DESK
        self.parent_cashier_panel = ctk.CTkFrame(self, corner_radius=15)
        self.parent_cashier_panel.grid(row=0, column=1, padx=15, pady=20, sticky="nsew")
        
        ctk.CTkLabel(self.parent_cashier_panel, text="💼 Parents Cashier Desk", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        self.parent_badge_lbl = ctk.CTkLabel(self.parent_cashier_panel, text="Waiting in Line: 0", font=("Helvetica", 13, "bold"), text_color="#f1c40f")
        self.parent_badge_lbl.pack(pady=2)

        self.parent_handling_lbl = ctk.CTkLabel(self.parent_cashier_panel, text="No Parent Active\nReady for next call.", font=("Helvetica", 14), text_color="#3498db")
        self.parent_handling_lbl.pack(pady=15)
        
        ctk.CTkButton(self.parent_cashier_panel, text="📢 Call Current Ticket", command=lambda: self.call_ticket("Parent"), fg_color="#3498db", hover_color="#2980b9").pack(pady=5, padx=30, fill="x")
        ctk.CTkButton(self.parent_cashier_panel, text="⏭️ Next Ticket", command=lambda: self.next_ticket("Parent"), fg_color="#e67e22", hover_color="#d35400").pack(pady=5, padx=30, fill="x")
        ctk.CTkButton(self.parent_cashier_panel, text="🔄 Recall Last Ticket", command=lambda: self.recall_ticket("Parent"), fg_color="#2c3e50", hover_color="#1a252f").pack(pady=5, padx=30, fill="x")
        
        self.btn_pause_parent = ctk.CTkButton(self.parent_cashier_panel, text="⏸️ Pause Desk", command=lambda: self.toggle_pause("Parent"), fg_color="#d35400", hover_color="#e67e22")
        self.btn_pause_parent.pack(pady=5, padx=30, fill="x")
        
        ctk.CTkButton(self.parent_cashier_panel, text="📊 Open Queue Database", command=self.open_database_view, fg_color="#9b59b6", hover_color="#8e44ad").pack(pady=15, padx=30, fill="x")

        self.tv_window = PublicTVMonitor(self)
        self.kiosk_window = CombinedKioskWindow(self)
        self.update_ui_displays()

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
            self.student_handling_lbl.configure(text=f"Active Queue: S-{stud_ticket['id']:03d}\nID/Name: {stud_ticket['student']}\nPurpose: {stud_ticket['purpose']}", text_color="#3498db")
        else:
            self.student_handling_lbl.configure(text="No Student Active\nReady for next call.", text_color="#3498db")

        if self.parent_paused:
            self.parent_handling_lbl.configure(text="⛔ DESK PAUSED\nCounter closed temporarily.", text_color="#e74c3c")
        elif parent_ticket:
            self.parent_handling_lbl.configure(text=f"Active Queue: G-{parent_ticket['id']:03d}\nID/Name: {parent_ticket['student']}\nPurpose: {parent_ticket['purpose']}", text_color="#3498db")
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
            db.log_to_excel(current['id'], current['student'], current['purpose'], f"{queue_type} Payment Completed", is_parent=is_parent_type)
            
            if queue_type == "Student":
                self.last_completed_student = current
            else:
                self.last_completed_parent = current
            
            for prep in list(db.preparation_queue):
                is_parent = "[Parent]" in prep['student']
                if (queue_type == "Parent" and is_parent) or (queue_type == "Student" and not is_parent):
                    db.preparation_queue.remove(prep)
                    db.paying_queue.append(prep)
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

    def recall_ticket(self, queue_type):
        is_paused = self.student_paused if queue_type == "Student" else self.parent_paused
        if is_paused:
            messagebox.showwarning("Desk Paused", f"The {queue_type} Desk is currently paused.")
            return

        is_parent_type = (queue_type == "Parent")
        last_ticket = self.last_completed_student if queue_type == "Student" else self.last_completed_parent
        if last_ticket:
            db.paying_queue.insert(0, last_ticket)
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