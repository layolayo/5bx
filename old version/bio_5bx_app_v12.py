import tkinter as tk
from tkinter import ttk, messagebox
import time
import json
import sqlite3
import os
import glob
import threading
import datetime
import subprocess
import platform
import sys
import csv
import statistics
import shutil
from PIL import Image, ImageTk

# Match v3 imports for graphing
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
import numpy as np

from ant_driver import AntHrvSensor
from ant_user_profile import UserProfile
import five_bx_data as bx

USER_DB_FILE = "user_progress.db"
PROFILE_DIR = "ant_user_profiles"
SESSION_DIR = "ant_sessions"
IMG_DIR = "images"
BACKUP_DIR = "ant_user_profiles/backups"
CALIBRATION_EXPIRY_DAYS = 30
PHASE_DURATIONS = {
    "REST": 60,
    "STRESS": 60,
    "EXERTION": 45,
    "RECOVERY": 60
}

class SessionLogger:
    def __init__(self, user_name):
        self.user_name = user_name
        self.filename = None
        self.file = None
        self.writer = None
        if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

    def start(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join([c for c in self.user_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        self.filename = os.path.join(SESSION_DIR, f"session_5bx_{safe_name}_{ts}.csv")
        self.file = open(self.filename, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer = csv.writer(self.file)
        self.writer.writerow(["Timestamp", "HR_BPM", "RMSSD_MS", "Raw_RR_MS", "Raw_Packet_Hex", "Chart_Level", "Exercise_Note", "Status", "Battery_V"])

    def log(self, hr, rmssd, raw_rr, raw_hex, state, trend, status, bat):
        if self.writer:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.writer.writerow([ts, hr, rmssd, raw_rr, raw_hex, state, trend, status, bat])
            self.file.flush()

    def stop(self):
        if self.file: self.file.close()

class Bio5BXApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bio-Adaptive 5BX Trainer v11")
        self.geometry("1000x950")
        self.configure(bg="#2c3e50")
        self.attributes('-fullscreen', True) # Enable Fullscreen
        self.bind("<Escape>", self.quit_app) # Exit on Esc

        self.user_id = None
        self.username = None
        self.user_data = {}
        self.profile_data = {}
        self.calculated_age = 30
        self.true_max_hr = 180
        self.session_metrics = []
        self.logger = None
        self.dashboard_active = False
        self.dashboard_active = False
        self.linker_active = False # New flag for first screen
        self.cardio_mode_var = tk.StringVar(value="Standard (Stationary)")
        self.current_cardio_mode = None # Reset to None for dynamic selection
        
        self.last_reconnect_attempt = 0 # Auto-Reconnect Cooldown
        self.is_reconnecting = False # Flag to prevent concurrent reconnection loops
        self.retry_task = None # Handle for pending scheduled retries
        self.retry_task = None # Handle for pending scheduled retries
        self.reset_task = None # Handle for manual reset delay
        self.sensor = None # Initialize sensor attribute

        self.init_sensor()

        self.current_exercise_idx = 0
        self.workout_active = False
        self.timer_running = False
        self.reps_achieved = []
        self.target_reps_list = []
        self.temp_reps_buffer = None
        
        self.last_reconnect_attempt = 0 # Auto-Reconnect Cooldown
        self.is_reconnecting = False # Flag to prevent concurrent reconnection loops

        self._init_db()
        self.show_profile_linker()

    def init_sensor(self, attempt=1, max_attempts=10):
        # Prevent concurrent reconnection attempts (Strict Lock)
        if attempt == 1 and self.is_reconnecting:
             print("Sensor Init: already in progress, skipping request.")
             return

        self.is_reconnecting = True
        
        try:
            # UI STEP 3: Initialising (Only on first attempt to avoid flicker)
            if attempt == 1:
                try:
                    msg = "📡 Initialising ANT+ HRM Sensor..."
                    if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                        self.lbl_device_status.config(text=msg, foreground="#f1c40f")
                    if hasattr(self, 'lbl_device_dash') and self.lbl_device_dash.winfo_exists():
                        self.lbl_device_dash.config(text=msg, foreground="#f1c40f")
                    self.update()
                except: pass

            # CRITICAL: Prevent Zombie Sensors
            # If we are about to create a new sensor, we MUST ensure the old one is dead
            # and not holding the USB handle.
            if self.sensor:
                try: 
                    self.sensor.stop()
                except: pass
                self.sensor = None

            self.sensor = AntHrvSensor()
            self.sensor.start()
            print(f"Sensor Initialized Successfully! (Attempt {attempt})")
            
            # UI STEP 4: Secured
            try:
                msg = "📡 Connection Secured"
                if hasattr(self, 'lbl_device_dash') and self.lbl_device_dash.winfo_exists():
                     self.lbl_device_dash.config(text=f"{msg} - Active", foreground="#2ecc71")
                if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                     self.lbl_device_status.config(text=msg, foreground="#2ecc71")
            except: pass
            
            # Reconnection successful - release flag and clear task
            self.is_reconnecting = False
            self.retry_task = None
            return
            
        except Exception as e:
            # Cleanup failed instance immediately
            if self.sensor:
                 try: self.sensor.stop()
                 except: pass
                 self.sensor = None

            err_str = str(e).lower()
            # Check for "Resource busy" (Error 16)
            if ("busy" in err_str or "16" in err_str or "usb" in err_str) and attempt < max_attempts:
                print(f"Sensor Busy: Retrying ({attempt}/{max_attempts})...")
                # Schedule next attempt in 500ms WITHOUT blocking GUI
                self.retry_task = self.after(500, lambda: self.init_sensor(attempt + 1, max_attempts))
            else:
                print(f"Sensor Error: {e}")
                self.sensor = None
                self.is_reconnecting = False # Give up and release flag
                self.retry_task = None

    def play_beep(self):
        system_os = platform.system()
        if system_os == "Windows":
            try:
                import winsound
                winsound.Beep(1000, 700)
            except: self.bell()
        elif system_os == "Darwin": self.bell()
        else:
            self.bell()
            # Removed spd-say "done" as per user request
            # try: os.system('spd-say "done" &')
            # except: pass

    def calculate_age(self, dob_str):
        # dob_str might be YYYY-MM-DD or None
        # If None/Empty, fall back to self.user_data['age']
        try:
            born = datetime.datetime.strptime(dob_str, "%Y-%m-%d")
            today = datetime.datetime.today()
            return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except:
            # Fallback to stored integer age or default
            return self.user_data.get('age', 30)

    def _init_db(self):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                         id INTEGER PRIMARY KEY AUTOINCREMENT,
                         name TEXT UNIQUE,
                         age INTEGER,
                         linked_file TEXT,
                         current_chart TEXT,
                         current_level TEXT,
                         goal_chart TEXT,
                         goal_level TEXT,
                         dob TEXT
                         )''')
            c.execute('''CREATE TABLE IF NOT EXISTS history (
                         id INTEGER PRIMARY KEY AUTOINCREMENT,
                         user_id INTEGER,
                         timestamp TEXT,
                         chart TEXT,
                         level TEXT,
                         verdict TEXT,
                         avg_hr INTEGER,
                         max_hr INTEGER,
                         end_rmssd INTEGER,
                         ex1 INTEGER,
                         ex2 INTEGER,
                         ex3 INTEGER,
                         ex4 INTEGER,
                         ex5 INTEGER,
                         segment_stats TEXT,
                         FOREIGN KEY(user_id) REFERENCES users(id)
                         )''')
                         
            # --- MIGRATION: Check if ex1..ex5 and segment_stats exist ---
            c.execute("PRAGMA table_info(history)")
            cols = [info[1] for info in c.fetchall()]
            
            if "ex1" not in cols:
                print("Migrating DB: Adding rep columns to history...")
                for i in range(1, 6):
                    try: c.execute(f"ALTER TABLE history ADD COLUMN ex{i} INTEGER DEFAULT 0")
                    except: pass
            
            if "segment_stats" not in cols:
                print("Migrating DB: Adding segment stats to history...")
                try: c.execute("ALTER TABLE history ADD COLUMN segment_stats TEXT")
                except: pass
            
            # --- MIGRATION: Check for DOB in users ---
            c.execute("PRAGMA table_info(users)")
            u_cols = [info[1] for info in c.fetchall()]
            if "dob" not in u_cols:
                print("Migrating DB: Adding DOB to users...")
                try: c.execute("ALTER TABLE users ADD COLUMN dob TEXT")
                except: pass
            
            # --- MIGRATION V9: Split Strength/Cardio ---
            if "strength_chart" not in u_cols:
                 print("Migrating DB: Adding Split Levels to users...")
                 try: 
                     c.execute("ALTER TABLE users ADD COLUMN strength_chart TEXT DEFAULT '1'")
                     c.execute("ALTER TABLE users ADD COLUMN strength_level TEXT DEFAULT '1'")
                     c.execute("ALTER TABLE users ADD COLUMN cardio_chart TEXT DEFAULT '1'")
                     c.execute("ALTER TABLE users ADD COLUMN cardio_level TEXT DEFAULT '1'")
                 except: pass

            # --- MIGRATION V9.1: Fix Legacy History Chart IDs ("3" -> "3/3") ---
            # This ensures old data works with new split logic
            try:
                # Update chart to chart/chart where it doesn't contain '/'  
                # We limit by length to avoid messing up anything weird, though checking for / is safest
                c.execute("UPDATE history SET chart = chart || '/' || chart WHERE chart NOT LIKE '%/%'")
            except Exception as e:
                print("Migration V9.1 Error:", e)

            # --- MIGRATION V11: Add Notes Column ---
            if "notes" not in cols:
                print("Migrating DB: Adding Notes to history...")
                try: c.execute("ALTER TABLE history ADD COLUMN notes TEXT")
                except: pass

            conn.commit()
            conn.close()
        except Exception as e:
            print("DB Init Error:", e)

    def db_get_user(self, name):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE name=?", (name,))
            row = c.fetchone()
            conn.close()
            return dict(row) if row else None
        except: return None

    def db_get_all_users(self):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            c.execute("SELECT name FROM users ORDER BY name ASC")
            rows = c.fetchall()
            conn.close()
            return [r[0] for r in rows]
        except: return []

    def db_create_user(self, name, age, linked_file, cur_c, cur_l, goal_c, goal_l, dob=None):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            # Initialize all columns (Legacy + New Split)
            # Default split levels to same as start (cur_c/cur_l)
            c.execute("""INSERT OR IGNORE INTO users 
                      (name, age, linked_file, dob, 
                       current_chart, current_level, goal_chart, goal_level,
                       strength_chart, strength_level, cardio_chart, cardio_level) 
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                      (name, age, linked_file, dob, 
                       cur_c, cur_l, goal_c, goal_l, 
                       cur_c, cur_l, cur_c, cur_l))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Create User Error: {e}")
            return False

    def db_delete_user(self, name):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            # Get ID first
            c.execute("SELECT id FROM users WHERE name=?", (name,))
            row = c.fetchone()
            if row:
                uid = row[0]
                # Delete History
                c.execute("DELETE FROM history WHERE user_id=?", (uid,))
                # Delete User
                c.execute("DELETE FROM users WHERE id=?", (uid,))
                conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Delete Error: {e}")
            return False

    def db_add_history(self, user_id, chart, level, verdict, avg_hr, max_hr, rmssd, reps_list=None, stats_json=None, ex5_type="standard", ex5_duration=0, notes=None):
        if reps_list is None: reps_list = [0,0,0,0,0]
        # Pad if short
        while len(reps_list) < 5: reps_list.append(0)
        
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("""INSERT INTO history (user_id, timestamp, chart, level, verdict, avg_hr, max_hr, end_rmssd, ex1, ex2, ex3, ex4, ex5, segment_stats, ex5_type, ex5_duration, notes)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (user_id, ts, chart, level, verdict, int(avg_hr), int(max_hr), int(rmssd), 
                      reps_list[0], reps_list[1], reps_list[2], reps_list[3], reps_list[4], stats_json, ex5_type, ex5_duration, notes))
        new_id = c.lastrowid
        conn.commit()
        conn.close()
        return new_id

    def db_update_notes(self, history_id, notes):
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE history SET notes=? WHERE id=?", (notes, history_id))
        conn.commit()
        conn.close()

    def db_delete_history(self, history_id):
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM history WHERE id=?", (history_id,))
        conn.commit()
        conn.close()

    def db_get_history(self, user_id):
        conn = sqlite3.connect(USER_DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC", (user_id,))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def db_update_level(self, user_id, chart, level):
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET current_chart=?, current_level=? WHERE id=?", (chart, level, user_id))
        conn.commit()
        conn.close()

    def db_update_split_level(self, user_id, s_c, s_l, c_c, c_l):
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET strength_chart=?, strength_level=?, cardio_chart=?, cardio_level=? WHERE id=?", 
                 (s_c, s_l, c_c, c_l, user_id))
        conn.commit()
        conn.close()
        
        # Sync Memory (Unconditional if active)
        if hasattr(self, 'user_data') and self.user_data:
            # Just update if exists, ignoring ID check to be robust against type mismatches
            self.user_data['strength_chart'] = str(s_c)
            self.user_data['strength_level'] = str(s_l)
            self.user_data['cardio_chart'] = str(c_c)
            self.user_data['cardio_level'] = str(c_l)
            
            # Legacy fields for combatability
            self.user_data['current_chart'] = str(s_c)
            self.user_data['current_level'] = str(s_l)

    # --- SCREEN 1: LINKER ---
    def show_profile_linker(self):
        self.dashboard_active = False
        self.linker_active = True # START LINKER LOOP
        self._clear()

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        # --- NEW: HARDWARE STATUS LABEL ON START SCREEN ---
        self.lbl_device_dash = ttk.Label(frame, text="📡 Searching for ANT+ Device...", foreground="#95a5a6", font=("Arial", 11))
        self.lbl_device_dash.pack(pady=5)
        # --------------------------------------------------

        ttk.Label(frame, text="Select User Profile", style="Header.TLabel", font=("Helvetica", 20, "bold")).pack(pady=10)

        profiles = glob.glob(os.path.join(PROFILE_DIR, "*_profile.json"))

        # BUTTON ROW (Split Across Screen)
        btn_frame = tk.Frame(frame, bg="#2c3e50")
        btn_frame.pack(fill=tk.X, pady=10)
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)
        btn_frame.columnconfigure(3, weight=1)
        btn_frame.columnconfigure(4, weight=1)

        # Load User
        self.btn_load = tk.Button(btn_frame, text="📂 Load User", bg="#2ecc71", font=("Arial", 10, "bold"), command=self.link_and_load)
        self.btn_load.grid(row=0, column=0, padx=5, sticky="ew")

        # New User
        tk.Button(btn_frame, text="➕ New User", bg="#3498db", fg="white", font=("Arial", 10, "bold"), 
                  command=self.create_new_user_popup).grid(row=0, column=1, padx=5, sticky="ew")
        
        # Delete User
        tk.Button(btn_frame, text="❌ Delete User", bg="#e74c3c", fg="white", font=("Arial", 10, "bold"), 
                  command=self.delete_selected_user).grid(row=0, column=2, padx=5, sticky="ew")

        # Run Calibration
        tk.Button(btn_frame, text="⚙️ Run Calibration", bg="#95a5a6", fg="black", font=("Arial", 10, "bold"), 
                  command=self.launch_calibration_app).grid(row=0, column=3, padx=5, sticky="ew")

        # Manual
        tk.Button(btn_frame, text="📘 Manual", bg="#2980b9", fg="white", font=("Arial", 10, "bold"), 
                  command=self.show_manual_popup).grid(row=0, column=4, padx=5, sticky="ew")

        # LISTBOX AREA (Container for List + Scrollbar)
        list_frame = tk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.lst_profiles = tk.Listbox(list_frame, height=8, font=("Arial", 14), yscrollcommand=scrollbar.set)
        self.lst_profiles.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.lst_profiles.yview)

        # Populate from DB
        user_list = self.db_get_all_users()
        for name in user_list:
            self.lst_profiles.insert(tk.END, name)

        # SELECTED INFO PANEL
        info_frame = tk.Frame(frame, bg="#34495e", pady=10)
        info_frame.pack(fill=tk.X, pady=5)
        
        self.lbl_sel_name = tk.Label(info_frame, text="Select a User...", font=("Arial", 12, "bold"), fg="#bdc3c7", bg="#34495e")
        self.lbl_sel_name.pack()
        
        self.lbl_sel_dob = tk.Label(info_frame, text="", font=("Arial", 10), fg="#95a5a6", bg="#34495e")
        self.lbl_sel_dob.pack()
        
        self.lbl_sel_cal_status = tk.Label(info_frame, text="", font=("Arial", 10), fg="#95a5a6", bg="#34495e")
        self.lbl_sel_cal_status.pack()

        # Quit Button
        tk.Button(frame, text="❌ Quit Application", command=self.quit_app, bg="#7f8c8d", fg="white", font=("Arial", 10)).pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        self.lst_profiles.bind('<<ListboxSelect>>', self.on_profile_select)

        # Start Live Update Loop
        self.update_status_loop()
        
    def delete_selected_user(self):
        selection = self.lst_profiles.curselection()
        if not selection:
            messagebox.showwarning("Select User", "Please select a user to delete.")
            return
            
        name = self.lst_profiles.get(selection[0])
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to PERMANENTLY delete user '{name}'?\n\nThis will remove their Profile and ALL Workout History."):
            return
            
        # 1. Delete from DB
        self.db_delete_user(name)
        
        # 2. Delete JSON Profile
        clean_name = name.lower().replace(" ", "_")
        prof_path = os.path.join(PROFILE_DIR, f"{clean_name}_profile.json")
        if os.path.exists(prof_path):
            try: os.remove(prof_path)
            except: pass
            
        messagebox.showinfo("Deleted", f"User {name} deleted.")
        self.show_profile_linker() # Refresh
        
    def create_new_user_popup(self):
        root = tk.Toplevel(self)
        root.title("Create New User")
        root.geometry("300x250")
        root.configure(bg="#34495e")
        
        tk.Label(root, text="Name:", bg="#34495e", fg="white").pack(pady=5)
        e_name = tk.Entry(root); e_name.pack()
        
        tk.Label(root, text="DOB (YYYY-MM-DD):", bg="#34495e", fg="white").pack(pady=5)
        e_dob = tk.Entry(root); e_dob.pack()
        
        def save():
            name = e_name.get().strip()
            dob_str = e_dob.get().strip()
            
            if not name or not dob_str: return
            
            # Validate DOB
            try:
                datetime.datetime.strptime(dob_str, "%Y-%m-%d")
            except:
                messagebox.showerror("Error", "Invalid DOB format. Use YYYY-MM-DD")
                return
            
            # Calculate Age for Legacy Column
            age = self.calculate_age(dob_str)
            
            # Prepare Profile Filename
            clean_name = name.lower().replace(" ", "_")
            linked_filename = f"{clean_name}_profile.json"
            
            # Create DB entry (Pass linked_filename)
            self.db_create_user(name, int(age), linked_filename, "1", "1", "6", "12", dob=dob_str)
            
            # Create Profile JSON
            prof_path = os.path.join(PROFILE_DIR, linked_filename)
            if not os.path.exists(prof_path):
                 with open(prof_path, 'w') as f:
                     json.dump({"name": name, "dob": dob_str, "age": int(age)}, f)
            
            messagebox.showinfo("Success", f"User {name} created!")
            root.destroy()
            self.show_profile_linker() # Refresh list
            
        tk.Button(root, text="Create", command=save, bg="#2ecc71").pack(pady=20)

    def launch_calibration_app(self):
        # 1. STOP SENSOR (Release Resource)
        if self.sensor:
            self.sensor.stop()
            time.sleep(1) # Give it a moment to release
            
        if hasattr(self, 'lbl_device_dash'):
            self.lbl_device_dash.config(text="📡 Status: Calibration Wizard Running...", foreground="#f39c12")
            
        # 2. PREPARE USER DATA
        user_data = None
        try:
            # CASE A: Already Logged In (Dashboard)
            if hasattr(self, 'username') and self.username and hasattr(self, 'profile_data') and self.profile_data:
                 user_data = {
                    "name": self.profile_data.get("name", self.username),
                    "dob": self.profile_data.get("dob"),
                    "age": self.profile_data.get("age", 30)
                 }
            
            # CASE B: Selecting from Linker (Not Logged In)
            elif hasattr(self, 'lst_profiles') and self.lst_profiles:
                selection = self.lst_profiles.curselection()
                if selection:
                    name = self.lst_profiles.get(selection[0])
                    
                    # Resolve File via DB
                    db_u = self.db_get_user(name)
                    filename = db_u['linked_file'] if (db_u and db_u.get('linked_file') and db_u['linked_file'] != 'none') else f"{name.lower().replace(' ', '_')}_profile.json"

                    prof_path = os.path.join(PROFILE_DIR, filename)
                    if os.path.exists(prof_path):
                        with open(prof_path, 'r') as f:
                            data = json.load(f)
                            if "dob" in data:
                                user_data = {
                                    "name": data.get("name", name),
                                    "dob": data.get("dob"),
                                    "age": data.get("age", 30)
                                }
        except Exception as e:
            print(f"Error fetching user for wizard: {e}")

        if not user_data:
            messagebox.showwarning("Selection Required", "Please select a user profile to run calibration.")
            # Ensure sensor is restarted if we stopped it
            if self.sensor and not self.sensor.running: self.init_sensor()
            return

        # 3. LAUNCH NATIVE WIZARD
        try: 
            CalibrationWizard(self, initial_user_data=user_data) 
        except Exception as e: 
            messagebox.showerror("Error", f"Could not launch wizard: {e}")
            self.finish_calibration_wizard()
            
    def finish_calibration_wizard(self):
        # Called by Wizard when it closes
        if hasattr(self, 'lbl_device_dash'):
            self.lbl_device_dash.config(text="📡 Status: Restarting Sensor...", foreground="#95a5a6")
        
        # Restart Sensor
        self.init_sensor()
        
        # Refresh profiles
        if self.linker_active:
            self.show_profile_linker()

    def on_profile_select(self, event):
        selection = self.lst_profiles.curselection()
        if not selection:
            self.lbl_sel_name.config(text="No User Selected", foreground="#f1c40f")
            self.lbl_sel_dob.config(text="")
            self.lbl_sel_cal_status.config(text="")
            self.btn_load.config(text="📂 Load User", bg="#2ecc71")
            return
        
        selected_text = self.lst_profiles.get(selection[0])
        
        # Resolve File via DB
        db_u = self.db_get_user(selected_text)
        clean_filename = db_u['linked_file'] if (db_u and db_u.get('linked_file') and db_u['linked_file'] != 'none') else (selected_text.lower().replace(" ", "_") + "_profile.json")

        full_path = os.path.join(PROFILE_DIR, clean_filename)
        
        self.profile_data = {} # Clear previous
        self.user_data = {} # Clear previous
        
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r') as f:
                    self.profile_data = json.load(f)
                    
                # Additional DB load for history/stats if needed
                self.user_data = self.db_get_user(selected_text) # Sync DB data to memory
                
                # Show details in right panel
                self.lbl_sel_name.config(text=self.profile_data.get("name", "Unknown"), foreground="#f1c40f")
                dob_str = self.profile_data.get("dob", "N/A")
                self.lbl_sel_dob.config(text=f"DOB: {dob_str}")

                # Check calibration date
                cal_date_str = self.profile_data.get("calibration_date")
                
                # Check Legacy Location
                if not cal_date_str:
                     stats = self.profile_data.get("current_stats", {})
                     cal_date_str = stats.get("date")

                if not cal_date_str:
                     self.btn_load.config(text="📂 Load User (Uncalibrated)", bg="#95a5a6")
                     self.lbl_sel_cal_status.config(text="⚠️ Not Calibrated", foreground="#e67e22")
                else:
                    try:
                        # Try parsing multiple formats
                        cal_date = None
                        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                            try:
                                cal_date = datetime.datetime.strptime(cal_date_str, fmt)
                                break
                            except ValueError: continue
                        
                        if cal_date:
                            days_since = (datetime.datetime.now() - cal_date).days
                            short_date = cal_date.strftime('%Y-%m-%d')
                            
                            if days_since > CALIBRATION_EXPIRY_DAYS:
                                self.btn_load.config(text=f"📂 LOAD (Recalibration Due)", bg="#f1c40f")
                                self.lbl_sel_cal_status.config(text=f"Calibration Expired ({days_since} days ago)", foreground="#e74c3c")
                            else:
                                self.btn_load.config(text="📂 Load User", bg="#2ecc71")
                                self.lbl_sel_cal_status.config(text=f"Last Calibrated: {short_date}", foreground="#2ecc71")
                        else:
                             self.lbl_sel_cal_status.config(text="Invalid Date format", foreground="red")
                    except Exception as ex:
                        print(f"Date check error: {ex}")
                        self.lbl_sel_cal_status.config(text="Error Checking Date", foreground="red")
            except Exception as e:
                print(f"Error loading profile details: {e}")
                self.lbl_sel_name.config(text="Error Loading Profile", foreground="red")
                self.lbl_sel_dob.config(text="")
                self.lbl_sel_cal_status.config(text="")
                self.btn_load.config(text="📂 Load User", bg="#2ecc71")
        else:
            self.lbl_sel_name.config(text="Profile File Missing", foreground="red")
            self.lbl_sel_dob.config(text="")
            self.lbl_sel_cal_status.config(text="")
            self.btn_load.config(text="📂 Load User", bg="#2ecc71")

    def link_and_load(self):
        self.linker_active = False # Stop linker loop
        selection = self.lst_profiles.curselection()
        if not selection:
            messagebox.showwarning("Select User", "Please select a user from the list.")
            return

        selected_text = self.lst_profiles.get(selection[0])
        
        # Resolve File via DB
        db_u = self.db_get_user(selected_text)
        clean_filename = db_u['linked_file'] if (db_u and db_u.get('linked_file') and db_u['linked_file'] != 'none') else f"{selected_text.lower().replace(' ', '_')}_profile.json"
        self.full_profile_path = os.path.join(PROFILE_DIR, clean_filename)

        try:
            with open(self.full_profile_path, 'r') as f: self.profile_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load profile data for {selected_text}: {e}")
            self.linker_active = True # Re-enable linker loop
            return

        raw_name = self.profile_data.get("name", selected_text)
        user_name = raw_name.title()
        if "dob" in self.profile_data:
            self.calculated_age = self.calculate_age(self.profile_data["dob"])
        else:
            self.calculated_age = self.profile_data.get("age", 30)

        if not self.db_get_user(user_name):
            goal_c, goal_l = bx.get_age_goal(self.calculated_age)
            self.db_create_user(user_name, self.calculated_age, clean_filename, "1", "1", goal_c, goal_l)

        self.load_user_session(user_name)

    def load_user_session(self, name):
        self.user_data = self.db_get_user(name)
        if not self.user_data: return
        self.user_id = self.user_data['id']
        self.username = name

        curr = self.profile_data.get('current_stats', {})
        self.bio_profile = UserProfile(name)
        self.bio_profile.baseline_rmssd = curr.get('baseline_rmssd', 40)
        profile_max = curr.get('max_hr', 180)
        age_max = 220 - self.calculated_age
        self.true_max_hr = max(profile_max, age_max)
        self.bio_profile.max_hr = self.true_max_hr

        self.show_dashboard()

    # --- SHARED STATUS LOOP (Used by Linker & Dashboard) ---
    def update_status_loop(self):
        # Runs if EITHER screen is active
        if not (self.dashboard_active or self.linker_active): return

        if self.sensor:
            data = self.sensor.get_data()
            manuf = data.get('manufacturer', 'Unknown')
            serial = data.get('serial')
            batt_v = data.get('battery_volts')
            batt_state = data.get('battery_state', 'Unknown')
            uptime = data.get('uptime_hours')
            bpm = data.get('bpm', 0)
            status = data.get('status', 'Initializing')

            if status == "Active" or bpm > 0:
                txt = f"📡 - ✅ {manuf} #{serial}" if serial else f"📡 - ❌ {manuf}"
                if batt_v: txt += f" | 🔋 {batt_v}V ({batt_state})"
                if uptime and uptime > 0: txt += f" | ⏱ {uptime}h"
                if bpm > 0: txt += f" | ♥ Live HR: {bpm}"

                if hasattr(self, 'lbl_device_dash'):
                    try: self.lbl_device_dash.config(text=txt, foreground="#2ecc71")
                    except: pass
            else:
                if hasattr(self, 'lbl_device_dash'):
                    try: self.lbl_device_dash.config(text=f"📡 {status}...", foreground="#95a5a6")
                    except: pass

        self.after(1000, self.update_status_loop)

    # --- SCREEN 2: DASHBOARD ---
    def show_dashboard(self):
        self._clear()
        self.linker_active = False
        self.dashboard_active = True

        self.user_data = self.db_get_user(self.username)
        # SPLIT LOADING
        s_chart = self.user_data.get("strength_chart") or self.user_data.get("current_chart") or "1"
        s_level = self.user_data.get("strength_level") or self.user_data.get("current_level") or "1"
        c_chart = self.user_data.get("cardio_chart") or self.user_data.get("current_chart") or "1"
        c_level = self.user_data.get("cardio_level") or self.user_data.get("current_level") or "1"
        
        s_disp = bx.get_level_display(s_level)
        c_disp = bx.get_level_display(c_level)
        
        # Get Targets
        s_targets = bx.get_targets(s_chart, s_level)
        c_targets = bx.get_targets(c_chart, c_level)
        
        # Combine: 1-4 from Strength, 5 from Cardio
        # Combine: 1-4 from Strength, 5 from Cardio
        # Targets is now potentially 7 items [ex1..ex5, run, walk]
        # But we previously sliced it: s_targets[:4] + [c_targets[4]]
        # ex5 (reps) is at index 4. Run at 5. Walk at 6.
        
        final_ex5_target = c_targets[4]
        if self.current_cardio_mode:
             if "Run" in self.current_cardio_mode:
                 final_ex5_target = c_targets[5] if len(c_targets) > 5 else 0
             elif "Walk" in self.current_cardio_mode:
                 final_ex5_target = c_targets[6] if len(c_targets) > 6 else 0
                 
        targets = s_targets[:4] + [final_ex5_target]

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        header_text = f"User: {self.username} (Age {self.calculated_age})"
        ttk.Label(frame, text=header_text, font=("Helvetica", 14, "bold")).pack(pady=10)
        
        split_frame = ttk.Frame(frame); split_frame.pack(fill=tk.X, pady=5)
        
        s_lbl = tk.Label(split_frame, text=f"💪 STRENGTH: Chart {s_chart} / Level {s_disp}", font=("Arial", 12, "bold"), fg="#f1c40f", bg="#34495e", padx=10, pady=5)
        s_lbl.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        c_lbl = tk.Label(split_frame, text=f"🏃 CARDIO: Chart {c_chart} / Level {c_disp}", font=("Arial", 12, "bold"), fg="#e74c3c", bg="#34495e", padx=10, pady=5)
        c_lbl.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        tk.Button(split_frame, text="⚙️ Edit", command=self.edit_user_progress, bg="#bdc3c7").pack(side=tk.RIGHT, padx=5)
        
        # self.view_chart_idx fallback if needed (used for badges etc)
        self.user_data["current_chart"] = s_chart # Weakest link or Strength? Use Strength as primary.

        # BIO STATS
        stats_frame = ttk.Frame(frame)
        stats_frame.pack(fill=tk.X, pady=5)
        curr = self.profile_data.get('current_stats', {})
        rhr = curr.get('resting_hr', '?')
        rmssd = curr.get('baseline_rmssd', '?')
        max_hr_source = "Profile" if self.bio_profile.max_hr == curr.get('max_hr', 0) else "Age-Predicted"

        lbl_stats = ttk.Label(stats_frame, text=f"❤️ RHR: {rhr} | ⚡ HRV: {rmssd}ms | 🎯 Max HR: {self.true_max_hr} ({max_hr_source})", foreground="#1abc9c", font=("Arial", 11))
        lbl_stats.pack(anchor="center")

        # DEVICE STATS
        hw_frame = ttk.Frame(frame)
        hw_frame.pack(fill=tk.X, pady=5)
        self.lbl_device_dash = ttk.Label(hw_frame, text="📡 Searching for ANT+ Device...", foreground="#95a5a6", font=("Arial", 10))
        self.lbl_device_dash.pack(anchor="center")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)
        tk.Button(btn_frame, text="View History Log", bg="#3498db", fg="white", font=("Arial", 10, "bold"), command=self.show_history_screen).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        tk.Button(btn_frame, text="📊 View Charts", bg="#9b59b6", fg="white", font=("Arial", 10, "bold"), command=self.open_chart_viewer).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        tk.Button(btn_frame, text="🏆 Badges", bg="#f1c40f", fg="black", font=("Arial", 10, "bold"), command=self.show_badges_screen).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        tk.Button(btn_frame, text="📘 Manual", bg="#2980b9", fg="white", font=("Arial", 10, "bold"), command=self.show_manual_popup).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        tk.Button(btn_frame, text="⚡ Calibrate", bg="#e67e22", fg="white", font=("Arial", 10, "bold"), command=self.launch_calibration_app).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # STRENGTH SECTION
        preview_s = ttk.LabelFrame(frame, text="Strength Exercises")
        preview_s.pack(fill=tk.BOTH, expand=True, pady=5)
        
        for i in range(4):
            # Strength 1-4
            target = s_targets[i]
            details = bx.get_exercise_detail(s_chart, i)
            row = ttk.Frame(preview_s)
            row.pack(fill=tk.X, padx=10, pady=5)
            
            txt = f"{i+1}. {details['name']}: {target} Reps"
            ttk.Label(row, text=txt, font=("Arial", 12)).pack(side=tk.LEFT)
            tk.Button(row, text="📈", font=("Arial", 10), 
                      command=lambda idx=i, name=details['name'], chart=s_chart: self.show_exercise_history(chart, idx, name)).pack(side=tk.RIGHT)

        # CARDIO SECTION
        preview_c = ttk.LabelFrame(frame, text="Cardio Options (Exercise 5)")
        preview_c.pack(fill=tk.BOTH, expand=True, pady=5)
        
        c_config = bx.get_cardio_config(c_chart)
        
        # Option 1: Stationary (Standard)
        # Idx 4
        details_c = bx.get_exercise_detail(c_chart, 4)
        t_stat = c_targets[4]
        row_c1 = ttk.Frame(preview_c)
        row_c1.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(row_c1, text=f"A. {details_c['name']}: {t_stat} Reps", font=("Arial", 12)).pack(side=tk.LEFT)
        tk.Button(row_c1, text="📈", font=("Arial", 10), 
                  command=lambda: self.show_exercise_history(c_chart, 4, details_c['name'])).pack(side=tk.RIGHT)
                  
        # Option 2: Run
        # Idx 5
        t_run = c_targets[5] if len(c_targets) > 5 else 0
        lbl_run = c_config['run']
        row_c2 = ttk.Frame(preview_c)
        row_c2.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(row_c2, text=f"B. {lbl_run}: {t_run // 60}:{t_run % 60:02d} (Time)", font=("Arial", 12)).pack(side=tk.LEFT)
        tk.Button(row_c2, text="📈", font=("Arial", 10), 
                  command=lambda: self.show_exercise_history(c_chart, 5, lbl_run)).pack(side=tk.RIGHT)
                  
        # Option 3: Walk
        lbl_walk = c_config['walk']
        if lbl_walk:
            t_walk = c_targets[6] if len(c_targets) > 6 else 0
            row_c3 = ttk.Frame(preview_c)
            row_c3.pack(fill=tk.X, padx=10, pady=5)
            ttk.Label(row_c3, text=f"C. {lbl_walk}: {t_walk // 60}:{t_walk % 60:02d} (Time)", font=("Arial", 12)).pack(side=tk.LEFT)
            tk.Button(row_c3, text="📈", font=("Arial", 10), 
                      command=lambda: self.show_exercise_history(c_chart, 6, lbl_walk)).pack(side=tk.RIGHT)

        btn = tk.Button(frame, text="START WORKOUT (Try Max Reps)", bg="#2ecc71", font=("Arial", 16, "bold"), command=self.start_workout)
        btn.pack(fill=tk.X, pady=20)
        
        # Switch Profile Button
        tk.Button(frame, text="🔄 Switch Profile", command=self.show_profile_linker, bg="#e67e22", fg="white", font=("Arial", 12)).pack(fill=tk.X, pady=10)

        ttk.Label(frame, text="Tip: Do as many reps as possible to Fast-Track!", font=("Arial", 10, "italic")).pack()

        # Resume loop for dashboard
        self.update_status_loop()

    def quit_app(self, event=None):
        if messagebox.askyesno("Quit", "Are you sure you want to exit?"):
            self.destroy()

    # --- SCREEN 2.5: HISTORY ---
    def show_history_screen(self):
        self.dashboard_active = False
        self._clear()
        
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ttk.Label(frame, text=f"History: {self.username}", style="Header.TLabel", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        cols = ("Date", "Level", "Verdict", "Reps", "HR Stats", "HRV")
        self.hist_tree = ttk.Treeview(frame, columns=cols, show='headings', height=15)
        
        self.hist_tree.heading("Date", text="Date")
        self.hist_tree.heading("Level", text="Chart-Level")
        self.hist_tree.heading("Verdict", text="Result")
        self.hist_tree.heading("Reps", text="Reps (1-5)")
        self.hist_tree.heading("HR Stats", text="Avg / Max HR")
        self.hist_tree.heading("HRV", text="End HRV")
        
        self.hist_tree.column("Date", width=150)
        self.hist_tree.column("Level", width=90)
        self.hist_tree.column("Verdict", width=450)
        self.hist_tree.column("Reps", width=140)
        self.hist_tree.column("HR Stats", width=110)
        self.hist_tree.column("HRV", width=70)
        
        self.hist_tree.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.hist_tree.yview)
        self.hist_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        records = self.db_get_history(self.user_id)
        for r in records:
            # Format Level: "Chart Grade" (e.g. 1 D- / 2 C+)
            c_raw = str(r['chart'])
            l_raw = str(r['level'])
            
            s_c, c_c = c_raw, c_raw
            s_l, c_l = l_raw, l_raw
            
            if "/" in c_raw:
                parts = c_raw.split("/")
                s_c = parts[0]
                c_c = parts[1] if len(parts)>1 else parts[0]
            
            if "/" in l_raw:
                parts = l_raw.split("/")
                s_l = parts[0]
                c_l = parts[1] if len(parts)>1 else parts[0]
                
            s_disp = bx.get_level_display(s_l)
            c_disp = bx.get_level_display(c_l)
            
            full_level = f"{s_c} {s_disp}"
            # Show split if Charts differ OR Levels differ
            if s_c != c_c or s_l != c_l:
                full_level = f"{s_c} {s_disp} / {c_c} {c_disp}"
            
            # Format Reps
            reps_str = ""
            if 'ex1' in r.keys() and r['ex1'] is not None:
                reps_str = f"{r['ex1']}-{r['ex2']}-{r['ex3']}-{r['ex4']}"
                
                # Ex 5 Special Handling
                ex5_type = r.get('ex5_type', 'standard') 
                if ex5_type == 'standard' or not ex5_type or "Stationary" in ex5_type:
                    # Treat Stationary Run as standard reps-based
                    val = r['ex5']
                    if "Stationary" in ex5_type: val = f"{r['ex5']} (Stat.)"
                    reps_str += f"-{val}"
                else:
                    dur = r.get('ex5_duration', 0)
                    m = dur // 60
                    s = dur % 60
                    icon = "🏃" if "Run" in ex5_type else "🚶" 
                    reps_str += f" | {icon} {m}:{s:02d}"
            else:
                reps_str = "--"
            
            tag = "neutral"
            if "LEAPFROG" in r['verdict']: tag = "super"
            elif "LEVEL UP" in r['verdict']: tag = "good"
            elif "PROMOTION" in r['verdict']: tag = "good"
            elif "REPEAT" in r['verdict']: tag = "bad"
            elif "DROP" in r['verdict'] or "DEMOTION" in r['verdict']: tag = "drop"
            
            self.hist_tree.insert("", "end", iid=r['id'], values=(
                r['timestamp'],
                full_level,
                r['verdict'],
                reps_str,
                f"{r['avg_hr']} / {r['max_hr']}",
                f"{r['end_rmssd']} ms"
            ), tags=(tag,))
            
        self.hist_tree.tag_configure("super", foreground="purple")
        self.hist_tree.tag_configure("good", foreground="green")
        self.hist_tree.tag_configure("bad", foreground="#e67e22") 
        self.hist_tree.tag_configure("drop", foreground="red")
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=20)
        
        tk.Button(btn_frame, text="Back to Dashboard", command=self.show_dashboard).pack(side=tk.LEFT)
        tk.Button(btn_frame, text="View Details", bg="#3498db", fg="white", command=self.history_view_details).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Delete Selected (Undo)", bg="#c0392b", fg="white", command=self.delete_history_item).pack(side=tk.RIGHT)
    
    def show_badges_screen(self):
        root = tk.Toplevel(self)
        root.title("Trophy Room")
        
        # 2/3 Screen Size and Center
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w = int(sw * 0.66)
        h = int(sh * 0.66)
        x = (sw - w) // 2
        y = (sh - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")
        
        root.configure(bg="#2c3e50")
        
        tk.Label(root, text="🏆 EARNED BADGES 🏆", font=("Arial", 28, "bold"), fg="#f1c40f", bg="#2c3e50").pack(pady=20)
        
        # SPLIT LOADING v9
        s_chart = self.user_data.get("strength_chart") or self.user_data.get("current_chart") or "1"
        s_level = self.user_data.get("strength_level") or self.user_data.get("current_level") or "1"
        c_chart = self.user_data.get("cardio_chart") or self.user_data.get("current_chart") or "1"
        c_level = self.user_data.get("cardio_level") or self.user_data.get("current_level") or "1"
        
        age = self.calculate_age(self.user_data.get('dob', '2000-01-01'))
        badges = bx.get_earned_badges(s_chart, s_level, c_chart, c_level, age)
        
        # Scrollable Frame Logic
        main_frame = tk.Frame(root, bg="#2c3e50")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=10)
        
        canvas = tk.Canvas(main_frame, bg="#2c3e50", highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#2c3e50")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Resize scrollable frame to match canvas width
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Render Badges
        if not badges:
             tk.Label(scrollable_frame, text="No badges yet. Keep training!", font=("Arial", 16), fg="#bdc3c7", bg="#2c3e50").pack(pady=40)
        else:
            self.badge_images = [] # Keep refs
            for b_obj in badges:
                card = tk.Frame(scrollable_frame, bg="#34495e", pady=15, padx=20)
                card.pack(fill=tk.X, pady=8, padx=10)
                
                # Image/Icon Container (Left)
                icon_frame = tk.Frame(card, bg="#34495e", width=100)
                icon_frame.pack(side=tk.LEFT, padx=(0, 20))
                
                img_path = b_obj.get('image')
                if img_path:
                    try:
                        pil_img = Image.open(img_path)
                        pil_img.thumbnail((100, 100)) # Slightly larger
                        tk_img = ImageTk.PhotoImage(pil_img)
                        self.badge_images.append(tk_img)
                        tk.Label(icon_frame, image=tk_img, bg="#34495e").pack()
                    except:
                         tk.Label(icon_frame, text="🏅", font=("Arial", 40), bg="#34495e", fg="#f1c40f").pack()
                else:
                    icon = "🏅" if b_obj['type'] == "Standard" else "✈️"
                    color = "#f39c12" if b_obj['type'] == "Standard" else "#e74c3c"
                    tk.Label(icon_frame, text=icon, font=("Arial", 40), bg="#34495e", fg=color).pack()
                
                # Text Container (Right)
                text_frame = tk.Frame(card, bg="#34495e")
                text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                
                # Title
                tk.Label(text_frame, text=b_obj['title'], font=("Arial", 22, "bold"), bg="#34495e", fg="white", anchor="w").pack(fill=tk.X)
                
                # Details
                tk.Label(text_frame, text=b_obj['details'], font=("Arial", 16), bg="#34495e", fg="#3498db", anchor="w").pack(fill=tk.X, pady=(5,0))
                
                # STATUS (Split Achievement)
                status = b_obj.get('status', 'Achieved')
                s_color = "#f1c40f" if "FULLY" in status else "#95a5a6" # Gold if full, Gray if partial
                tk.Label(text_frame, text=status, font=("Arial", 14, "italic"), bg="#34495e", fg=s_color, anchor="w").pack(fill=tk.X, pady=(5,0))

        tk.Button(root, text="Close", font=("Arial", 14), command=root.destroy, bg="#e74c3c", fg="white").pack(pady=20)
    


    def open_chart_viewer(self):
        # Default to STRENGTH chart as primary
        try: self.view_chart_idx = int(self.user_data.get("strength_chart") or self.user_data.get("current_chart") or "1")
        except: self.view_chart_idx = 1
        
        self.chart_win = tk.Toplevel(self)
        self.chart_win.title("5BX Chart Viewer")
        self.chart_win.attributes('-fullscreen', True)
        self.chart_win.configure(bg="#2c3e50")
        self.chart_win.bind("<Escape>", lambda e: self.chart_win.destroy())
        
        # Navigation Frame
        nav_frame = tk.Frame(self.chart_win, bg="#34495e", height=60)
        nav_frame.pack(fill=tk.X, side=tk.TOP)
        
        tk.Button(nav_frame, text="Close", bg="#c0392b", fg="white", command=self.chart_win.destroy).pack(side=tk.RIGHT, padx=20, pady=10)
        
        tk.Button(nav_frame, text="◀ Prev Chart", command=lambda: self.change_chart_view(-1), font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=20, pady=10)
        self.lbl_chart_title = tk.Label(nav_frame, text=f"CHART {self.view_chart_idx}", font=("Helvetica", 20, "bold"), bg="#34495e", fg="white")
        self.lbl_chart_title.pack(side=tk.LEFT, padx=20, pady=10)
        tk.Button(nav_frame, text="Next Chart ▶", command=lambda: self.change_chart_view(1), font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=20, pady=10)

        # Content Frame
        self.chart_content = tk.Frame(self.chart_win, bg="#2c3e50")
        self.chart_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        
        # Graph Pane (Middle) - Increased Height
        self.graph_pane = tk.Frame(self.chart_win, bg="#34495e", height=300)
        self.graph_pane.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=5)

        # Info Pane (Bottom) - Increased Height Again
        self.info_pane = tk.Frame(self.chart_win, bg="#34495e", height=300)
        self.info_pane.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=5)
        
        self.render_chart_grid()
        
        # Auto-Select Exercise 1 (Default)
        self.selected_exercise_idx = 0
        self.show_exercise_info(self.selected_exercise_idx)

    def change_chart_view(self, delta):
        new_idx = self.view_chart_idx + delta
        if 1 <= new_idx <= 6:
            self.view_chart_idx = new_idx
            self.lbl_chart_title.config(text=f"CHART {self.view_chart_idx}")
            self.render_chart_grid()
            # Maintain selected exercise
            self.show_exercise_info(self.selected_exercise_idx)

    def render_chart_grid(self):
        for widget in self.chart_content.winfo_children(): widget.destroy()
        
        # Grid Headers
        exercises = []
        for i in range(5):
            # For Chart Viewer, we use "Standard" for headers usually?
            # Or if this chart has 1 Mile Run we could show its description if clicked?
            d = bx.get_exercise_detail(str(self.view_chart_idx), i)
            exercises.append(d['name'])
            
        is_chart1 = False # Legacy flag check no longer needed
        
        c_config = bx.get_cardio_config(str(self.view_chart_idx))
        exercises.append(c_config['run'])
        if c_config['walk']:
            exercises.append(c_config['walk'])

        # Headers
        tk.Label(self.chart_content, text="Lvl", bg="#2c3e50", fg="#bdc3c7", font=("Arial", 12, "bold")).grid(row=0, column=0, padx=5, pady=5)
        for i, name in enumerate(exercises):
            # Tint Cardio Headers (Ex 5, Run, Walk -> i >= 4)
            h_bg = "#2c3e50"
            if i >= 4: h_bg = "#6e2c2c" # Dark Reddish for header
            
            h_frame = tk.Frame(self.chart_content, bg=h_bg)
            h_frame.grid(row=0, column=i+1, padx=5, pady=5, sticky="ew")
            # All columns are buttons now
            # Button bg should maybe match or be distinct? Standard buttons are #3498db (Blue).
            # Let's start with standard blue but maybe reddish for cardio?
            btn_bg = "#3498db"
            if i >= 4: btn_bg = "#c0392b"
            
            tk.Button(h_frame, text=name, bg=btn_bg, fg="white", font=("Arial", 9, "bold"), 
                        command=lambda x=i: self.show_exercise_info(x)).pack(side=tk.TOP, fill=tk.X)

        # Data Rows
        conn = sqlite3.connect(bx.DB_NAME)
        c = conn.cursor()
        
        # We need extra columns if Chart 1
        sql = "SELECT level, ex1, ex2, ex3, ex4, ex5 FROM ExerciseTimes WHERE chart=? ORDER BY level DESC"
        # Always fetch extras now? Or conditionally? 
        # Let's simple fetch all 7. If DB doesn't have them for other charts, they will be 0.
        # But we need them to exist. We added them to table, so they exist for ALL rows (default 0).
        sql = "SELECT level, ex1, ex2, ex3, ex4, ex5, ex5_run, ex5_walk FROM ExerciseTimes WHERE chart=? ORDER BY level DESC"
             
        c.execute(sql, (str(self.view_chart_idx),))
        rows = c.fetchall()
        conn.close()
        
        # User Status for Highlighting (SPLIT V9)
        s_chart = str(self.user_data.get('strength_chart') or self.user_data.get('current_chart') or '1')
        s_level = str(self.user_data.get('strength_level') or self.user_data.get('current_level') or '1')
        c_chart = str(self.user_data.get('cardio_chart') or self.user_data.get('current_chart') or '1')
        c_level = str(self.user_data.get('cardio_level') or self.user_data.get('current_level') or '1')
        
        # Row Offset for Grid (Header is row 0)
        r_offset = 1
        
        for idx, r in enumerate(rows):
            lvl = str(r[0])
            view_c = str(self.view_chart_idx)
            
            is_s_row = (view_c == s_chart and lvl == s_level)
            is_c_row = (view_c == c_chart and lvl == c_level)
            
            grid_row = r_offset + idx
            
            # Level Label Highlighting 
            lbl_bg = "#34495e"
            if is_s_row: lbl_bg = "#27ae60"
            elif is_c_row: lbl_bg = "#c0392b"
             
            tk.Label(self.chart_content, text=bx.get_level_display(lvl), bg=lbl_bg, fg="white", font=("Arial", 12), width=6).grid(row=grid_row, column=0, padx=2, pady=2, sticky="nsew")
            
            # Reps / Times (r starts at index 1 for ex1)
            cnt = 5
            # Adjust count based on what we are showing
            show_walk = (c_config['walk'] is not None)
            
            # r has [level, ex1..ex5, run, walk] (indices 0..7)
            # We want to show: 1..5, Run, Walk?
            # We updated headers above.
            cols_to_show = 5 + 1 # +Run
            if show_walk: cols_to_show += 1
            
            for i in range(cols_to_show):
                val = r[i+1] # r[1] is ex1
                
                # Format time for run/walk (indices 5, 6)
                disp_val = str(val)
                if i >= 5:
                    m = val // 60
                    s = val % 60
                    disp_val = f"{m}:{s:02d}"
                    if val == 0: disp_val = "-" # Show dash if no data
                
                # Logic: Ex 1-4 (i 0-3) use Strength; Ex 5+ (i 4,5,6) use Cardio
                if i < 4:
                    cell_bg = "#34495e" # Default Strength
                    if is_s_row: cell_bg = "#27ae60" # Strength Green Highlight
                else:
                    cell_bg = "#544040" # Default Cardio (Reddish tint)
                    if is_c_row: cell_bg = "#c0392b" # Cardio Red Highlight
                
                tk.Label(self.chart_content, text=disp_val, bg=cell_bg, fg="white", font=("Arial", 12)).grid(row=grid_row, column=i+1, padx=2, pady=2, sticky="nsew")
                
        # Configure grid weights
        self.chart_content.grid_columnconfigure(0, weight=1)
        for i in range(cols_to_show): self.chart_content.grid_columnconfigure(i+1, weight=3)

    def show_exercise_history_popup(self, name, idx):
        # Reuse existing logic but in a new Toplevel is easiest to ensure it sits on top of chart viewer
        self.show_exercise_history(self.view_chart_idx, idx, name) 
        pass 
        
    def show_exercise_info(self, idx):
        self.selected_exercise_idx = idx # Track selection
        
        # Clear Info Pane
        for widget in self.info_pane.winfo_children(): widget.destroy()
        
        details = bx.get_exercise_detail(str(self.view_chart_idx), idx)
        
        # Title
        tk.Label(self.info_pane, text=details['name'], font=("Helvetica", 16, "bold"), bg="#34495e", fg="white").pack(anchor="w", padx=10, pady=5)
        
        content_frame = tk.Frame(self.info_pane, bg="#34495e")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        
        # Image (Left)
        img_path = os.path.join(IMG_DIR, details['img'])
        screen_w = self.chart_win.winfo_screenwidth()
        max_img_w = int(screen_w * 0.5)
        text_wrap = int(screen_w * 0.4) # Leave space for text
        
        if os.path.exists(img_path) and details['img']:
            try:
                load = Image.open(img_path)
                orig_w, orig_h = load.size
                
                # Target Height is 250, but constrain Width to max_img_w
                target_h = 250
                target_w = int(target_h * (orig_w / orig_h))
                
                if target_w > max_img_w:
                    target_w = max_img_w
                    target_h = int(target_w * (orig_h / orig_w))
                
                load = load.resize((target_w, target_h), Image.Resampling.LANCZOS)
                render = ImageTk.PhotoImage(load)
                img_lbl = tk.Label(content_frame, image=render, bg="#34495e")
                img_lbl.image = render # Keep Ref
                img_lbl.pack(side=tk.LEFT, padx=10)
            except: pass
            
        # Description (Right)
        f_desc = tk.Frame(content_frame, bg="#34495e")
        f_desc.pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)

        tk.Label(f_desc, text=details['desc'], font=("Arial", 12), bg="#34495e", fg="#ecf0f1", wraplength=text_wrap, justify=tk.LEFT).pack(anchor="w", fill=tk.BOTH)

        # --- TREADMILL CHART (Run/Walk Only) ---
        # Ex 5 (idx 4) is Stationary.
        # Ex 6 (idx 5) is Run.
        # Ex 7 (idx 6) is Walk.
        
        target_mode = None
        if idx == 5: target_mode = "RUN"
        elif idx == 6: target_mode = "WALK"
        
        if target_mode:
            # 1. Get Distances
            chart_str = str(self.view_chart_idx)
            cfg = bx.get_cardio_config(chart_str)
            
            # Helper to parse "1 Mile" -> 1.0
            def parse_dist(txt):
                if not txt: return 0
                try:
                    # Assumes format like "1 Mile..." or "1/2 Mile..."
                    first = txt.split()[0]
                    if "/" in first:
                        n, d = first.split("/")
                        return float(n)/float(d)
                    return float(first)
                except: return 0
            
            # Determine params
            dist = 0
            m_idx = 0
            
            if target_mode == "RUN":
                 dist = parse_dist(cfg.get('run'))
                 m_idx = 5 # Index in get_targets
            elif target_mode == "WALK":
                 dist = parse_dist(cfg.get('walk'))
                 m_idx = 6 # Index in get_targets
            
            if dist > 0:
                tk.Label(f_desc, text=f"\n🏃 {target_mode} SETTINGS ({dist} Mile(s))", font=("Arial", 10, "bold"), bg="#34495e", fg="#3498db").pack(anchor="w", pady=(10, 0))
                
                # Table Frame
                f_table = ttk.Frame(f_desc)
                f_table.pack(anchor="w", fill=tk.X, pady=5)
                
                cols = ("Level", "Time", "MPH", "KPH")
                tv = ttk.Treeview(f_table, columns=cols, show="headings", height=12)
                tv.pack(fill=tk.X)
                
                for c in cols: 
                    tv.heading(c, text=c)
                    tv.column(c, width=60, anchor="center")
                    
                # Calculate for Levels 12 down to 1 (A+ to D-)
                for l in range(12, 0, -1):
                    targs = bx.get_targets(chart_str, str(l))
                    time_sec = targs[m_idx] if len(targs) > m_idx else 0
                    
                    if time_sec > 0:
                        mins = time_sec // 60
                        secs = time_sec % 60
                        t_str = f"{mins}:{secs:02d}"
                        
                        # Speed = Dist / (Sec / 3600)
                        mph = dist / (time_sec / 3600.0)
                        kph = mph * 1.60934
                        
                        # Level Display (e.g. "A+")
                        lvl_disp = bx.get_level_display(l)
                        
                        tv.insert("", "end", values=(lvl_disp, t_str, f"{mph:.1f}", f"{kph:.1f}"))
                
                # Adjust height to content
                tv.configure(height=12)

        # --- GRAPH RENDERING ---
        for widget in self.graph_pane.winfo_children(): widget.destroy()
        
        records = self.db_get_history(self.user_id)
        report_reps, report_hr, report_hrv, dates = [], [], [], []
        
        records = self.db_get_history(self.user_id)
        report_reps, report_hr, report_hrv, dates = [], [], [], []
        
        for r in records:
            # Filter by Current Chart (Handle Split Logic)
            raw_chart = str(r['chart'])
            chart = raw_chart
            
            # SPLIT LOGIC v9
            if "/" in chart:
                parts = chart.split("/")
                if len(parts) >= 2:
                    if idx < 4: chart = parts[0] # Strength
                    else: chart = parts[1] # Cardio
            
            # DEBUG
            # print(f"Processing Rec: ID={r['id']} RawChart={raw_chart} EffChart={chart} ViewChart={self.view_chart_idx}")

            if chart != str(self.view_chart_idx):
                 # print(f"  -> SKIPPED (Chart Mismatch)")
                 continue

            # print(f"  -> ACCEPTED")
                 
            # Parse Reps
            reps_list = [0]*5
            if r['ex1']: reps_list = [r['ex1'], r['ex2'], r['ex3'], r['ex4'], r['ex5']]
            
            # Helper to get value
            val = 0
            e_type = r.get('ex5_type', "")
            e_dur = r.get('ex5_duration', 0)
            
            if idx < 5:
                # Standard Logic
                if idx == 4: # Standard Stationary Filter
                     # If EX 5 type IS Run or Walk, skip this record for Stationary Graph
                     if e_type and ("Run" in e_type or "Walk" in e_type) and "Stationary" not in e_type:
                         continue
                
                if reps_list[idx] <= 0: continue
                val = reps_list[idx]
            else:
                # Handle Ex 6 (Run) / 7 (Walk)
                if idx == 5: # Run
                    if "Run" in e_type and "Stationary" not in e_type: val = e_dur
                elif idx == 6: # Walk
                    if "Walk" in e_type: val = e_dur
                    
                if val <= 0: continue
            
            # Parse Detailed Stats (JSON)
            hr = 0
            hrv = 0
            stats_json = r.get('segment_stats')
            if stats_json:
                try:
                    data = json.loads(stats_json)
                    
                    # Handle V2 format
                    segments = []
                    if isinstance(data, dict):
                        segments = data.get('segments', [])
                    elif isinstance(data, list):
                        segments = data
                        
                    # Use Index Math: reliable 0-4
                    target_stats_idx = idx
                    if idx >= 5: target_stats_idx = 4 # Map back to Ex 5 slot for stats
                    
                    if target_stats_idx < len(segments):
                         item = segments[target_stats_idx]
                         hr = item.get('max_hr', 0)
                         hrv = item.get('hrv', 0)
                except: pass
            
            # If no detailed stats found, maybe use session average? No, keep 0 to avoid noise.
            
            dates.append(r['timestamp'][:10])
            report_reps.append(val)
            report_hr.append(hr)
            report_hrv.append(hrv)

        # Reverse to show chronological left-to-right
        dates = dates[::-1]
        report_reps = report_reps[::-1]
        report_hr = report_hr[::-1]
        report_hrv = report_hrv[::-1]
        
        # Plot
        fig = Figure(figsize=(10, 3), dpi=90, facecolor="#34495e") # Shorter height
        
        # Ax1: Reps
        ax1 = fig.add_subplot(121)
        ax1.set_facecolor("#2c3e50")
        ax1.plot(dates, report_reps, marker='o', color='#2ecc71', linewidth=2, label="Score")
        t_label = "Reps Progress"
        if idx >= 5: t_label = "Time (Seconds)"
        ax1.set_title(t_label, color="white", fontsize=10)
        ax1.tick_params(axis='x', colors='white', labelsize=8, rotation=45)
        ax1.tick_params(axis='y', colors='white')
        ax1.grid(color='#7f8c8d', linestyle='--', linewidth=0.5)
        
        # Ax2: HR / HRV
        ax2 = fig.add_subplot(122)
        ax2.set_facecolor("#2c3e50")
        ax2.plot(dates, report_hr, marker='s', color='#e74c3c', linewidth=2, label="Max HR")
        ax2.set_title("Physiological Cost (HR & HRV)", color="white", fontsize=10)
        
        ax2_b = ax2.twinx()
        ax2_b.plot(dates, report_hrv, marker='^', color='#f1c40f', linestyle='--', linewidth=1.5, label="HRV")
        
        ax2.tick_params(axis='x', colors='white', labelsize=8, rotation=45)
        ax2.tick_params(axis='y', colors='#e74c3c')
        ax2_b.tick_params(axis='y', colors='#f1c40f')
        
        # Combined Legend
        lines, labels = ax2.get_legend_handles_labels()
        lines2, labels2 = ax2_b.get_legend_handles_labels()
        ax2.legend(lines + lines2, labels + labels2, loc='upper left', fontsize=8)
        
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.graph_pane)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)


    def delete_history_item(self):
        selected = self.hist_tree.selection()
        if not selected: return
        db_id = int(selected[0])
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("SELECT MAX(id) FROM history WHERE user_id=?", (self.user_id,))
        latest_id = c.fetchone()[0]
        conn.close()

        if messagebox.askyesno("Confirm", "Delete this record?"):
            # V13 FIX: Capture state BEFORE delete
            del_c, del_l = "1", "1"
            is_latest = (db_id == latest_id)
            
            if is_latest:
                 conn = sqlite3.connect(USER_DB_FILE)
                 c = conn.cursor()
                 c.execute("SELECT chart, level FROM history WHERE id=?", (db_id,))
                 row_del = c.fetchone()
                 conn.close()
                 if row_del:
                     del_c = str(row_del[0])
                     del_l = str(row_del[1])

            self.db_delete_history(db_id)
            
            # If we deleted the LATEST record, we revert to the state stored IN that record
            # (which represents the start point of that session)
            if is_latest:
                 prev_c_str = del_c
                 prev_l_str = del_l
                 
                 # Handle Split Format: "1/1", "2/1"
                 s_c, c_c = "1", "1"
                 s_l, c_l = "1", "1"
                 
                 if " | " in prev_c_str:
                      parts = prev_c_str.split(" | ")
                      if len(parts) >= 2: s_c, c_c = parts[0], parts[1]
                 elif "/" in prev_c_str:
                      parts = prev_c_str.split("/")
                      if len(parts) >= 2: s_c, c_c = parts[0], parts[1]
                 else: s_c, c_c = prev_c_str, prev_c_str
                 
                 if " | " in prev_l_str:
                      parts = prev_l_str.split(" | ")
                      if len(parts) >= 2: s_l, c_l = parts[0], parts[1]
                 elif "/" in prev_l_str:
                      parts = prev_l_str.split("/")
                      if len(parts) >= 2: s_l, c_l = parts[0], parts[1]
                 else: s_l, c_l = prev_l_str, prev_l_str
                 
                 self.db_update_split_level(self.user_id, s_c, s_l, c_c, c_l)
                 
                 # Format for Message
                 s_disp_l = bx.get_level_display(s_l)
                 c_disp_l = bx.get_level_display(c_l)
                 messagebox.showinfo("Synced", f"Most recent workout deleted. Level reverted to start of that session:\n\nStrength: {s_c} {s_disp_l}\nCardio: {c_c} {c_disp_l}")
            
            self.show_history_screen()

    # --- EXERCISE FLOW ---
    def start_workout(self):
        self.dashboard_active = False
        self.current_exercise_idx = 0
        self.session_metrics = []
        self.reps_achieved = []
        self.logger = SessionLogger(self.username)
        self.logger.start()

        # V9: Split Strength/Cardio
        s_chart = self.user_data.get("strength_chart") or self.user_data.get("current_chart") or "1"
        s_level = self.user_data.get("strength_level") or self.user_data.get("current_level") or "1"
        c_chart = self.user_data.get("cardio_chart") or self.user_data.get("current_chart") or "1"
        c_level = self.user_data.get("cardio_level") or self.user_data.get("current_level") or "1"
        
        strength_targets = bx.get_targets(s_chart, s_level)
        cardio_targets = bx.get_targets(c_chart, c_level)
        
        # Combine: First 4 from Strength, 5th from Cardio
        # targets includes [ex1..ex5, run, walk]
        # Store full cardio targets for later selection
        self.cardio_targets_all = cardio_targets
        
        # Initial target list - Ex 5 placeholder until selected
        self.target_reps_list = strength_targets[:4] + [cardio_targets[4]]
        
        # Reset Mode
        self.current_cardio_mode = None
        
        self.workout_active = True
        self.timer_running = False
        
        # Switch to main thread loop for UI safety
        self.run_exercise_screen()
        self.sensor_loop() 

    def reset_sensor_connection(self):
        print("Force Resetting Sensor...")
        
        # UI STEP 1: Closing
        try:
            if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                 self.lbl_device_status.config(text="📡 Closing USB Connection...", foreground="#e67e22")
            if hasattr(self, 'lbl_device_dash') and self.lbl_device_dash.winfo_exists():
                 self.lbl_device_dash.config(text="📡 Closing USB...", foreground="#e67e22")
        except: pass
        self.update() # Force UI refresh

        if self.sensor:
            try: self.sensor.stop()
            except: pass
            self.sensor = None
            
        # UI STEP 2: Waiting/Re-opening
        try:
            if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                 self.lbl_device_status.config(text="📡 Re-opening USB Connection...", foreground="#e67e22")
        except: pass
        
        # Stop any pending retry loops
        if self.retry_task:
             try: self.after_cancel(self.retry_task)
             except: pass
             self.retry_task = None
             
        # Stop any pending reset delay (Debounce)
        if self.reset_task:
             try: self.after_cancel(self.reset_task)
             except: pass
             self.reset_task = None
             
        self.is_reconnecting = False # Force release lock for this manual action

        # Smart Init will handle the waiting -> Instant callback
        # Wait 2.0s to allow proper USB resource release by OS
        self.reset_task = self.after(2000, self.init_sensor)
        
    def run_exercise_screen(self):
        self._clear()
        idx = self.current_exercise_idx
        if idx >= 5:
            self.finish_workout()
            return

        chart = self.user_data["current_chart"]
        
        # CARDIO SELECTION INTERCEPT
        if idx == 4 and self.current_cardio_mode is None:
             frame = ttk.Frame(self)
             frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
             
             c_chart = chart
             if "/" in str(chart):
                 try: c_chart = chart.split("/")[1]
                 except: pass
                 
             self._show_cardio_selection(frame, c_chart)
             return

             self._show_cardio_selection(frame, c_chart)
             return

        # Use Cardio Mode for variant details if applicable
        variant = "Standard"
        if idx == 4 and self.current_cardio_mode:
            variant = self.current_cardio_mode
            
        details = bx.get_exercise_detail(chart, idx, variant)
        target = self.target_reps_list[idx]
        duration = bx.TIME_LIMITS[idx]

        self.session_metrics.append({'name': details['name'], 'hr': [], 'rmssd': []})

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        # Top Bar
        top_bar = ttk.Frame(frame)
        top_bar.pack(fill=tk.X, pady=5)
        
        tk.Button(top_bar, text="⬅ Quit Workout", command=self.show_dashboard, bg="#e74c3c", fg="white").pack(side=tk.LEFT)
        tk.Button(top_bar, text="📡 Reset", command=self.reset_sensor_connection, bg="#e67e22", fg="white").pack(side=tk.RIGHT)
        
        title_text = f"Exercise {idx+1}: {details['name']}"
        
        # Customize title for Run/Walk to show distance
        if idx == 4 and self.current_cardio_mode:
             # Logic to extract distance similar to below, or just use the whole string?
             # User wants: "Run (Distance)"
             # self.current_cardio_mode is like "1 Mile (1.6 km) Run"
             # We want "Run (1 Mile (1.6 km))" or just swap it?
             # Let's say details['name'] is "Run" (from get_exercise_detail) 
             # actually get_exercise_detail returns generic names mostly unless overridden.
             # Let's use current_cardio_mode to build it.
             
             raw = self.current_cardio_mode
             dist_text = ""
             mode_name = "Run"
             if "Run" in raw: 
                 dist_text = raw.replace(" Run", "")
                 mode_name = "Run"
             elif "Walk" in raw: 
                 dist_text = raw.replace(" Walk", "")
                 mode_name = "Walk"
             elif "Stationary" in raw:
                 mode_name = "Stationary Run"
                 
             if dist_text:
                 title_text = f"Exercise {idx+1}: {mode_name} - {dist_text}"
             elif mode_name == "Stationary Run":
                 title_text = f"Exercise {idx+1}: Stationary Run"

        ttk.Label(frame, text=title_text, font=("Helvetica", 24, "bold")).pack()

        img_path = os.path.join(IMG_DIR, details['img'])
        if os.path.exists(img_path) and details['img']:
            try:
                load = Image.open(img_path)
                orig_w, orig_h = load.size
                target_w = 400
                target_h = int(target_w * (orig_h / orig_w))
                if target_h > 300: target_h = 300; target_w = int(target_h * (orig_h / orig_w))
                load = load.resize((target_w, target_h), Image.Resampling.LANCZOS)
                render = ImageTk.PhotoImage(load)
                img_lbl = tk.Label(frame, image=render, bg="#2c3e50")
                img_lbl.image = render
                img_lbl.pack(pady=10)
            except: pass
            
        ttk.Label(frame, text=details['desc'], wraplength=800, justify=tk.CENTER, font=("Arial", 16)).pack(pady=10)
        
        # History Button Logic
        hist_idx = idx
        if idx == 4 and self.current_cardio_mode:
            if "Run" in self.current_cardio_mode and "Stationary" not in self.current_cardio_mode: hist_idx = 5
            elif "Walk" in self.current_cardio_mode: hist_idx = 6
        
        hist_chart_filter = chart
        if "/" in str(chart):
            parts = str(chart).split("/")
            if len(parts) >= 2:
                if idx < 4: hist_chart_filter = parts[0]
                else: hist_chart_filter = parts[1]
                
        tk.Button(frame, text=f"📈 View History: {details['name']}", 
                 command=lambda: self.show_exercise_history(hist_chart_filter, hist_idx, details['name'])).pack(pady=5)
        
        # STATS BOX (Dark Background)
        stats_frame = tk.Frame(frame, bg="#22313f", bd=2, relief=tk.RAISED)
        stats_frame.pack(fill=tk.X, padx=40, pady=10)
        
        lbl_target = ttk.Label(stats_frame, text=f"GOAL: {target}", font=("Courier", 32, "bold"), foreground="#ecf0f1", background="#22313f")
        lbl_target.pack(pady=10) # Center
        
        self.time_left = duration
        self.lbl_timer = ttk.Label(stats_frame, text=f"{self.time_left}s", font=("Arial", 80, "bold"), background="#22313f", foreground="#bdc3c7")
        self.lbl_timer.pack(pady=5) # Center

        self.lbl_hr = ttk.Label(frame, text="HR: --", font=("Arial", 48, "bold"))
        self.lbl_hr.pack()
        self.lbl_advice = ttk.Label(frame, text="Get Ready...", foreground="darkorange", font=("Arial", 24, "bold"))
        self.lbl_advice.pack()
        
        # HRM Status Label (Inside Frame for visibility or stick to bottom?)
        # User requested "Goal, Treadmill and status underneath that could all be in a rectangle"
        self.lbl_device_status = ttk.Label(stats_frame, text="📡 Scanning...", foreground="#95a5a6", background="#22313f", font=("Arial", 14))
        self.lbl_device_status.pack(side=tk.BOTTOM, pady=5)
        
        # DISTANCE DISPLAY (NEW)
        if idx == 4:
             dist_text = ""
             # Check for Run/Walk variant
             if self.current_cardio_mode:
                 if "Run" in self.current_cardio_mode:
                     c_config = bx.get_cardio_config(chart)
                     # Parse out the distance part if possible, or just use the whole string?
                     # The string is like "1 Mile (1.6 km) Run"
                     # Let's extract "1 Mile (1.6 km)"
                     raw = self.current_cardio_mode
                     if "Run" in raw: dist_text = raw.replace(" Run", "")
                     elif "Walk" in raw: dist_text = raw.replace(" Walk", "")
                     else: dist_text = raw
                 
             if dist_text:
                 ttk.Label(stats_frame, text=f"Distance: {dist_text}", foreground="#f1c40f", background="#22313f", font=("Arial", 18, "bold")).pack(pady=5)


        # Alt Cardio Mode Logic
        if idx == 4 and self.current_cardio_mode and ("Run" in self.current_cardio_mode or "Walk" in self.current_cardio_mode) and "Stationary" not in self.current_cardio_mode:
             # Manual Mode UI
             # Removed explicitly hiding HR/Advice/Timer. We want HR and Advice visible.
             # self.lbl_hr.pack_forget() <- REMOVED
             # self.lbl_advice.pack_forget() <- REMOVED
             
             self.lbl_timer.pack_forget() # Hide Timer for Run/Walk as per user request
             
             # Actually we only want to hide the TIMER if we are doing distance based, but user might want to see elapsed time?
             # User Request: "show HR, HR status and HRV"
             # So we keep lbl_hr and lbl_advice (status).
             # We might want to hide the COUNTDOWN TIMER (`lbl_timer`) if it's not relevant, but let's just leave it or repurpose?
             # The code below changes lbl_target to GOAL TIME. 
             # Let's just create the HRV label here too.
             
             # Show Target Time clearly
             mins = target // 60
             secs = target % 60
             lbl_target.config(text=f"GOAL: {mins}:{secs:02d}")
             
             # Show Treadmill Speed
             try:
                 # Distances
                 dist = 0
                 c_idx = int(chart.split('/')[1] if '/' in str(chart) else chart)
                 if "Run" in self.current_cardio_mode:
                     dist = 0.5 if c_idx == 1 else 1.0
                 elif "Walk" in self.current_cardio_mode:
                     dist = 1.0 if c_idx == 1 else 2.0
                     
                 if dist > 0:
                     hours = target / 3600.0
                     mph = dist / hours
                     kph = mph * 1.60934
                     # Cyan color for high visibility on dark bg
                     ttk.Label(stats_frame, text=f"Speed: {mph:.1f} mph ({kph:.1f} km/h)", 
                               foreground="#00ffff", background="#22313f", font=("Arial", 18, "bold")).pack(pady=5)
             except: pass
             
             # LIVE HRV DISPLAY (Added here as well)
             self.lbl_hrv = ttk.Label(frame, text="HRV: -- ms", font=("Arial", 24), foreground="white")
             self.lbl_hrv.pack()
             
             self.btn_action = tk.Button(frame, text="ENTER TIME TAKEN", bg="#3498db", fg="white", font=("Arial", 14, "bold"), command=self.input_results)
             self.btn_action.pack(fill=tk.X, side=tk.BOTTOM, pady=10)
        else:
             # LIVE HRV DISPLAY (NEW)
             # Add a label for HRV next to HR
             self.lbl_hrv = ttk.Label(frame, text="HRV: -- ms", font=("Arial", 24), foreground="white")
             self.lbl_hrv.pack()
             
             self.btn_action = tk.Button(frame, text="START EXERCISE (3s Countdown)", bg="#2ecc71", fg="white", font=("Arial", 14, "bold"), command=self.start_timer_action)
             self.btn_action.pack(fill=tk.X, side=tk.BOTTOM, pady=10)
        self.timer_running = False

    def _show_cardio_selection(self, parent, chart):
        # Top Bar
        top_bar = ttk.Frame(parent)
        top_bar.pack(fill=tk.X, pady=5)
        tk.Button(top_bar, text="⬅ Quit Workout", command=self.show_dashboard, bg="#e74c3c", fg="white").pack(side=tk.LEFT)
        tk.Button(top_bar, text="📡 Reset", command=self.reset_sensor_connection, bg="#e67e22", fg="white").pack(side=tk.RIGHT)

        ttk.Label(parent, text="Select Exercise 5 Variant", font=("Arial", 20, "bold")).pack(pady=10)
        
        # Get Config
        config = bx.get_cardio_config(chart)
        
        # Option 1: Stationary
        # Target is at index 4 (Standard)
        t_stat = self.cardio_targets_all[4]
        def sel_stat():
            self.current_cardio_mode = "Standard (Stationary)"
            self.target_reps_list[4] = t_stat
            self.run_exercise_screen() # Refresh
            
        b1 = tk.Button(parent, text=f"Stationary Run\nTarget: {t_stat} Reps", font=("Arial", 14), bg="#e67e22", fg="white", height=3, command=sel_stat)
        b1.pack(fill=tk.X, pady=10, padx=20)
        
        # Option 2: Run
        # Target at index 5
        t_run = self.cardio_targets_all[5] if len(self.cardio_targets_all) > 5 else 0
        m = t_run // 60; s = t_run % 60
        lbl_run = config['run']
        def sel_run():
            self.current_cardio_mode = lbl_run
            self.target_reps_list[4] = t_run
            self.run_exercise_screen()
            
        b2 = tk.Button(parent, text=f"{lbl_run}\nTarget: {m}:{s:02d}", font=("Arial", 14), bg="#e74c3c", fg="white", height=3, command=sel_run)
        b2.pack(fill=tk.X, pady=10, padx=20)
        
        # Option 3: Walk (if exists)
        lbl_walk = config['walk']
        if lbl_walk:
            t_walk = self.cardio_targets_all[6] if len(self.cardio_targets_all) > 6 else 0
            m = t_walk // 60; s = t_walk % 60
            def sel_walk():
                self.current_cardio_mode = lbl_walk
                self.target_reps_list[4] = t_walk
                self.run_exercise_screen()
                
            b3 = tk.Button(parent, text=f"{lbl_walk}\nTarget: {m}:{s:02d}", font=("Arial", 14), bg="#9b59b6", fg="white", height=3, command=sel_walk)
            b3.pack(fill=tk.X, pady=10, padx=20)


    def start_timer_action(self):
        # Disable button during countdown
        self.btn_action.config(state=tk.DISABLED, bg="#95a5a6", text="Starting...")
        self.start_countdown(3)

    def start_countdown(self, count):
        if not hasattr(self, 'lbl_timer') or not self.lbl_timer.winfo_exists(): return
        
        if count > 0:
            # Display Count on TIMER LABEL (Stats Box)
            self.lbl_timer.config(text=str(count), foreground="#f1c40f", font=("Arial", 80, "bold"))
            self.play_beep()
            self.after(1000, lambda: self.start_countdown(count - 1))
        else:
            # GO!
            self.lbl_timer.config(text="GO!", foreground="#2ecc71", font=("Arial", 80, "bold"))
            self.play_beep() 
            
            # Start Actual Timer
            self.timer_running = True
            self.btn_action.config(state=tk.NORMAL, text="COMPLETED (Input Reps)", bg="#e67e22", command=self.input_results)
            
            # Wait 1s then restore and start
            self.after(1000, self._start_real_timer)

    def _start_real_timer(self):
        if not self.workout_active or not self.timer_running: return
        if hasattr(self, 'lbl_timer') and self.lbl_timer.winfo_exists():
            self.lbl_timer.config(font=("Arial", 80, "bold"), foreground="#bdc3c7")
            self.timer_loop()

    def input_results(self):
        self.timer_running = False
        idx = self.current_exercise_idx
        chart = self.user_data["current_chart"]
        details = bx.get_exercise_detail(chart, idx)

        top = tk.Toplevel(self)
        top.title("Report Card")
        top.geometry("300x250")
        top.configure(bg="#34495e")
        top.transient(self); top.grab_set()
        tk.Label(top, text=f"Reps Completed for\n{details['name']}:", fg="white", bg="#34495e", font=("Arial", 12)).pack(pady=20)
        e_reps = tk.Entry(top, font=("Arial", 14), justify='center')
        e_reps = tk.Entry(top, font=("Arial", 14), justify='center')
        
        # Check based on current mode, not just index
        is_alt_cardio = (idx == 4 and self.current_cardio_mode and ("Run" in self.current_cardio_mode or "Walk" in self.current_cardio_mode) and "Stationary" not in self.current_cardio_mode)
        
        if is_alt_cardio:
             tk.Label(top, text="Time Taken (MM:SS):", fg="white", bg="#34495e").pack()
             e_reps.insert(0, "")
        else:
             e_reps.insert(0, str(self.target_reps_list[idx]))
             
        e_reps.pack(pady=10); e_reps.select_range(0, tk.END); e_reps.focus_force()
        self.temp_reps_buffer = None
        
        def save_reps(event=None):
            try: 
                val = 0
                if is_alt_cardio:
                    # Parse MM:SS
                    txt = e_reps.get().strip()
                    if ":" in txt:
                        parts = txt.split(":")
                        val = int(parts[0]) * 60 + int(parts[1])
                    else:
                        val = int(txt) * 60 # Assume minutes if no colon? Or seconds? Assume M:S usually.
                else:
                    val = int(e_reps.get().strip())
                    
                self.temp_reps_buffer = val
                
                # BADGE LOGIC
                target = self.target_reps_list[idx]
                badge = None
                color = "gold"
                
                if is_alt_cardio:
                    # Time: Lower is better
                    diff = target - val # Positive if faster (better)
                    if diff >= 60: badge = "🔥 UNSTOPPABLE"; color="#e74c3c"
                    elif diff >= 10: badge = "🚀 SMASHED IT"; color="#9b59b6"
                    elif diff >= 0: badge = "🎯 TARGET HIT"; color="#2ecc71"
                else:
                    # Reps: Higher is better
                    diff = val - target
                    if diff >= target * 0.2 and target > 10: badge = "🔥 UNSTOPPABLE"; color="#e74c3c"
                    elif diff >= target * 0.1 and target > 10: badge = "🚀 SMASHED IT"; color="#9b59b6"
                    elif diff >= 0: badge = "🎯 TARGET HIT"; color="#2ecc71"
                
                if badge:
                    # Celebration Animation
                    for w in top.winfo_children(): w.destroy()
                    top.configure(bg=color)
                    tk.Label(top, text="🎉", font=("Arial", 60), bg=color).pack(expand=True)
                    tk.Label(top, text=badge, font=("Arial", 24, "bold"), fg="white", bg=color).pack(pady=10)
                    top.update()
                    self.after(2000, top.destroy)
                else:
                    top.destroy()
            except: pass
        btn = tk.Button(top, text="Confirm", command=save_reps, bg="#2ecc71"); btn.pack(pady=20); top.bind('<Return>', save_reps)
        self.wait_window(top)

        if self.temp_reps_buffer is not None:
            self.reps_achieved.append(self.temp_reps_buffer)
            self.current_exercise_idx += 1
            self.run_exercise_screen()
        else: self.input_results()

    def timer_loop(self):
        if not self.workout_active or not self.timer_running: return
        
        # Safety Check: Ensure widget exists before configuring
        if not hasattr(self, 'lbl_timer') or not self.lbl_timer.winfo_exists():
            self.timer_running = False
            return

        if self.time_left > 0:
            self.time_left -= 1
            self.lbl_timer.config(text=f"{self.time_left}s")
            self.after(1000, self.timer_loop)
        else:
            self.lbl_timer.config(text="TIME UP!", foreground="red")
            self.play_beep()
            # AUTO-STOP LOGIC (NEW)
            # Automatically trigger input results
            self.input_results()

    def sensor_loop(self):
        if not self.workout_active: return
        
        # --- AUTO-RECONNECT LOGIC ---
        current_time = time.time()
        needs_restart = False
        
        if self.sensor is None: needs_restart = True
        elif not self.sensor.running: needs_restart = True
        elif hasattr(self.sensor, 'status') and str(self.sensor.status).startswith("Error"): needs_restart = True
        
        if needs_restart and not self.is_reconnecting:
            if (current_time - self.last_reconnect_attempt) > 5.0:
                print("⚠️ Auto-Reconnecting Sensor (Dropout Detected)...")
                self.last_reconnect_attempt = current_time
                
                # Update Status if possible
                if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                    self.lbl_device_status.config(text="📡 Reconnecting...", foreground="#e67e22")
                    
                # Use our Smart Retry Init
                self.init_sensor() 
            else:
                # Cooldown period
                pass
                
        if self.sensor and self.sensor.running:
            data = self.sensor.get_data()
            hr = data['bpm']
            rmssd = data['rmssd']

            chart = self.user_data["current_chart"]
            level = self.user_data["current_level"]
            trend = f"C{chart}-Ex {self.current_exercise_idx+1}"

            # Advice Logic
            limit_95 = self.true_max_hr * 0.95
            limit_90 = self.true_max_hr * 0.90
            limit_60 = self.true_max_hr * 0.60
            status_text, status_color, log_status = "Zone OK", "#2ecc71", "OK"

            if hr >= limit_95: status_text, status_color, log_status = "⚠️ DANGER! STOP NOW", "#e74c3c", "CRITICAL"
            elif hr >= limit_90: status_text, status_color, log_status = "⚠️ Limit Reached - SLOW DOWN", "#e67e22", "WARNING"
            elif hr < limit_60 and self.current_exercise_idx == 4: status_text, status_color, log_status = "⚡ Push Harder!", "#f1c40f", "LOW"

            if hr > 0:
                if self.current_exercise_idx < len(self.session_metrics):
                    self.session_metrics[self.current_exercise_idx]['hr'].append(hr)
                    self.session_metrics[self.current_exercise_idx]['rmssd'].append(rmssd)

                if self.logger and self.current_exercise_idx < len(self.session_metrics):
                    name = self.session_metrics[self.current_exercise_idx]['name']
                    raw_rr = data.get('raw_rr_ms', 0)
                    raw_hex = data.get('raw_hex', '')
                    self.logger.log(hr, rmssd, raw_rr, raw_hex, f"Ch {chart} - Lvl {level}", f"C{chart}-Ex {self.current_exercise_idx+1}: {name}", log_status, data.get('battery_volts'))

                try:
                    txt = f"♥ {hr} BPM"
                    if hasattr(self, 'lbl_hr'): self.lbl_hr.config(text=txt, foreground="#2c3e50")
                    
                    # LIVE HRV UPDATE (NEW)
                    if hasattr(self, 'lbl_hrv'): 
                        self.lbl_hrv.config(text=f"HRV: {int(rmssd)} ms", foreground="#2c3e50")

                    if hasattr(self, 'lbl_advice'): self.lbl_advice.config(text=status_text, foreground=status_color)
                except: pass
        
            # Update Device Status Label (Detailed)
            manuf = data.get('manufacturer', 'Unknown')
            serial = data.get('serial')
            bat = data.get('battery_volts')
            bat_state = data.get('battery_state', 'Unknown')
            uptime = data.get('uptime_hours')
            bpm = data.get('bpm', 0)
            status = data.get('status', 'Initializing')
            
            # --- PATCH: If we have stale data (status is not Active and loop has stalled), fall through ---
            if status != "Active" and bpm == 0:
                 # Treat as disconnected for UI Update purposes to prevent stuck values
                 pass

            if status == "Active" or bpm > 0:
                stat_txt = f"📡 - ✅ {manuf} #{serial}" if serial else f"📡 - ❌ {manuf}"
                if bat: stat_txt += f" | 🔋 {bat}V ({bat_state})"
                if uptime and uptime > 0: stat_txt += f" | ⏱ {uptime}h"
            else:
                stat_txt = f"📡 {status}..."

            try:
                if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                        self.lbl_device_status.config(text=stat_txt, foreground="#2ecc71" if hr > 0 else "#95a5a6")
            except: pass
            
        else:
            # SENSOR IS DOWN / RECONNECTING - Mark Data Stale
            try:
                if hasattr(self, 'lbl_hr') and self.lbl_hr.winfo_exists():
                     self.lbl_hr.config(text="♥ -- BPM", foreground="#e74c3c") # Red for Stale
                if hasattr(self, 'lbl_hrv') and self.lbl_hrv.winfo_exists():
                     self.lbl_hrv.config(text="HRV: -- ms", foreground="#e74c3c")
                     
                if hasattr(self, 'lbl_device_status') and self.lbl_device_status.winfo_exists():
                    # If we are effectively reconnecting, keep the orange text, else show Error
                    is_recon = getattr(self, 'is_reconnecting', False)
                    conn_text = "📡 Reconnecting..." if is_recon else "📡 Disconnected"
                    self.lbl_device_status.config(text=conn_text, foreground="#e67e22" if is_recon else "#e74c3c")
            except: pass
            
        self.after(1000, self.sensor_loop)

    # --- FINISH & REPORT ---
    def _get_consecutive_fails(self, component="Strength"):
        """Count consecutive fails/non-upgrades backwards in history.
           Stops when it finds an UP, or a Max Level Maintain (Pass)."""
        if not os.path.exists(USER_DB_FILE): return 0
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT chart, level, verdict FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10", (self.user_id,))
            rows = c.fetchall()
            conn.close()
            
            fails = 0
            for r in rows:
                v_str = r['verdict']
                # Parse Verdict Part
                # Format: "Strength (MAINTAIN) / Cardio (UP)" or "Strength (...) | Cardio (...)"
                part = v_str
                if " | " in v_str:
                     parts = v_str.split(" | ")
                     if len(parts) >= 2:
                         part = parts[0] if component == "Strength" else parts[1]
                elif "/" in v_str: # Legacy support
                    parts = v_str.split("/")
                    if len(parts) >= 2:
                        part = parts[0] if component == "Strength" else parts[1]
                
                # Check outcome
                if "UP" in part or "PROMOTION" in part or "LEAPFROG" in part or "LEVEL UP" in part:
                     break # Success breaks the streak
                
                if "MAINTAIN" in part:
                     # Check if Max Level (Pass)
                     raw_c, raw_l = str(r['chart']), str(r['level'])
                     chart, level = raw_c, raw_l
                     
                     if " | " in raw_c:
                         c_parts = raw_c.split(" | ")
                         l_parts = raw_l.split(" | ")
                         if len(c_parts) >= 2:
                             chart = c_parts[0] if component == "Strength" else c_parts[1]
                             level = l_parts[0] if component == "Strength" else l_parts[1]
                     elif "/" in raw_c:
                         c_parts = raw_c.split("/")
                         l_parts = raw_l.split("/")
                         if len(c_parts) >= 2:
                             chart = c_parts[0] if component == "Strength" else c_parts[1]
                             level = l_parts[0] if component == "Strength" else l_parts[1]
                     
                     if str(chart) == "6" and str(level) == "12":
                         break # Max Level Pass
                     
                     fails += 1
                else:
                     # Demotion, Down, etc.
                     fails += 1
            return fails
        except:
            return 0

    def finish_workout(self):
        self.workout_active = False
        if self.logger: self.logger.stop()
        self._clear()

        missed = 0
        for a, t in zip(self.reps_achieved, self.target_reps_list):
            if a < t: missed += 1
        physical_pass = (missed == 0)

        report_text = ["--- SESSION BREAKDOWN ---"]
        
        # REPS SUMMARY
        exercises = ["Toe Touch", "Sit-up", "Back Extension", "Push-up", "Cardio"]
        report_text.append("PERFORMANCE:")
        for i in range(5):
            name = exercises[i]
            done = self.reps_achieved[i]
            target = self.target_reps_list[i]
            
            # Format for Cardio (Time vs Reps)
            if i == 4 and self.current_cardio_mode in ["Run", "Walk"]:
                 # Time
                 done_str = f"{int(done//60)}:{int(done%60):02d}"
                 target_str = f"{int(target//60)}:{int(target%60):02d}"
                 report_text.append(f"{name}: {done_str} / {target_str}")
            else:
                 report_text.append(f"{name}: {done} / {target}")
        report_text.append("") # Spacer
        
        warnings = 0
        session_peak_hr = 0
        all_hr, all_rmssd = [], []

        for i, metric in enumerate(self.session_metrics):
            name, hrs, hrvs = metric['name'], metric['hr'], metric['rmssd']
            if not hrs:
                report_text.append(f"{name}: (No HR Data)"); continue

            avg_hr, max_hr = sum(hrs)/len(hrs), max(hrs)
            all_hr.extend(hrs)
            session_peak_hr = max(session_peak_hr, max_hr)

            if "Back Arch" in name or i == 2: hrv_str = "(Ignored)"; avg_hrv = 999
            else: avg_hrv = sum(hrvs)/len(hrvs) if hrvs else 0; hrv_str = f"{avg_hrv:.1f} ms"; all_rmssd.extend(hrvs)

            status = "OK"
            if max_hr > (self.true_max_hr * 0.95): status = "INTENSE"; warnings += 1
            if avg_hrv < 10 and avg_hrv != 999: status += " / HIGH STRESS"

            line = f"{name}: Avg HR {int(avg_hr)} | Max {max_hr} | HRV {hrv_str}"
            if status != "OK": line += f"\n   -> ⚠️ {status}"
            report_text.append(line)

        if session_peak_hr > self.true_max_hr and session_peak_hr < 220:
            report_text.append(f"\n📈 NEW MAX HR: {session_peak_hr} bpm (Prev: {self.true_max_hr})")
            self.bio_profile.max_hr = session_peak_hr
            if "current_stats" in self.profile_data:
                self.profile_data['current_stats']['max_hr'] = session_peak_hr
                with open(self.full_profile_path, 'w') as f: json.dump(self.profile_data, f, indent=4)
            warnings += 1
            report_text.append("⚠️ Pushed to absolute limit.")

        avg_session_hr = sum(all_hr)/len(all_hr) if all_hr else 0
        max_session_hr = session_peak_hr
        end_session_rmssd = all_rmssd[-1] if all_rmssd else 0

        # V9: SPLIT LOGIC
        # 1. Load Current States
        s_chart = self.user_data.get("strength_chart") or self.user_data.get("current_chart") or "1"
        s_level = self.user_data.get("strength_level") or self.user_data.get("current_level") or "1"
        c_chart = self.user_data.get("cardio_chart") or self.user_data.get("current_chart") or "1"
        c_level = self.user_data.get("cardio_level") or self.user_data.get("current_level") or "1"
        
        
        report_text.append("") # Spacer before Verdict
        
        # 2. Evaluate STRENGTH (Ex 1-4)
        s_perf_c, s_perf_l = bx.calculate_strength_placement(self.reps_achieved, s_chart)
        s_status = "MAINTAIN"
        s_new_c, s_new_l = s_chart, s_level
        s_score_curr = bx.get_total_score(s_chart, s_level)
        s_score_perf = bx.get_total_score(s_perf_c, s_perf_l)
        
        s_missed = 0
        for i in range(4):
            if self.reps_achieved[i] < self.target_reps_list[i]: s_missed += 1

        if s_missed == 0:
            # Met Current Targets!
            # 5BX Rule: If you meet the target, you advance to the next level.
            # Even if our reps didn't technically qualify for the higher level yet (e.g. exact match), we advance.
            s_next_c, s_next_l = bx.get_next_level(s_chart, s_level)
            s_score_next = bx.get_total_score(s_next_c, s_next_l)
            
            if s_score_perf < s_score_next:
                s_perf_c, s_perf_l = s_next_c, s_next_l
                s_score_perf = s_score_next

            if s_score_perf > s_score_curr:
                s_status = "UP"
                s_new_c, s_new_l = s_perf_c, s_perf_l
                
                # Check for Leap
                s_disp = bx.get_level_display(s_new_l)
                dest = f"C{s_new_c} {s_disp}"
                steps = s_score_perf - s_score_curr
                if steps > 1:
                    report_text.append(f"Strength: 🚀 PROMOTION! (Jumped {steps} Levels to {dest})")
                else:
                    report_text.append(f"Strength: ✅ LEVEL UP! (Now at {dest})")

        else:
            s_status = "MAINTAIN"
            s_new_c, s_new_l = s_chart, s_level
            
            # Check Demotion (Strength)
            streak = 1 + self._get_consecutive_fails("Strength")
            if streak >= 3:
                s_status = "DOWN"
                # Logic: Drop to performance level.
                # Constraint: Don't drop CHART unless we were already at the bottom (Level 1 / D-)
                if s_level != "1" and int(s_perf_c) < int(s_chart):
                    s_perf_c = s_chart
                    s_perf_l = "1"
                elif s_level == "1" and s_perf_l == "1":
                     # Already at bottom, and placement is keeping us at bottom (or lower)
                     l1_targets = bx.get_targets(s_chart, "1")
                     failed_l1 = any(self.reps_achieved[i] < l1_targets[i] for i in range(4))
                     if failed_l1 and int(s_chart) > 1:
                         s_perf_c = str(int(s_chart) - 1)
                         s_perf_l = "12" # A+

                s_new_c, s_new_l = s_perf_c, s_perf_l
                s_disp = bx.get_level_display(s_new_l)
                report_text.append(f"💪 Strength: 📉 DEMOTION: {streak} Consecutive Failures. Dropped to C{s_new_c} {s_disp}")
            else:
                report_text.append(f"💪 Strength: Missed Target (Streak {streak}/3)")

        # 3. Evaluate CARDIO (Ex 5)
        c_perf_c, c_perf_l = bx.calculate_cardio_placement(self.reps_achieved, c_chart)
        c_status = "MAINTAIN" 
        c_new_c, c_new_l = c_chart, c_level
        
        c_missed = 0
        if self.current_cardio_mode and ("Run" in self.current_cardio_mode or "Walk" in self.current_cardio_mode) and "Stationary" not in self.current_cardio_mode:
            # Time Based: Achieved <= Target (LOWER IS BETTER)
            user_time = self.reps_achieved[4]
            target_time = self.target_reps_list[4]
            
            # Report
            mins = user_time // 60
            secs = user_time % 60
            report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): {mins}:{secs:02d} (Target {target_time // 60}:{target_time % 60:02d})")
            
            if user_time <= target_time:
                # PASSED TARGET (Minimum requirement met for current level)
                # Now check absolute placement to allow leapfrogging charts
                c_perf_c, c_perf_l = bx.calculate_cardio_time_placement(user_time, self.current_cardio_mode, c_chart)
                
                # Calculate scores
                score_curr = bx.get_total_score(c_chart, c_level)
                score_perf = bx.get_total_score(c_perf_c, c_perf_l)
                
                # Check Next Level (Incremental) to ensure at least +1 if placement is conservative?
                # Actually placement should find the max level consistent with time.
                # But if placement returns current level (because time equals exactly current target)?
                # We want at least progress.
                # If valid time <= target time, we should advance?
                # Standard 5BX: If you meet the time, you advance to next level.
                c_next_c, c_next_l = bx.get_next_level(c_chart, c_level)
                score_next = bx.get_total_score(c_next_c, c_next_l)
                
                if score_perf < score_next:
                    # Upgrade logic guarantees at least 1 step if entered time met target
                    c_perf_c, c_perf_l = c_next_c, c_next_l
                    score_perf = score_next
                
                if score_perf > score_curr:
                     c_status = "UP"
                     c_new_c, c_new_l = c_perf_c, c_perf_l
                     
                     # Check for Leap
                     c_disp = bx.get_level_display(c_new_l)
                     dest = f"C{c_new_c} {c_disp}"
                     steps = score_perf - score_curr
                     if steps > 1:
                         report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): 🚀 PROMOTION! (Jumped {steps} Levels to {dest})")
                     else:
                         report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): ✅ LEVEL UP! (Now at {dest})")
            else:
                c_missed = 1
                # Check Demotion (Time)
                streak = 1 + self._get_consecutive_fails("Cardio")
                if streak >= 3:
                    c_status = "DOWN"
                    c_perf_c, c_perf_l = bx.calculate_cardio_time_placement(user_time, self.current_cardio_mode, c_chart)
                    
                    # Logic: Drop to performance level.
                    # Constraint: Don't drop CHART unless we were already at the bottom (Level 1 / D-)
                    if c_level != "1" and int(c_perf_c) < int(c_chart):
                        c_perf_c = c_chart
                        c_perf_l = "1"
                    elif c_level == "1":
                        # We are at bottom. Did we fail Level 1 targets?
                        # Note: calculate_placement might return lower chart, implying failure.
                        # But we confirm explicitly against L1 Target to be safe.
                        l1_time = bx.get_time_target(c_chart, "1", self.current_cardio_mode)
                        if user_time > l1_time and int(c_chart) > 1:
                            c_perf_c = str(int(c_chart) - 1)
                            c_perf_l = "12"
                        else:
                            # We failed streaks but passed L1 time (maybe barely?)
                            # Or we are at Chart 1.
                            c_perf_c = c_chart
                            c_perf_l = "1"

                    c_new_c, c_new_l = c_perf_c, c_perf_l
                    c_disp = bx.get_level_display(c_new_l)
                    report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): 📉 DEMOTIION: {streak} Consecutive Failures. Dropped to C{c_new_c} {c_disp}")
                else:
                    report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): Missed Target (Streak {streak}/3)")
        else:
            # Reps Based (Original)
            if self.reps_achieved[4] < self.target_reps_list[4]:
                c_missed += 1
            
            if c_missed == 0:
                c_score_curr = bx.get_total_score(c_chart, c_level)
                c_score_perf = bx.get_total_score(c_perf_c, c_perf_l)
                
                # Check Next Level (Guaranteed Promotion if Target Met)
                c_next_c, c_next_l = bx.get_next_level(c_chart, c_level)
                score_next = bx.get_total_score(c_next_c, c_next_l)
                
                if c_score_perf < score_next:
                    c_perf_c, c_perf_l = c_next_c, c_next_l
                    c_score_perf = score_next
                
                if c_score_perf > c_score_curr:
                    c_status = "UP"
                    c_new_c, c_new_l = c_perf_c, c_perf_l
                     
                    # Check for Leap
                    c_disp = bx.get_level_display(c_new_l)
                    dest = f"C{c_new_c} {c_disp}"
                    steps = c_score_perf - c_score_curr
                    if steps > 1:
                        report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): 🚀 PROMOTION! (Jumped {steps} Levels to {dest})")
                    else:
                        report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): ✅ LEVEL UP! (Now at {dest})")
                else:
                    report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): MAINTAIN (Max Level or Scored Equal)")
                    c_status = "MAINTAIN"
                    c_new_c, c_new_l = c_chart, c_level
                
            else:
                # Check Demotion (Reps) - ONLY IF MISSED
                streak = 1 + self._get_consecutive_fails("Cardio")
                if streak >= 3:
                    c_status = "DOWN"
                    c_perf_c, c_perf_l = bx.calculate_cardio_placement(self.reps_achieved, c_chart)
                    
                    # Logic: Drop to performance level.
                    # Constraint: Don't drop CHART unless we were already at the bottom (Level 1 / D-)
                    if c_level != "1" and int(c_perf_c) < int(c_chart):
                        c_perf_c = c_chart
                        c_perf_l = "1"
                    elif c_level == "1":
                         targets = bx.get_targets(c_chart, "1")
                         if self.reps_achieved[4] < targets[4] and int(c_chart) > 1:
                             c_perf_c = str(int(c_chart) - 1)
                             c_perf_l = "12"
                         else:
                             c_perf_c = c_chart
                             c_perf_l = "1"

                    c_new_c, c_new_l = c_perf_c, c_perf_l
                    c_disp = bx.get_level_display(c_new_l)
                    report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): 📉 DEMOTIION: {streak} Consecutive Failures. Dropped to C{c_new_c} {c_disp}")
                else:
                    report_text.append(f"🏃 Cardio ({self.current_cardio_mode}): Missed Target (Streak {streak}/3)")


        # 4. Final Verdict
        # Format: Strength (LEAPFROG to C2 B+) / Cardio (MAINTAIN (1/3 Strikes))
        
        def get_progression_desc(old_c, old_l, new_c, new_l, status, score_old, score_new, strikes=0):
            if status == "DOWN":
                n_disp = bx.get_level_display(new_l)
                dest = f"C{new_c} {n_disp}"
                return f"DEMOTION to {dest}"
            if status != "UP":
                c_disp = bx.get_level_display(old_l)
                loc = f"C{old_c} {c_disp}"
                if strikes > 0:
                     return f"MAINTAIN {loc} ({strikes}/3 Strikes)"
                return f"MAINTAIN {loc}"
            
            diff = score_new - score_old
            n_disp = bx.get_level_display(new_l)
            dest = f"C{new_c} {n_disp}"
            
            if diff > 1: return f"LEAPFROG to {dest}"
            if str(new_c) != str(old_c): return f"PROMOTION to {dest}"
            return f"LEVEL UP to {dest}"

        # Strength Verdict
        # Calculate current strk for display (if missed)
        s_current_streak = 0
        if s_missed > 0 and s_status == "MAINTAIN":
             # We just missed, so streak is at least 1. 
             # The DB function gets PAST history, so we add 1 for today.
             s_current_streak = 1 + self._get_consecutive_fails("Strength")

        s_algo_verdict = get_progression_desc(s_chart, s_level, s_new_c, s_new_l, s_status, s_score_curr, s_score_perf, s_current_streak)
        
        # Cardio Verdict
        c_current_streak = 0
        if c_missed > 0 and c_status == "MAINTAIN":
             c_current_streak = 1 + self._get_consecutive_fails("Cardio")

        c_algo_verdict = get_progression_desc(c_chart, c_level, c_new_c, c_new_l, c_status, bx.get_total_score(c_chart, c_level), bx.get_total_score(c_new_c, c_new_l), c_current_streak)

        status = f"Strength ({s_algo_verdict}) | Cardio ({c_algo_verdict})"
        color = "#2ecc71" if "UP" in status else "darkorange"
        if "DOWN" in status: color = "#e74c3c"
        
        def get_component_reason(name, status, missed):
            if status == "UP": return f"{name} improved!"
            if status == "DOWN": return f"{name} level reduced to match ability."
            if missed > 0: return f"{name} targets missed."
            return f"{name} maintained."

        s_reason = get_component_reason("Strength", s_status, s_missed)
        c_reason = get_component_reason("Cardio", c_status, c_missed)
        
        if s_reason == c_reason:
            # Combined
            if s_status == "UP": reason = "Great Job! Both Strength and Cardio improved!"
            elif s_status == "DOWN": reason = "Both levels adjusted to match current performance."
            elif s_missed > 0: reason = "Standards not met. Improvement required to advance."
            else: reason = "Maintained status in both areas. Keep pushing!"
        else:
            # Different
            reason = f"{s_reason} {c_reason}"

        # Check for Milestones (Strength & Cardio)
        age = self.calculate_age(self.user_data.get('dob', '2000-01-01'))
        milestones = bx.check_milestones(age, s_chart, s_level, s_new_c, s_new_l, c_chart, c_level, c_new_c, c_new_l)
        
        # MILESTONE POPUP
        if milestones:
            m_top = tk.Toplevel(self)
            m_top.title("ACHIEVEMENT UNLOCKED!")
            m_top.geometry("900x600") # Taller and Wider for text
            m_top.configure(bg="#8e44ad")
            
            tk.Label(m_top, text="🏆 CONGRATULATIONS! 🏆", font=("Arial", 28, "bold"), fg="#f1c40f", bg="#8e44ad").pack(pady=20)
            
            # Keep ref
            self.milestone_images = []
            
            for m_obj in milestones:
                # m_obj is now {'text': str, 'image': path}
                frame = tk.Frame(m_top, bg="#8e44ad")
                frame.pack(pady=10)
                
                img_path = m_obj.get('image')
                if img_path:
                    try:
                        pil_img = Image.open(img_path)
                        pil_img.thumbnail((120, 120))
                        tk_img = ImageTk.PhotoImage(pil_img)
                        self.milestone_images.append(tk_img)
                        tk.Label(frame, image=tk_img, bg="#8e44ad").pack(side=tk.LEFT, padx=20)
                    except: pass
                
                tk.Label(frame, text=m_obj['text'], font=("Arial", 20), fg="white", bg="#8e44ad").pack(side=tk.LEFT)
                
            tk.Button(m_top, text="Woohoo!", command=m_top.destroy, font=("Arial", 16), bg="#f1c40f").pack(pady=30)
            
            # Center Popup
            m_top.update_idletasks()
            w, h = m_top.winfo_width(), m_top.winfo_height()
            x = (m_top.winfo_screenwidth() // 2) - (w // 2)
            y = (m_top.winfo_screenheight() // 2) - (h // 2)
            m_top.geometry(f"+{x}+{y}")
            self.wait_window(m_top)

        # 4. Serialize Detailed Stats for History (EXTENDED V2)
        segment_data = []
        for i, metric in enumerate(self.session_metrics):
            name = metric['name']
            hr_data = metric['hr']
            hrv_data = metric['rmssd']
            
            avg_hr_seg = int(sum(hr_data)/len(hr_data)) if hr_data else 0
            max_hr_seg = max(hr_data) if hr_data else 0
            avg_hrv_seg = int(sum(hrv_data)/len(hrv_data)) if hrv_data else 0
            
            # --- STATUS / INTENSITY CHECK (Restored from v10) ---
            status_txt = "OK"
            if max_hr_seg > (self.true_max_hr * 0.95): status_txt = "INTENSE"
            if avg_hrv_seg < 10 and avg_hrv_seg > 0: status_txt += " / HIGH STRESS"
            if status_txt == "OK": status_txt = "" # Don't save "OK" to keep JSON clean unless needed
            
            segment_data.append({
                "name": name, 
                "avg_hr": avg_hr_seg, 
                "max_hr": max_hr_seg, 
                "hrv": avg_hrv_seg,
                "status": status_txt
            })
        
        # New Struct: { segments: [], badges: [], verdict: "" }
        milestone_data = []
        if milestones:
            for m in milestones:
                milestone_data.append({'text': m['text'], 'image': m.get('image', '')})

        stats_payload = {
            "version": "2.0",
            "segments": segment_data,
            "badges": milestone_data,
            "verdict_reason": reason
        }
        stats_json = json.dumps(stats_payload)

        # Ex 5 Metadata
        ex5_duration = 0
        if self.current_cardio_mode and ("Run" in self.current_cardio_mode or "Walk" in self.current_cardio_mode) and "Stationary" not in self.current_cardio_mode:
             ex5_duration = self.reps_achieved[4]
             self.reps_achieved[4] = 1 if c_missed == 0 else 0
              
        self.db_update_split_level(self.user_id, s_new_c, s_new_l, c_new_c, c_new_l)
        
        self.last_history_id = self.db_add_history(self.user_id, f"{s_chart}/{c_chart}", f"{s_level}/{c_level}", status, avg_session_hr, max_session_hr, end_session_rmssd, self.reps_achieved, stats_json, 
                                                   ex5_type=self.current_cardio_mode, ex5_duration=ex5_duration)

        # --- UI REFACTOR: Session Summary (Read-Only) ---
        self._clear()
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        ttk.Label(frame, text="Workout Complete", style="Header.TLabel").pack()

        # Split UI: Top (Stats), Bottom (Verdict/Badges)
        paned = ttk.PanedWindow(frame, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Section 1: Session Stats (Read-Only)
        f_stats = ttk.Labelframe(paned, text="Session Stats (HR/HRV Breakdown)")
        paned.add(f_stats, weight=2)
        
        scr_s = ttk.Scrollbar(f_stats)
        scr_s.pack(side=tk.RIGHT, fill=tk.Y)
        txt_s = tk.Text(f_stats, height=8, font=("Courier", 10), bg="#2c3e50", fg="white", yscrollcommand=scr_s.set)
        txt_s.pack(fill=tk.BOTH, expand=True)
        self.session_stats_text = "\n".join(report_text)
        txt_s.insert(tk.END, self.session_stats_text)
        txt_s.config(state=tk.DISABLED) 
        scr_s.config(command=txt_s.yview)

        # Section 2: Verdict & Badges (Bottom Frame)
        f_bottom = ttk.Frame(paned) # Use frame inside paned
        paned.add(f_bottom, weight=1)
        
        # Verdict Frame
        f_verdict = ttk.Labelframe(f_bottom, text="Session Verdict")
        f_verdict.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))
        
        s_color = "#2ecc71" if "UP" in s_status else "darkorange"
        if "DOWN" in s_status: s_color = "#e74c3c"
        
        c_color = "#2ecc71" if "UP" in c_status else "darkorange"
        if "DOWN" in c_status: c_color = "#e74c3c"

        # disp_status = status.replace(" | ", "\n").replace(" / ", "\n")
        # ttk.Label(f_verdict, text=disp_status, font=("Arial", 14, "bold"), foreground=color, justify=tk.CENTER).pack(pady=5)
        
        ttk.Label(f_verdict, text=f"Strength ({s_algo_verdict})", font=("Arial", 12, "bold"), foreground=s_color, justify=tk.CENTER).pack(pady=(5,0))
        ttk.Label(f_verdict, text=f"Cardio ({c_algo_verdict})", font=("Arial", 12, "bold"), foreground=c_color, justify=tk.CENTER).pack(pady=(0,5))
        ttk.Label(f_verdict, text=reason, font=("Arial", 12), wraplength=400).pack(pady=5)
        
        # Badges Frame
        if milestones:
            f_badges = ttk.Labelframe(f_bottom, text="Badges Earned")
            f_badges.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
            
            if not hasattr(self, 'badge_imgs'): self.badge_imgs = []
            
            for m_obj in milestones:
                b_row = tk.Frame(f_badges)
                b_row.pack(anchor="w", pady=2)
                
                # Image
                img_path = m_obj.get('image')
                if img_path:
                    try:
                        pil_img = Image.open(img_path)
                        pil_img.thumbnail((30, 30))
                        tk_img = ImageTk.PhotoImage(pil_img)
                        self.badge_imgs.append(tk_img)
                        tk.Label(b_row, image=tk_img).pack(side=tk.LEFT, padx=5)
                    except: pass
                
                tk.Label(b_row, text=m_obj['text'], font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        
        # Save Button (Just Exit now)
        ttk.Button(frame, text="Finish & Close", command=self.show_dashboard).pack(pady=5)

    def save_notes_and_exit(self):
        # Allow pass through
        self.show_profile_linker()

    # --- HISTORY GRAPH LOGIC ---
    # --- HISTORY POPUP (STRICT ID FILTERING) ---
    def history_view_details(self):
        selected = self.hist_tree.selection()
        if not selected: return
        
        db_id = int(selected[0])
        conn = sqlite3.connect(USER_DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM history WHERE id=?", (db_id,))
        record = c.fetchone()
        conn.close()
        
        if not record: return
        
        stats_json = record['segment_stats'] if 'segment_stats' in record.keys() else None
        
        top = tk.Toplevel(self)
        top.title(f"Details: {record['timestamp']}")
        top.geometry("750x700") # Wider to prevent wrapping
        top.configure(bg="#2c3e50")
        
        # We don't need the header label repeated if we have the text
        # tk.Label(top, text="Session Details", font=("Helvetica", 16, "bold"), bg="#2c3e50", fg="white").pack(pady=5)
        
        txt = tk.Text(top, height=30, font=("Courier", 11), bg="#34495e", fg="white", padx=15, pady=15)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        report = []
        
        # A. PARSE JSON DATA
        segments = []
        badges = []
        verdict_reason = ""
        
        if stats_json:
            try:
                data = json.loads(stats_json)
                if isinstance(data, dict):
                    # V2
                    segments = data.get('segments', [])
                    badges = data.get('badges', [])
                    verdict_reason = data.get('verdict_reason', "")
                else:
                    # V1 (List)
                    segments = data
            except:
                report.append("[Error parsing stats JSON]")

        # B. RENDER SEGMENTS (with Reps)
        row_keys = record.keys()
        
        # Map numeric index to DB columns for Reps
        rep_cols = ['ex1', 'ex2', 'ex3', 'ex4', 'ex5'] # We might need logic for Ex 5
        
        if segments:
            for i, item in enumerate(segments):
                name = item['name']
                
                # --- EX 5 NAME LOGIC ---
                if i == 4:
                     prefix = "CARDIO - EXERCISE 5"
                     raw_c = str(record['chart'])
                     c_chart = raw_c.split('/')[1] if '/' in raw_c else raw_c
                     try:
                         details_db = bx.get_exercise_detail(c_chart, 4)
                         final_variant = details_db['name']
                     except:
                         final_variant = name 
                     
                     if 'ex5_type' in row_keys:
                         e_type = record['ex5_type']
                         if e_type and e_type.lower() != 'standard':
                             dur = record['ex5_duration'] if 'ex5_duration' in row_keys else 0
                             m = dur // 60
                             s = dur % 60
                             final_variant = f"{e_type} - {m}:{s:02d}"
                     name = f"{prefix} ({final_variant})"
                # -----------------------

                # --- REPS LOGIC ---
                reps_line = ""
                
                # Lazy Load Targets
                if 'targets_loaded' not in locals():
                    try:
                        raw_c, raw_l = str(record['chart']), str(record['level'])
                        s_c, c_c = raw_c, raw_c
                        s_l, c_l = raw_l, raw_l
                        if "/" in raw_c: s_c, c_c = raw_c.split("/")
                        if "/" in raw_l: s_l, c_l = raw_l.split("/")
                        
                        s_targets = bx.get_targets(s_c, s_l)
                        c_targets = bx.get_targets(c_c, c_l)
                        targets_loaded = True
                    except:
                        s_targets = [0]*5
                        c_targets = [0]*5
                        targets_loaded = True
                
                if i < 4:
                    # Ex 1-4: Show Reps/Target + Standard Badge Logic
                    val = record[rep_cols[i]] if rep_cols[i] in row_keys else 0
                    if val > 0:
                        t = s_targets[i] if s_targets else 0
                        status_s = " (Missed)"
                        if t > 0:
                            diff = val - t
                            if diff >= 0:
                                status_s = " (🎯 TARGET HIT)"
                                if t > 10:
                                    if diff >= t * 0.2: status_s = " (🔥 UNSTOPPABLE)"
                                    elif diff >= t * 0.1: status_s = " (🚀 SMASHED IT)"
                        
                        reps_line = f"   REPS: {val}/{t}{status_s}"
                        
                # Ex 5: usually implied by title (Time) or Stationary (Reps implied?). 
                # Ex 5: Cardio
                # Ex 5: Cardio
                if i == 4:
                     e_type = record['ex5_type'] if 'ex5_type' in row_keys else "Standard"
                     if not e_type: e_type = "Standard"
                     e_type_lower = e_type.lower()
                     
                     if "run" in e_type_lower or "walk" in e_type_lower:
                         # --- TIME LOGIC (Run/Walk) ---
                         val = record['ex5_duration'] if 'ex5_duration' in row_keys else 0
                         if val == 0 and 'ex5' in row_keys: val = record['ex5'] # Fallback? No, ex5 is boolean. 0 is safer.
                         mode = "Run" if "run" in e_type_lower else "Walk"
                         
                         # Fetch Target
                         t_sec = bx.get_time_target(c_c, c_l, mode)
                         
                         # Utils
                         def fmt_t(s): return f"{s//60}:{s%60:02d}"
                         
                         # Logic: Time - Lower is Better
                         diff = t_sec - val
                         status_s = " (Missed)" # Default if val > t_sec (slower)
                         
                         if val > 0 and diff >= 0: # Done <= Target (Faster or Equal) AND Valid Data
                             status_s = " (🎯 TARGET HIT)"
                             if diff >= 60: status_s = " (🔥 UNSTOPPABLE)"
                             elif diff >= 10: status_s = " (🚀 SMASHED IT)"
                         
                         # Always show if we have data or target
                         if val > 0 or t_sec > 0:
                             reps_line = f"   Time: {fmt_t(val)}/{fmt_t(t_sec)}{status_s}"
                             
                     else:
                         # --- REPS LOGIC (Stationary/Standard) ---
                         val = record['ex5'] if 'ex5' in row_keys else 0
                         t = c_targets[4] if c_targets else 0
                         status_s = " (Missed)"
                         
                         if t > 0:
                             diff = val - t
                             if diff >= 0:
                                 status_s = " (🎯 TARGET HIT)"
                                 if t > 10:
                                     if diff >= t * 0.2: status_s = " (🔥 UNSTOPPABLE)"
                                     elif diff >= t * 0.1: status_s = " (🚀 SMASHED IT)"
                         
                         # Show if value exists OR target exists (so 0/400 (Missed) shows)
                         if val > 0 or t > 0:
                             reps_line = f"   REPS: {val}/{t}{status_s}"
                # ------------------

                hrv_str = f"{item.get('hrv', 0)} ms"
                if "Back Arch" in name: hrv_str = "(Artifact Ignored)"
                
                report.append(f"• {name.upper()}")
                if reps_line: report.append(reps_line)
                
                avg = item.get('avg_hr', 0)
                mx = item.get('max_hr', 0)
                report.append(f"   HR:  Avg {avg} | Max {mx}")
                report.append(f"   HRV: {hrv_str}")
                
                # --- STATUS DISPLAY ---
                status_txt = item.get('status', '')
                if status_txt and status_txt != "OK":
                     report.append(f"   -> ⚠️ {status_txt}")
                     
                report.append("")
        else:
            report.append("(No detailed physiological stats available)")
            report.append("")

        # C. SESSION NOTES - REMOVED PER USER REQUEST
        
        # D. VERDICT (Formatted)
        v_str = record['verdict']
        # Handle separator (Pipe | or Slash /)
        # We replace " / Cardio" with " | Cardio" to protect internal fractions like "1/3"
        v_clean = v_str.replace(" / Cardio", " | Cardio")
        
        if "Strength" in v_clean and "Cardio" in v_clean and "|" in v_clean:
            parts = v_clean.split("|")
            s_part = parts[0].strip().replace("Strength (", "Strength - ").replace(")", "")
            c_part = parts[1].strip().replace("Cardio (", "Cardio - ").replace(")", "")
            final_v = f"VERDICT:\n{s_part}\n{c_part}"
        else:
            final_v = f"VERDICT:\n{v_str}"
        
        report.append(final_v)
        if verdict_reason:
            # Maybe show reason below verdict? 
            # User request didn't explicitly ask for the long reason text in the example, 
            # but it's valuable. I'll add it indented or just below.
            # User example: Just showed Verdict. 
            pass # Keep it clean as per request.

        report.append("")

        # E. BADGES
        if badges:
            report.append("BADGES EARNED:")
            for b in badges:
                report.append(f"🏆 {b['text']}")
            report.append("")

            report.append("")
        
        # Configure Tags
        txt.tag_config("demote", foreground="#e74c3c", font=("Courier New", 12, "bold"))
        txt.tag_config("header", font=("Courier New", 12, "bold"))
        
        # Insert line by line to apply tags
        for line in report:
            tags = tuple()
            if "DEMOTION" in line:
                tags = ("demote",)
            elif "VERDICT:" in line:
                tags = ("header",)
            
            txt.insert(tk.END, line + "\n", tags)
        
        btn = tk.Button(top, text="Close", command=top.destroy)
        btn.pack(pady=10)
    
    def show_exercise_history(self, target_chart_id, target_idx, title_name):
        """
        Shows a graph of progress for a specific exercise name.
        target_chart_id: The Chart ID (e.g. "1") to strictly filter by.
        target_idx: 0-4 (The index in the routine) OR 5=Run, 6=Walk.
        title_name: Display name for the window title.
        """
        records = self.db_get_history(self.user_id)
        
        dates = []
        reps = []
        hrs = []
        hrvs = []
        
        for r in records:
            # 1. Resolve Effective Chart for this Record
            raw_chart = str(r['chart'])
            eff_chart = raw_chart
            
            if "/" in raw_chart:
                parts = raw_chart.split("/")
                if len(parts) >= 2:
                    if target_idx < 4: eff_chart = parts[0]
                    else: eff_chart = parts[1]
            
            # 2. STRICT ID MATCH
            if str(eff_chart) != str(target_chart_id):
                 continue
                 
            # 3. Parse Value
            val = 0
            
            # Reps list
            reps_list = [0]*5
            if r['ex1']: reps_list = [r['ex1'], r['ex2'], r['ex3'], r['ex4'], r['ex5']]
            
            if target_idx < 5:
                # Use index directly from the DB row data we just extracted
                val = reps_list[target_idx]
            else:
                # Handle Ex 6 (Run) / 7 (Walk)
                keys = r.keys()
                e_type = r['ex5_type'] if 'ex5_type' in keys else ""
                e_dur = r['ex5_duration'] if 'ex5_duration' in keys else 0
                if not e_type: e_type = ""
                if not e_dur: e_dur = 0
                
                if target_idx == 5: # Run
                    if "Run" in e_type: val = e_dur
                elif target_idx == 6: # Walk
                    if "Walk" in e_type: val = e_dur
            
            r_hr = r['avg_hr']
            r_hrv = 0
            
            # 4. Parse JSON stats if available
            stats_json = r.get('segment_stats')
            if stats_json:
                try:
                    data = json.loads(stats_json)
                    # Handle V2 Struct
                    if isinstance(data, dict):
                         data = data.get('segments', [])

                    # Use Index Math
                    t_stat = target_idx
                    if target_idx >= 5: t_stat = 4
                    
                    if t_stat < len(data):
                         item = data[t_stat]
                         r_hr = item.get('max_hr', 0)
                         r_hrv = item.get('hrv', 0)
                except: pass
            
            if val > 0:
                short_date = r['timestamp'].split(" ")[0][5:] # MM-DD
                dates.append(short_date)
                reps.append(val)
                hrs.append(r_hr)
                hrvs.append(r_hrv)
                
            # LIMIT TO 20
            if len(dates) >= 20: break
            
        if not dates:
            messagebox.showinfo("History", f"No history data found for {title_name}")
            return
            
        # Reverse for plot (Oldest -> Newest)
        dates = dates[::-1]
        reps = reps[::-1]
        hrs = hrs[::-1]
        hrvs = hrvs[::-1]

        # -- PLOT --
        top = tk.Toplevel(self)
        
        # Detailed Title
        full_title = f"Chart {target_chart_id} Exercise {target_idx + 1}: {title_name}"
        top.title(f"Progress: {full_title}")
        
        # 66% Screen Size
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        w = int(sw * 0.66)
        h = int(sh * 0.66)
        x = (sw - w) // 2
        y = (sh - h) // 2
        top.geometry(f"{w}x{h}+{x}+{y}")
        
        top.configure(bg="#2c3e50")
        
        fig = Figure(figsize=(8, 6), dpi=100, facecolor="#2c3e50")
        fig.subplots_adjust(hspace=0.4) # spacing
        
        # Subplot 1: Reps
        ax1 = fig.add_subplot(211)
        ax1.set_facecolor("#34495e")
        ax1.plot(dates, reps, marker='o', color='#2ecc71', linewidth=2, label="Score")
        
        y_label = "Reps Count"
        if target_idx >= 5: y_label = "Time (Seconds)"
        
        ax1.set_title(f"{y_label}: {full_title}", color="white")
        ax1.tick_params(colors='white', rotation=45)
        ax1.xaxis.set_major_locator(MaxNLocator(nbins=8)) # Fix Date Readability
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        
        # Subplot 2: Bio
        ax2 = fig.add_subplot(212)
        ax2.set_facecolor("#34495e")
        ax2.plot(dates, hrs, marker='s', color='#ff5555', linestyle='--', label="Avg HR")
        
        # Only plot HRV if we valid data
        if any(h > 0 for h in hrvs):
            ax2_2 = ax2.twinx()
            ax2_2.plot(dates, hrvs, marker='^', color='#f1c40f', linestyle=':', label="HRV (ms)")
            ax2_2.tick_params(colors='#f1c40f')
            ax2_2.spines['right'].set_color('#f1c40f')
            
        ax2.set_title("Physiological Cost", color="white")
        ax2.tick_params(colors='white', rotation=45)
        ax2.xaxis.set_major_locator(MaxNLocator(nbins=8))
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper left')

        canvas = FigureCanvasTkAgg(fig, master=top)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def show_exercise_info_popup(self, idx):
        # Determine variant if Ex 5
        variant = "Standard"
        if idx == 4:
            variant = self.current_cardio_mode
            
        c_chart = str(self.user_data.get('cardio_chart') or "1")
        s_chart = str(self.user_data.get('strength_chart') or "1")
        
        target_chart = s_chart if idx < 4 else c_chart
        
        d = bx.get_exercise_detail(target_chart, idx, variant)
        
        top = tk.Toplevel(self)
        top.title(d['name'])
        top.geometry("400x500")
        
        try:
             # Load Image
             if d['img']:
                 path = os.path.join(IMG_DIR, d['img'])
                 if os.path.exists(path):
                     load = Image.open(path)
                     load = load.resize((350, 250), Image.Resampling.LANCZOS)
                     render = ImageTk.PhotoImage(load)
                     img = tk.Label(top, image=render)
                     img.image = render
                     img.pack(pady=10)
        except: pass
        
        formatted_desc = d['desc'].replace(". ", ".\n\n")
        lbl = tk.Label(top, text=formatted_desc, wraplength=350, justify="left", font=("Arial", 11))
        lbl.pack(pady=10, padx=10)
        
        tk.Button(top, text="Close", command=top.destroy).pack(pady=10)

    def _clear(self):
        for widget in self.winfo_children():
            if isinstance(widget, tk.Toplevel): continue
            widget.destroy()
    def destroy(self):
        self.workout_active = False; self.dashboard_active = False; self.linker_active = False
        if self.sensor:
            try: self.sensor.stop()
            except: pass
        super().destroy()

    def edit_user_progress(self):
        """Allow manual override of Strength and Cardio levels."""
        top = tk.Toplevel(self)
        top.title("Edit Progress Manually")
        top.geometry("500x350")
        top.transient(self)
        
        # Load Current
        u = self.user_data
        s_c = u.get("strength_chart") or u.get("current_chart") or "1"
        s_l = u.get("strength_level") or u.get("current_level") or "1"
        c_c = u.get("cardio_chart") or u.get("current_chart") or "1"
        c_l = u.get("cardio_level") or u.get("current_level") or "1"
        
        tk.Label(top, text="Override Progress Levels", font=("Arial", 12, "bold")).pack(pady=10)
        
        frame = ttk.Frame(top)
        frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        # Helper Lists
        charts = [str(i) for i in range(1, 7)]
        # levels with display: "D-" (1) ... "A+" (12)
        # We store just the display strings. Index+1 is the level ID.
        level_displays = []
        for i in range(1, 13):
            level_displays.append(bx.get_level_display(str(i)))
        
        # Reverse for Display (A+ at top)
        level_values_reversed = list(reversed(level_displays))
        
        # Initial Values (Display Only)
        s_l_disp = bx.get_level_display(s_l)
        c_l_disp = bx.get_level_display(c_l)
        
        # Strength Box
        sf = tk.LabelFrame(frame, text="💪 Strength", padx=10, pady=10)
        sf.grid(row=0, column=0, padx=5, sticky="nsew")
        
        tk.Label(sf, text="Chart:").grid(row=0, column=0, sticky="w")
        s_c_var = tk.StringVar(value=s_c)
        ttk.Combobox(sf, textvariable=s_c_var, values=charts, width=5).grid(row=0, column=1, pady=5)
        
        tk.Label(sf, text="Level:").grid(row=1, column=0, sticky="w")
        s_l_var = tk.StringVar(value=s_l_disp)
        ttk.Combobox(sf, textvariable=s_l_var, values=level_values_reversed, width=12).grid(row=1, column=1, pady=5)
        
        # Cardio Box
        cf = tk.LabelFrame(frame, text="🏃 Cardio", padx=10, pady=10)
        cf.grid(row=0, column=1, padx=5, sticky="nsew")
        
        tk.Label(cf, text="Chart:").grid(row=0, column=0, sticky="w")
        c_c_var = tk.StringVar(value=c_c)
        ttk.Combobox(cf, textvariable=c_c_var, values=charts, width=5).grid(row=0, column=1, pady=5)
        
        tk.Label(cf, text="Level:").grid(row=1, column=0, sticky="w")
        c_l_var = tk.StringVar(value=c_l_disp)
        ttk.Combobox(cf, textvariable=c_l_var, values=level_values_reversed, width=12).grid(row=1, column=1, pady=5)
        
        def save():
            sc = s_c_var.get()
            cc = c_c_var.get()
            
            # Parse Level: "A+" -> "12"
            # Find index in STANDARD level_displays (not reversed)
            sl_raw = "1"
            if s_l_var.get() in level_displays:
                sl_raw = str(level_displays.index(s_l_var.get()) + 1)
                
            cl_raw = "1"
            if c_l_var.get() in level_displays:
                 cl_raw = str(level_displays.index(c_l_var.get()) + 1)
            
            # Update DB
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            c.execute("""
                UPDATE users 
                SET strength_chart=?, strength_level=?, 
                    cardio_chart=?, cardio_level=?,
                    current_chart=?, current_level=?
                WHERE name=?
            """, (sc, sl_raw, cc, cl_raw, sc, sl_raw, self.username))
            conn.commit()
            conn.close()
            
            # Log this manual change in history
            s_disp = bx.get_level_display(sl_raw)
            c_disp = bx.get_level_display(cl_raw)
            verdict = f"MANUAL SET: S(C{sc} {s_disp}) | C(C{cc} {c_disp})"
            
            # Construct DB fields (handle split)
            db_chart = sc
            if sc != cc: db_chart = f"{sc}/{cc}"
            
            db_level = sl_raw
            if sl_raw != cl_raw: db_level = f"{sl_raw}/{cl_raw}"
            
            self.db_add_history(self.user_id, db_chart, db_level, verdict, 0, 0, 0, reps_list=[0]*5)
            
            # Update Live Obj
            self.user_data["strength_chart"] = sc
            self.user_data["strength_level"] = sl_raw
            top.destroy()
            
        tk.Button(top, text="Save Changes", bg="#2ecc71", fg="white", font=("Arial", 11, "bold"), command=save).pack(pady=20)

    # --- DOCUMENTATION VIEWER ---
    def show_manual_popup(self):
        root = tk.Toplevel(self)
        root.title("5BX Manual & Rules")
        root.geometry("1400x900") # Widened to support full table width
        root.configure(bg="#2c3e50")
        
        # Sidebar
        sidebar = tk.Frame(root, bg="#34495e", width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        
        # Content Area
        content_frame = tk.Frame(root, bg="white")
        content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Text Widget
        import tkinter.scrolledtext as st
        self.doc_text = st.ScrolledText(content_frame, wrap=tk.WORD, padx=20, pady=20, font=("Georgia", 11))
        self.doc_text.pack(fill=tk.BOTH, expand=True)
        
        # Tags - Using Clean Typography
        self.doc_text.tag_config("h1", font=("Helvetica", 24, "bold"), spacing3=10, foreground="#2c3e50")
        self.doc_text.tag_config("h2", font=("Helvetica", 18, "bold"), spacing3=10, foreground="#e67e22")
        self.doc_text.tag_config("h3", font=("Helvetica", 14, "bold"), spacing3=5, foreground="#2980b9")
        self.doc_text.tag_config("bold", font=("Georgia", 11, "bold"))
        self.doc_text.tag_config("italic", font=("Georgia", 11, "italic"))
        self.doc_text.tag_config("quote", font=("Georgia", 11, "italic"), lmargin1=20, lmargin2=20, foreground="#7f8c8d")
        
        # Table: Courier font + Tab Stops for alignment
        # Table: Fixed Font + Wide Tab Stops
        # Headers like "Ex 1 (Toe Touch)" need >3cm space
        # Stops: 2c, 6c, 10c, 14c, 18c, 22c
        self.doc_text.tag_config("table", font="TkFixedFont", background="#ecf0f1", 
                                 tabs=("2c", "6c", "10c", "14c", "18c", "22c"))
        
        self.doc_images = [] # Keep references
        
        def load_doc(filename):
            path = os.path.join(os.getcwd(), filename)
            if not os.path.exists(path):
                 self.doc_text.config(state=tk.NORMAL)
                 self.doc_text.delete("1.0", tk.END)
                 self.doc_text.insert(tk.END, f"File not found: {filename}")
                 self.doc_text.config(state=tk.DISABLED)
                 return
            
            with open(path, 'r') as f:
                content = f.read()
            self._render_markdown(content)
            
        # Buttons
        tk.Label(sidebar, text="📚 Documents", bg="#34495e", fg="#bdc3c7", font=("Arial", 10)).pack(pady=10)
        
        tk.Button(sidebar, text="Introduction", bg="#2980b9", fg="white", font=("Arial", 11, "bold"),
                  command=lambda: load_doc("5bx_introduction.md")).pack(fill=tk.X, padx=10, pady=5)
                  
        tk.Button(sidebar, text="Progression Rules", bg="#8e44ad", fg="white", font=("Arial", 11, "bold"),
                  command=lambda: load_doc("progression_rules.md")).pack(fill=tk.X, padx=10, pady=5)
                  
        tk.Button(sidebar, text="Calibration Guide", bg="#e67e22", fg="white", font=("Arial", 11, "bold"),
                  command=lambda: load_doc("calibration_guide.md")).pack(fill=tk.X, padx=10, pady=5)
                  
        tk.Button(sidebar, text="Close", bg="#c0392b", fg="white", command=root.destroy).pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=20)
        
        # Default Load
        load_doc("5bx_introduction.md")

    def _render_markdown(self, content):
        self.doc_text.config(state=tk.NORMAL)
        self.doc_text.delete("1.0", tk.END)
        self.doc_images = []
        self.table_buffer = [] # Buffer for contiguous table lines
        
        lines = content.split('\n')
        
        def flush_table_buffer():
            if not self.table_buffer: return
            
            # Create a Frame for the table
            table_frame = tk.Frame(self.doc_text, bg="#bdc3c7", padx=1, pady=1) # Border effect
            
            # Parse Data
            raw_rows = []
            for l in self.table_buffer:
                # | Cell | Cell | -> ['Cell', 'Cell']
                cells = [c.strip() for c in l.strip().split('|')]
                if len(cells) > 0 and cells[0] == '': cells.pop(0)
                if len(cells) > 0 and cells[-1] == '': cells.pop(-1)
                raw_rows.append(cells)
            
            # Render
            for r_idx, row_data in enumerate(raw_rows):
                # Check for Divider Row (e.g. ---)
                if all(c.replace('-', '').replace(':', '').strip() == '' for c in row_data):
                    continue
                    
                is_header = (r_idx == 0)
                bg_color = "#34495e" if is_header else ("#ecf0f1" if r_idx % 2 == 0 else "#ffffff")
                fg_color = "white" if is_header else "black"
                font_style = ("Arial", 11, "bold") if is_header else ("Arial", 10)
                
                for c_idx, cell_text in enumerate(row_data):
                    clean_text = cell_text.replace("**", "")
                    lbl = tk.Label(table_frame, text=clean_text, font=font_style, 
                                   bg=bg_color, fg=fg_color, padx=10, pady=5, borderwidth=1, relief="solid")
                    lbl.grid(row=r_idx, column=c_idx, sticky="nsew")
            
            # Embed the frame
            self.doc_text.window_create(tk.END, window=table_frame)
            self.doc_text.insert(tk.END, "\n")
            self.table_buffer = []

        for line in lines:
            stripped = line.strip()
            
            # Check for Table Line
            if stripped.startswith("|"):
                self.table_buffer.append(stripped)
                continue
            else:
                # Not a table line -> Flush header if exists
                flush_table_buffer()
                
            # Headers
            if line.startswith("# "):
                self.doc_text.insert(tk.END, line[2:] + "\n", "h1")
            elif line.startswith("## "):
                self.doc_text.insert(tk.END, line[3:] + "\n", "h2")
            elif line.startswith("### "):
                self.doc_text.insert(tk.END, line[4:] + "\n", "h3")
            
            # Blockquote
            elif line.startswith("> "):
                clean = line[2:].replace("**", "") # Strip bold for quote
                self.doc_text.insert(tk.END, clean + "\n", "quote")
                
            # Images: ![alt](path)
            elif stripped.startswith("!["):
                try:
                    s = line.find("(") + 1
                    e = line.find(")")
                    path = line[s:e]
                    full_path = os.path.join(os.getcwd(), path)
                    
                    if os.path.exists(full_path):
                        img = Image.open(full_path)
                        # Resize to fit
                        base_width = 500
                        w_percent = (base_width / float(img.size[0]))
                        h_size = int((float(img.size[1]) * float(w_percent)))
                        img = img.resize((base_width, h_size), Image.Resampling.LANCZOS)
                        
                        photo = ImageTk.PhotoImage(img)
                        self.doc_images.append(photo)
                        self.doc_text.image_create(tk.END, image=photo)
                        self.doc_text.insert(tk.END, "\n")
                except:
                    self.doc_text.insert(tk.END, "[Image Load Failed]\n")
            
            # Dividers (Horizontal Rules)
            elif line.startswith("---"):
                 self.doc_text.insert(tk.END, "_"*60 + "\n", "quote") # Lighter divider
                
            # Normal Text (Partial Bold Parsing)
            else:
                # Poor man's bold parser
                if "**" in line:
                    parts = line.split("**")
                    for i, part in enumerate(parts):
                        tag = "bold" if i % 2 == 1 else ""
                        self.doc_text.insert(tk.END, part, tag)
                else:
                    self.doc_text.insert(tk.END, line)
                self.doc_text.insert(tk.END, "\n")
        
        # Final flush
        flush_table_buffer()
        self.doc_text.config(state=tk.DISABLED)

# --- CALIBRATION WIZARD ---
class CalibrationWizard(tk.Toplevel):
    def __init__(self, parent, initial_user_data=None):
        super().__init__(parent)
        self.parent = parent
        self.title("Biofeedback Calibration Wizard")
        self.geometry("600x800")
        self.configure(bg="#2c3e50")
        
        # Data State
        self.sensor = None
        self.user_name = ""
        self.user_dob = ""
        self.user_age = 30
        self.current_phase = ""
        self.is_recording = False
        self.dashboard_active = False 

        self.phase_data_hr = []
        self.phase_data_rmssd = []

        self.results = {
            "rest": {}, "stress": {}, "exertion": {}, "recovery": {}
        }
        
        # Start Sensor Logic
        self.dashboard_active = True 
        self.init_sensor_loop()

        # UI Setup - Jump straight to Phase 1
        if initial_user_data:
            self.user_name = initial_user_data.get('name', 'Unknown')
            self.user_dob = initial_user_data.get('dob', '')
            self.user_age = initial_user_data.get('age', 30)
            
            # Start Wizard
            self.show_instruction("REST")
            self.update_dashboard_loop()
        else:
             # Fallback (Should not happen in correct usage)
             tk.Label(self, text="Error: No User Profile Data Loaded", fg="red").pack(pady=50)
            
    def init_sensor_loop(self):
        # The parent app has supposedly stopped its sensor.
        # We try to create a new one.
        if self.sensor and self.sensor.status == "Active": return

        try:
            if self.sensor: 
                try: self.sensor.stop() 
                except: pass
                
            self.sensor = AntHrvSensor()
            self.sensor.start()
            self.after(500, self.check_startup_status)
        except Exception as e:
            if hasattr(self, 'lbl_device_dash'):
                self.lbl_device_dash.config(text=f"📡 Searching... {e}", foreground="#e67e22")
            self.after(2000, self.init_sensor_loop)

    def check_startup_status(self):
        if not self.sensor: return
        data = self.sensor.get_data()
        status = data.get('status', 'Error')
        if status == "Active" or status == "Initializing":
             self.update_dashboard_loop()
        else:
             if hasattr(self, 'lbl_device_dash'):
                self.lbl_device_dash.config(text=f"📡 {status}...", foreground="#e67e22")
             self.after(2000, self.init_sensor_loop)

    # --- SOUND ENGINE ---
    def play_beep(self):
        self.parent.bell() 

    # --- AGE CALCULATION ---
    def calculate_age(self, dob_str):
        try:
            birth_date = datetime.datetime.strptime(dob_str, "%Y-%m-%d").date()
            today = datetime.date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except ValueError:
            return None





    def show_instruction(self, phase):
        self.current_phase = phase
        self.is_recording = False
        self.clear_screen()

        texts = {
            "REST": "PHASE 1: RESTING BASELINE\n\nSit comfortably. Close your eyes.\nBreathe normally.\nDo not talk or move.",
            "STRESS": "PHASE 2: NECKER CUBE TEST\n\nFocus on the cube below.\nTry to HOLD it in one perspective.\nCount silently each time it flips involuntarily.",
            "EXERTION": "PHASE 3: PHYSICAL EXERTION\n\nStand up.\nDo Jumping Jacks or High Knees vigorously.\nGet your heart rate up!",
            "RECOVERY": "PHASE 4: VAGAL RECOVERY\n\nSit down immediately.\nClose your eyes.\nInhale deeply (4s), Exhale slowly (6s)."
        }

        frame = ttk.Frame(self)
        frame.pack(expand=True, fill='both', padx=20)

        ttk.Label(frame, text=texts[phase], justify="center", font=("Arial", 14)).pack(pady=10)

        self.lbl_device_dash = ttk.Label(frame, text="📡 Searching...", foreground="#95a5a6", font=("Arial", 10))
        self.lbl_device_dash.pack(pady=5)

        if phase == "STRESS":
            self.draw_necker_cube(frame)

        self.btn_next = ttk.Button(frame, text="BEGIN PHASE", command=self.run_phase_timer)
        self.btn_next.pack(pady=20)

        self.lbl_live = ttk.Label(frame, text="Waiting for signal...", foreground="yellow")
        self.lbl_live.pack()
        self.update_live_preview()

    def update_dashboard_loop(self):
        if not self.dashboard_active: return
        if self.sensor:
            data = self.sensor.get_data()
            bpm = data.get('bpm', 0)
            status = data.get('status', 'Initializing')
            
            if status == "Active" or bpm > 0:
                txt = f"✅ Active | Live HR: {bpm}"
                if hasattr(self, 'lbl_device_dash'): self.lbl_device_dash.config(text=txt, foreground="#2ecc71")
            else:
                if hasattr(self, 'lbl_device_dash'): self.lbl_device_dash.config(text=f"📡 {status}...", foreground="#e67e22")
        self.after(1000, self.update_dashboard_loop)

    def draw_necker_cube(self, parent):
        c = tk.Canvas(parent, width=200, height=200, bg="#2c3e50", highlightthickness=0)
        c.pack(pady=5)
        c.create_rectangle(50, 50, 150, 150, outline="cyan", width=3)
        c.create_rectangle(80, 20, 180, 120, outline="cyan", width=3)
        c.create_line(50, 50, 80, 20, fill="cyan", width=3)
        c.create_line(150, 50, 180, 20, fill="cyan", width=3)
        c.create_line(50, 150, 80, 120, fill="cyan", width=3)
        c.create_line(150, 150, 180, 120, fill="cyan", width=3)

    def update_live_preview(self):
        if self.is_recording or self.current_phase == "FINISHED": return
        if self.sensor:
            data = self.sensor.get_data()
            self.lbl_live.config(text=f"♥ {data.get('bpm',0)} bpm  |  ⚡ {data.get('rmssd',0):.3f} ms")
        self.after(1000, self.update_live_preview)

    def run_phase_timer(self):
        self.is_recording = True
        self.btn_next.config(state="disabled")
        self.phase_data_hr = []
        self.phase_data_rmssd = []
        self.remaining_time = PHASE_DURATIONS[self.current_phase]
        self.record_loop()

    def record_loop(self):
        if self.remaining_time > 0:
            if self.sensor:
                data = self.sensor.get_data()
                if data.get('bpm',0) > 0:
                    self.phase_data_hr.append(data['bpm'])
                    self.phase_data_rmssd.append(data.get('rmssd',0))
                self.lbl_live.config(text=f"RECORDING... {self.remaining_time}s\n♥ {data.get('bpm',0)} | ⚡ {data.get('rmssd',0):.3f}")
            self.remaining_time -= 1
            self.after(1000, self.record_loop)
        else:
            self.finish_phase()

    def finish_phase(self):
        self.play_beep()
        self.is_recording = False
        
        if len(self.phase_data_hr) > 0:
            avg_hr = statistics.mean(self.phase_data_hr)
            max_hr = max(self.phase_data_hr)
            avg_rmssd = statistics.mean(self.phase_data_rmssd)
            peak_rmssd = max(self.phase_data_rmssd)
        else:
            avg_hr, max_hr, avg_rmssd, peak_rmssd = 0, 0, 0, 0

        self.results[self.current_phase.lower()] = {
            "avg_hr": avg_hr, "max_hr": max_hr,
            "avg_rmssd": avg_rmssd, "peak_rmssd": peak_rmssd
        }

        sequence = ["REST", "STRESS", "EXERTION", "RECOVERY"]
        curr_idx = sequence.index(self.current_phase)
        if curr_idx < len(sequence) - 1:
            self.show_instruction(sequence[curr_idx + 1])
        else:
            self.save_profile()

    def save_profile(self):
        self.current_phase = "FINISHED"
        self.dashboard_active = False 
        self.clear_screen()

        profile = UserProfile(self.user_name)
        profile.calibrate(self.results['rest'], self.results['stress'], self.results['recovery'])
        
        age_max = 220 - self.user_age
        measured_max = self.results['exertion']['max_hr']
        profile.max_hr = max(age_max, measured_max)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_stats = {
            "date": timestamp,
            "resting_hr": round(profile.resting_hr, 1),
            "baseline_rmssd": round(profile.baseline_rmssd, 3),
            "stress_hr_threshold": round(profile.stress_hr_threshold, 1),
            "recovery_score": round(profile.recovery_score, 1),
            "max_hr": int(profile.max_hr),
            "raw_results": self.results
        }

        # Resolve File via DB (using parent app reference)
        db_u = self.parent.db_get_user(self.user_name)
        filename = db_u['linked_file'] if (db_u and db_u.get('linked_file') and db_u['linked_file'] != 'none') else f"{self.user_name.lower().replace(' ', '_')}_profile.json"
        
        full_path = os.path.join(PROFILE_DIR, filename) 
        
        final_data = {
            "name": self.user_name,
            "dob": self.user_dob,
            "age": self.user_age,
            "current_stats": new_stats,
            "history": []
        }

        if os.path.exists(full_path):
            backup_name = f"{filename}.{int(time.time())}.bak"
            if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
            try: shutil.copy(full_path, os.path.join(BACKUP_DIR, backup_name))
            except: pass

            try:
                with open(full_path, 'r') as f: old_data = json.load(f)
                if "history" in old_data: final_data["history"] = old_data["history"]
                if "current_stats" in old_data: final_data["history"].append(old_data["current_stats"])
            except: pass

        with open(full_path, 'w') as f:
            json.dump(final_data, f, indent=4)

        self.show_success_screen(profile, filename)

    def show_success_screen(self, profile, filename):
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        ttk.Label(frame, text="Calibration Complete!", style="Header.TLabel", foreground="#50fa7b").pack(pady=10)
        res_text = (
            f"Profile Saved: {filename}\n"
            f"Resting HR: {profile.resting_hr:.1f} bpm\n"
            f"Baseline HRV: {profile.baseline_rmssd:.3f} ms\n"
            f"Max HR: {int(profile.max_hr)} bpm"
        )
        ttk.Label(frame, text=res_text, font=("Courier", 12), background="black", padding=10).pack(fill=tk.BOTH, expand=True, pady=10)
        ttk.Button(frame, text="Close", command=self.destroy).pack(pady=20)

    def clear_screen(self):
        for widget in self.winfo_children(): widget.destroy()

    def destroy(self):
        self.dashboard_active = False # Stop loops
        if self.retry_task:
             try: self.after_cancel(self.retry_task)
             except: pass
        if self.reset_task:
             try: self.after_cancel(self.reset_task)
             except: pass
        if self.sensor:
            try: self.sensor.stop()
            except: pass
        try: self.parent.finish_calibration_wizard() # Notify parent if exists
        except: pass
        super().destroy()

if __name__ == "__main__":
    try:
        app = Bio5BXApp()
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        if 'app' in locals() and hasattr(app, 'sensor') and app.sensor:
             app.sensor.stop()
        if 'app' in locals():
             try: app.destroy()
             except: pass
