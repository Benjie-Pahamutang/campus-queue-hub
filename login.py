import customtkinter as ctk
from tkinter import messagebox
import os

# Try importing Pillow safely so it never causes a crash if uninstalled
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

class LoginWindow(ctk.CTk):
    def __init__(self, on_success_bridge):
        super().__init__()
        self.on_success_bridge = on_success_bridge
        
        self.title("System Authentication")
        
        # ================================================================
        # 🎯 PERFECT SCREEN CENTERING LOGIC
        # ================================================================
        window_width = 400
        window_height = 350
        
        # Get your monitor's exact width and height
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        # Calculate coordinate points to center the window completely
        center_x = int((screen_width / 2) - (window_width / 2))
        center_y = int((screen_height / 2) - (window_height / 2))
        
        # Set geometry with offsets to center it on startup
        self.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Center UI Elements Frame
        self.frame = ctk.CTkFrame(self, corner_radius=15)
        self.frame.pack(pady=40, padx=40, fill="both", expand=True)
        
        self.label = ctk.CTkLabel(self.frame, text="Cashier Portal", font=("Helvetica", 24, "bold"))
        self.label.pack(pady=20)
        
        self.username_entry = ctk.CTkEntry(self.frame, placeholder_text="Username", width=200)
        self.username_entry.pack(pady=10)
        
        self.password_entry = ctk.CTkEntry(self.frame, placeholder_text="Password", show="*", width=200)
        self.password_entry.pack(pady=10)
        
        self.login_btn = ctk.CTkButton(self.frame, text="Login", command=self.validate_login, width=200, corner_radius=8)
        self.login_btn.pack(pady=20)
        
        # ================================================================
        # 🎯 DYNAMIC RESPONSIVE LOGO AREA
        # ================================================================
        self.load_safe_logo()
        
        # Bind the window resize event (<Configure>) to scale the logo dynamically
        self.bind("<Configure>", self.resize_logo)

    def load_safe_logo(self):
        # We start with a base size of 45x45 pixels for standard window mode
        self.base_logo_size = 45
        
        if HAS_PILLOW and os.path.exists("logo.png"):
            try:
                self.logo_image_source = Image.open("logo.png")
                self.logo_img_tk = ctk.CTkImage(
                    light_image=self.logo_image_source,
                    dark_image=self.logo_image_source,
                    size=(self.base_logo_size, self.base_logo_size)
                )
                self.logo_label = ctk.CTkLabel(self, image=self.logo_img_tk, text="")
            except Exception:
                self.logo_label = ctk.CTkLabel(self, text="🏫 CQH", font=("Helvetica", 14, "bold"), text_color="#f5cd79")
        else:
            self.logo_label = ctk.CTkLabel(self, text="🏫 CQH", font=("Helvetica", 14, "bold"), text_color="#f5cd79")
            
        self.logo_label.place(relx=1.0, rely=0.0, anchor="ne", x=-15, y=10)

    def resize_logo(self, event=None):
        """Monitors window size and scales the logo larger if the user goes full screen."""
        try:
            # SAFETY CHECK: If the window is closing or doesn't exist, exit immediately
            if not self.winfo_exists():
                return
                
            # Check if window is currently maximized/fullscreen
            is_maximized = self.state() == "zoomed" or self.attributes("-fullscreen")
            
            # If full screen, bump size to 75x75, otherwise keep it at 45x45
            new_size = 75 if is_maximized else 45
            
            # Update text size or image size depending on what is being displayed
            if hasattr(self, 'logo_img_tk') and HAS_PILLOW:
                self.logo_img_tk.configure(size=(new_size, new_size))
            else:
                new_font_size = 24 if is_maximized else 14
                self.logo_label.configure(font=("Helvetica", new_font_size, "bold"))
        except Exception:
            # Fail silently during destruction transitions
            pass

    def validate_login(self):
        if self.username_entry.get() == "tcc" and self.password_entry.get() == "tcc123":
            # Safely unbind events and withdraw before destroying to prevent animation callback errors
            self.unbind("<Configure>")
            self.withdraw()
            self.destroy() 
            self.on_success_bridge() 
        else:
            messagebox.showerror("Error", "Invalid username or password.")

if __name__ == "__main__":
    app = LoginWindow(on_success_bridge=lambda: print("Success! Opening main system..."))
    app.mainloop()