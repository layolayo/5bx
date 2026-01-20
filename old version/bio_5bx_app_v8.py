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
from PIL import Image, ImageTk

# Match v3 imports for graphing
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from ant_driver import AntHrvSensor
from ant_user_profile import UserProfile
import five_bx_data as bx

USER_DB_FILE = "../user_progress.db"
PROFILE_DIR = "../ant_user_profiles"
SESSION_DIR = "../ant_sessions"
IMG_DIR = "../images"
CALIBRATION_EXPIRY_DAYS = 30

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
        self.writer.writerow(["Timestamp", "HR_BPM", "RMSSD_MS", "Cadence_SPM", "State", "Trend", "Status", "Battery_V"])

    def log(self, hr, rmssd, cad, state, trend, status, bat):
        if self.writer:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.writer.writerow([ts, hr, rmssd, cad, state, trend, status, bat])
            self.file.flush()

    def stop(self):
        if self.file: self.file.close()

class Bio5BXApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bio-Adaptive 5BX Trainer")
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
        self.linker_active = False # New flag for first screen

        try:
            self.sensor = AntHrvSensor()
            self.sensor.start()
        except Exception as e:
            print(f"Sensor Error: {e}")
            self.sensor = None

        self.current_exercise_idx = 0
        self.workout_active = False
        self.timer_running = False
        self.reps_achieved = []
        self.target_reps_list = []
        self.temp_reps_buffer = None

        self._init_db()
        self.show_profile_linker()

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
            print('\a')
            try: os.system('spd-say "done" &')
            except: pass

    def calculate_age(self, dob_str):
        try:
            birth_date = datetime.datetime.strptime(dob_str, "%Y-%m-%d").date()
            today = datetime.date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except: return 30

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
                         goal_level TEXT
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
            
            conn.commit()
            conn.close()
        except Exception as e:
            messagebox.showerror("DB Error", f"Could not init DB: {e}")

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

    def db_create_user(self, name, age, linked_file, c_chart, c_level, g_chart, g_level):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            c.execute("""INSERT INTO users (name, age, linked_file, current_chart, current_level, goal_chart, goal_level) VALUES (?, ?, ?, ?, ?, ?, ?)""", (name, age, linked_file, c_chart, c_level, g_chart, g_level))
            conn.commit()
            conn.close()
        except: pass

    def db_update_level(self, user_id, new_chart, new_level):
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET current_chart=?, current_level=? WHERE id=?", (new_chart, new_level, user_id))
        conn.commit()
        conn.close()

    def db_add_history(self, user_id, chart, level, verdict, avg_hr, max_hr, rmssd, reps_list=None, stats_json=None):
        if reps_list is None: reps_list = [0,0,0,0,0]
        # Pad if short
        while len(reps_list) < 5: reps_list.append(0)
        
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("""INSERT INTO history (user_id, timestamp, chart, level, verdict, avg_hr, max_hr, end_rmssd, ex1, ex2, ex3, ex4, ex5, segment_stats)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (user_id, ts, chart, level, verdict, int(avg_hr), int(max_hr), int(rmssd), 
                      reps_list[0], reps_list[1], reps_list[2], reps_list[3], reps_list[4], stats_json))
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

    # --- SCREEN 1: LINKER ---
    def show_profile_linker(self):
        self.dashboard_active = False
        self._clear()
        self.linker_active = True # START LINKER LOOP

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        ttk.Label(frame, text="Select Calibration Profile", style="Header.TLabel", font=("Helvetica", 20, "bold")).pack(pady=20)

        # --- NEW: HARDWARE STATUS LABEL ON START SCREEN ---
        self.lbl_device_dash = ttk.Label(frame, text="📡 Searching for ANT+ Device...", foreground="#95a5a6", font=("Arial", 11))
        self.lbl_device_dash.pack(pady=5)
        # --------------------------------------------------

        profiles = glob.glob(os.path.join(PROFILE_DIR, "*_profile.json"))

        btn_calib = tk.Button(frame, text="Run Calibration Wizard", bg="#95a5a6", font=("Arial", 10), command=self.launch_calibration_app)
        btn_calib.pack(pady=5, anchor="ne")

        self.lst_profiles = tk.Listbox(frame, height=8, font=("Arial", 14))
        self.lst_profiles.pack(fill=tk.X, pady=10)
        for p in profiles:
            name = os.path.basename(p).replace("_profile.json", "").replace("_", " ").title()
            self.lst_profiles.insert(tk.END, name)

        self.btn_load = tk.Button(frame, text="Load User", bg="#2ecc71", font=("Arial", 12, "bold"), command=self.link_and_load)
        self.btn_load.pack(pady=20, fill=tk.X)
        
        # Quit Button
        tk.Button(frame, text="❌ Quit Application", command=self.quit_app, bg="#c0392b", fg="white", font=("Arial", 10)).pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        self.lst_profiles.bind('<<ListboxSelect>>', self.check_profile_date)

        # Start Live Update Loop
        self.update_status_loop()

    def launch_calibration_app(self):
        try: subprocess.Popen([sys.executable, "ant_calibration_app.py"])
        except Exception as e: messagebox.showerror("Error", f"Could not launch wizard: {e}")

    def check_profile_date(self, event):
        selection = self.lst_profiles.curselection()
        if not selection: return
        selected_text = self.lst_profiles.get(selection[0])
        clean_filename = selected_text.lower().replace(" ", "_") + "_profile.json"
        full_path = os.path.join(PROFILE_DIR, clean_filename)
        try:
            mod_time = os.path.getmtime(full_path)
            file_date = datetime.datetime.fromtimestamp(mod_time)
            if (datetime.datetime.now() - file_date).days > CALIBRATION_EXPIRY_DAYS:
                self.btn_load.config(text=f"⚠️ LOAD (Recalibration Due)", bg="#f1c40f")
            else:
                self.btn_load.config(text="Load User", bg="#2ecc71")
        except: pass

    def link_and_load(self):
        self.linker_active = False # Stop linker loop
        selection = self.lst_profiles.curselection()
        if not selection:
            messagebox.showwarning("Select User", "Please select a user from the list.")
            return

        selected_text = self.lst_profiles.get(selection[0])
        clean_filename = selected_text.lower().replace(" ", "_") + "_profile.json"
        self.full_profile_path = os.path.join(PROFILE_DIR, clean_filename)

        try:
            with open(self.full_profile_path, 'r') as f: self.profile_data = json.load(f)
        except Exception as e: return

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
            uptime = data.get('uptime_hours')
            bpm = data.get('bpm', 0)
            status = data.get('status', 'Initializing')

            if status == "Active" or bpm > 0:
                txt = f"📡 - ✅ {manuf} #{serial}" if serial else f"📡 - ❌ {manuf}"
                if batt_v: txt += f" | 🔋 {batt_v}V"
                if uptime and uptime > 0: txt += f" | ⏱ {uptime}h"
                if bpm > 0: txt += f" | ♥ Live HR: {bpm}"

                if hasattr(self, 'lbl_device_dash'):
                    self.lbl_device_dash.config(text=txt, foreground="#2ecc71")
            else:
                if hasattr(self, 'lbl_device_dash'):
                    self.lbl_device_dash.config(text=f"📡 {status}...", foreground="#95a5a6")

        self.after(1000, self.update_status_loop)

    # --- SCREEN 2: DASHBOARD ---
    def show_dashboard(self):
        self._clear()
        self.linker_active = False
        self.dashboard_active = True

        self.user_data = self.db_get_user(self.username)
        chart = self.user_data["current_chart"]
        level = self.user_data["current_level"]
        disp_level = bx.get_level_display(level)
        targets = bx.get_targets(chart, level)

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        header_text = f"User: {self.username} (Age {self.calculated_age}) | Chart {chart} - Level {disp_level}"
        ttk.Label(frame, text=header_text, font=("Helvetica", 14, "bold")).pack(pady=10)

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

        preview = ttk.LabelFrame(frame, text="Today's Targets")
        preview.pack(fill=tk.BOTH, expand=True, pady=10)
        for i, target in enumerate(targets):
            details = bx.get_exercise_detail(chart, i)
            row = ttk.Frame(preview)
            row.pack(fill=tk.X, padx=10, pady=5)
            
            txt = f"{i+1}. {details['name']}: {target} Reps"
            ttk.Label(row, text=txt, font=("Arial", 12)).pack(side=tk.LEFT)
            
            # Graph Button
            tk.Button(row, text="📈", font=("Arial", 10), 
                      command=lambda idx=i, name=details['name']: self.show_exercise_history(name, idx)).pack(side=tk.RIGHT)

        btn = tk.Button(frame, text="START WORKOUT (Try Max Reps)", bg="#2ecc71", font=("Arial", 16, "bold"), command=self.start_workout)
        btn.pack(fill=tk.X, pady=20)
        
        # Quit Button
        tk.Button(frame, text="❌ Quit Application", command=self.quit_app, bg="#c0392b", fg="white").pack(fill=tk.X, pady=10)

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
        self.hist_tree.column("Verdict", width=220)
        self.hist_tree.column("Reps", width=140)
        self.hist_tree.column("HR Stats", width=110)
        self.hist_tree.column("HRV", width=70)
        
        self.hist_tree.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.hist_tree.yview)
        self.hist_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        records = self.db_get_history(self.user_id)
        for r in records:
            lvl_disp = bx.get_level_display(r['level'])
            full_level = f"{r['chart']}-{lvl_disp}"
            
            # Format Reps
            reps_str = ""
            if 'ex1' in r.keys() and r['ex1'] is not None:
                reps_str = f"{r['ex1']}-{r['ex2']}-{r['ex3']}-{r['ex4']}-{r['ex5']}"
            else:
                reps_str = "--"
            
            tag = "neutral"
            if "LEAPFROG" in r['verdict']: tag = "super"
            elif "LEVEL UP" in r['verdict']: tag = "good"
            elif "PROMOTION" in r['verdict']: tag = "good"
            elif "REPEAT" in r['verdict']: tag = "bad"
            elif "DROP" in r['verdict']: tag = "drop"
            
            self.hist_tree.insert("", "end", iid=r['id'], values=(
                r['timestamp'],
                full_level,
                r['verdict'],
                reps_str,
                f"{r['avg_hr']} / {r['max_hr']}",
                f"{r['end_rmssd']} ms"
            ), tags=(tag,))
            
        self.hist_tree.tag_configure("super", foreground="purple", font=("Arial", 10, "bold"))
        self.hist_tree.tag_configure("good", foreground="green")
        self.hist_tree.tag_configure("bad", foreground="#e67e22") 
        self.hist_tree.tag_configure("drop", foreground="red", font=("Arial", 10, "bold"))
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=20)
        
        tk.Button(btn_frame, text="Back to Dashboard", command=self.show_dashboard).pack(side=tk.LEFT)
        tk.Button(btn_frame, text="View Details", bg="#3498db", fg="white", command=self.history_view_details).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Delete Selected (Undo)", bg="#c0392b", fg="white", command=self.delete_history_item).pack(side=tk.RIGHT)
    
    def show_badges_screen(self):
        root = tk.Toplevel(self)
        root.title("Trophy Room")
        root.geometry("500x600")
        root.configure(bg="#2c3e50")
        
        tk.Label(root, text="🏆 EARNED BADGES 🏆", font=("Arial", 20, "bold"), fg="#f1c40f", bg="#2c3e50").pack(pady=20)
        
        badges = bx.get_earned_badges(self.user_data['current_chart'], self.user_data['current_level'])
        
        # Scrollable Frame Logic
        main_frame = tk.Frame(root, bg="#2c3e50")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        canvas = tk.Canvas(main_frame, bg="#2c3e50", highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#2c3e50")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Render Badges
        if not badges:
             tk.Label(scrollable_frame, text="No badges yet. Keep training!", font=("Arial", 14), fg="#bdc3c7", bg="#2c3e50").pack(pady=20)
        else:
            for b in badges:
                card = tk.Frame(scrollable_frame, bg="#34495e", pady=10, padx=10)
                card.pack(fill=tk.X, pady=5, padx=5)
                
                icon = "🏅" if "Standard" in b else "✈️"
                color = "#f39c12" if "Standard" in b else "#e74c3c"
                
                tk.Label(card, text=icon, font=("Arial", 24), bg="#34495e", fg=color).pack(side=tk.LEFT, padx=10)
                tk.Label(card, text=b, font=("Arial", 14, "bold"), bg="#34495e", fg="white").pack(side=tk.LEFT)
                
        tk.Button(root, text="Close", font=("Arial", 12), command=root.destroy, bg="#e74c3c", fg="white").pack(pady=10)
    
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
        top.geometry("500x500")
        top.configure(bg="#2c3e50")
        
        lbl_h = tk.Label(top, text="Physiological Breakdown", font=("Helvetica", 16, "bold"), bg="#2c3e50", fg="white")
        lbl_h.pack(pady=10)
        
        txt = tk.Text(top, height=20, font=("Courier", 11), bg="#34495e", fg="white", padx=10, pady=10)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        report = []
        if stats_json:
            try:
                data = json.loads(stats_json)
                for item in data:
                    name = item['name']
                    # Tag Back Arch
                    hrv_str = f"{item['hrv']} ms"
                    if "Back Arch" in name: hrv_str = "(Artifact Ignored)"
                    
                    report.append(f"• {name.upper()}")
                    report.append(f"   HR:  Avg {item['avg_hr']} | Max {item['max_hr']}")
                    report.append(f"   HRV: {hrv_str}")
                    
                    # Mini analysis
                    if item['max_hr'] > (self.bio_profile.max_hr * 0.9):
                        report.append("   ⚠️ HIGH INTENSITY")
                    report.append("")
            except:
                report.append("Error parsing detailed stats.")
        else:
            report.append("No detailed physiological data available for this session.")
            report.append("(It may be from an older version of the app).")
            
        txt.insert(tk.END, "\n".join(report))
        
        btn = tk.Button(top, text="Close", command=top.destroy)
        btn.pack(pady=10)

    def open_chart_viewer(self):
        # Default to current user chart
        try: self.view_chart_idx = int(self.user_data["current_chart"])
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
            d = bx.get_exercise_detail(str(self.view_chart_idx), i)
            exercises.append(d['name'])
            
        # Headers
        tk.Label(self.chart_content, text="Lvl", bg="#2c3e50", fg="#bdc3c7", font=("Arial", 12, "bold")).grid(row=0, column=0, padx=5, pady=5)
        for i, name in enumerate(exercises):
            h_frame = tk.Frame(self.chart_content, bg="#2c3e50")
            h_frame.grid(row=0, column=i+1, padx=5, pady=5, sticky="ew")
            # Exercise Name Button (Show Info)
            tk.Button(h_frame, text=name, bg="#3498db", fg="white", font=("Arial", 11, "bold"), 
                      command=lambda x=i: self.show_exercise_info(x)).pack(side=tk.TOP, fill=tk.X)

        # Data Rows
        conn = sqlite3.connect(bx.DB_NAME)
        c = conn.cursor()
        # Order DESC for Level 12 at top
        c.execute("SELECT level, ex1, ex2, ex3, ex4, ex5 FROM ExerciseTimes WHERE chart=? ORDER BY level DESC", (str(self.view_chart_idx),))
        rows = c.fetchall()
        conn.close()
        
        # User Status for Highlighting
        u_chart = str(self.user_data.get('current_chart', '1'))
        u_level = str(self.user_data.get('current_level', '1'))
        g_chart = str(self.user_data.get('goal_chart', '1'))
        g_level = str(self.user_data.get('goal_level', '1'))
        
        # Row Offset for Grid (Header is row 0)
        r_offset = 1
        
        for idx, r in enumerate(rows):
            lvl = str(r[0])
            is_current = (str(self.view_chart_idx) == u_chart and lvl == u_level)
            is_goal = (str(self.view_chart_idx) == g_chart and lvl == g_level)
            
            bg_color = "#34495e" # default
            if is_current: bg_color = "#27ae60" # Current = Green
            elif is_goal: bg_color = "#f39c12"  # Goal = Orange
            
            grid_row = r_offset + idx
            
            # Level Label
            tk.Label(self.chart_content, text=bx.get_level_display(lvl), bg=bg_color, fg="white", font=("Arial", 12), width=6).grid(row=grid_row, column=0, padx=2, pady=2, sticky="nsew")
            
            # Reps
            for i in range(5):
                val = r[i+1]
                tk.Label(self.chart_content, text=str(val), bg=bg_color, fg="white", font=("Arial", 14)).grid(row=grid_row, column=i+1, padx=2, pady=2, sticky="nsew")
                
        # Configure grid weights
        self.chart_content.grid_columnconfigure(0, weight=1)
        for i in range(5): self.chart_content.grid_columnconfigure(i+1, weight=3)

    def show_exercise_history_popup(self, name, idx):
        # Reuse existing logic but in a new Toplevel is easiest to ensure it sits on top of chart viewer
        self.show_exercise_history(name, idx) 
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
        tk.Label(content_frame, text=details['desc'], font=("Arial", 12), bg="#34495e", fg="#ecf0f1", wraplength=text_wrap, justify=tk.LEFT).pack(side=tk.LEFT, padx=10, fill=tk.BOTH, expand=True)

        # --- GRAPH RENDERING ---
        for widget in self.graph_pane.winfo_children(): widget.destroy()
        
        records = self.db_get_history(self.user_id)
        report_reps, report_hr, report_hrv, dates = [], [], [], []
        
        records = self.db_get_history(self.user_id)
        report_reps, report_hr, report_hrv, dates = [], [], [], []
        
        for r in records:
            # Filter by Current Chart
            if str(r['chart']) != str(self.view_chart_idx):
                 continue
                 
            # Parse Reps
            reps_list = [0]*5
            if r['ex1']: reps_list = [r['ex1'], r['ex2'], r['ex3'], r['ex4'], r['ex5']]
            
            # Skip if 0 reps for this exercise (meaning not completed or irrelevant)
            if reps_list[idx] <= 0: continue
            
            # Parse Detailed Stats (JSON)
            hr = 0
            hrv = 0
            stats_json = r.get('segment_stats')
            if stats_json:
                try:
                    data = json.loads(stats_json)
                    # We need to match exercise name to find stats
                    for item in data:
                        if item['name'] == details['name']:
                             hr = item['max_hr']
                             hrv = item['hrv']
                             break
                except: pass
            
            # If no detailed stats found, maybe use session average? No, keep 0 to avoid noise.
            
            dates.append(r['timestamp'][:10])
            report_reps.append(reps_list[idx])
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
        ax1.plot(dates, report_reps, marker='o', color='#2ecc71', linewidth=2, label="Reps")
        ax1.set_title("Reps Progress", color="white", fontsize=10)
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
        max_id = c.fetchone()[0]
        c.execute("SELECT chart, level FROM history WHERE id=?", (db_id,))
        record_data = c.fetchone()
        conn.close()

        if messagebox.askyesno("Confirm", "Delete this record?"):
            self.db_delete_history(db_id)
            if db_id == max_id and record_data:
                self.db_update_level(self.user_id, record_data[0], record_data[1])
            self.show_history_screen()

    # --- EXERCISE FLOW ---
    def start_workout(self):
        self.dashboard_active = False
        self.current_exercise_idx = 0
        self.session_metrics = []
        self.reps_achieved = []
        self.logger = SessionLogger(self.username)
        self.logger.start()

        chart = self.user_data["current_chart"]
        level = self.user_data["current_level"]
        self.target_reps_list = bx.get_targets(chart, level)
        self.workout_active = True
        self.timer_running = False
        
        # Switch to main thread loop for UI safety
        self.run_exercise_screen()
        self.sensor_loop() 

    def run_exercise_screen(self):
        self._clear()
        idx = self.current_exercise_idx
        if idx >= 5:
            self.finish_workout()
            return

        chart = self.user_data["current_chart"]
        details = bx.get_exercise_detail(chart, idx)
        target = self.target_reps_list[idx]
        duration = bx.TIME_LIMITS[idx]

        self.session_metrics.append({'name': details['name'], 'hr': [], 'rmssd': []})

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        # Top Bar
        top_bar = ttk.Frame(frame)
        top_bar.pack(fill=tk.X, pady=5)
        
        tk.Button(top_bar, text="⬅ Quit Workout", command=self.show_dashboard, bg="#e74c3c", fg="white").pack(side=tk.LEFT)
        
        ttk.Label(frame, text=f"Exercise {idx+1}: {details['name']}", font=("Helvetica", 24, "bold")).pack()

        img_path = os.path.join(IMG_DIR, details['img'])
        if os.path.exists(img_path) and details['img']:
            try:
                load = Image.open(img_path)
                orig_w, orig_h = load.size
                target_w = 400
                target_h = int(target_w * (orig_h / orig_w))
                if target_h > 300: target_h = 300; target_w = int(target_h * (orig_w / orig_h))
                load = load.resize((target_w, target_h), Image.Resampling.LANCZOS)
                render = ImageTk.PhotoImage(load)
                img_lbl = tk.Label(frame, image=render, bg="#2c3e50")
                img_lbl.image = render
                img_lbl.pack(pady=10)
            except: pass
            
        ttk.Label(frame, text=details['desc'], wraplength=800, justify=tk.CENTER, font=("Arial", 16)).pack(pady=10)
        
        # History Button
        tk.Button(frame, text=f"📈 View History: {details['name']}", 
                 command=lambda: self.show_exercise_history(details['name'], idx)).pack()
        
        info_frame = ttk.Frame(frame); info_frame.pack(pady=10)
        lbl_target = ttk.Label(info_frame, text=f"GOAL: {target}", font=("Courier", 32, "bold"), foreground="red")
        lbl_target.pack(side=tk.LEFT, padx=20)
        self.time_left = duration
        self.lbl_timer = ttk.Label(info_frame, text=f"{self.time_left}s", font=("Courier", 32))
        self.lbl_timer = ttk.Label(info_frame, text=f"{self.time_left}s", font=("Courier", 32))
        self.lbl_timer.pack(side=tk.RIGHT, padx=20)

        self.lbl_hr = ttk.Label(frame, text="HR: --", font=("Arial", 48, "bold"))
        self.lbl_hr.pack()
        self.lbl_advice = ttk.Label(frame, text="Get Ready...", foreground="cyan", font=("Arial", 24, "bold"))
        self.lbl_advice.pack()
        
        # HRM Status Label (Bottom)
        self.lbl_device_status = ttk.Label(frame, text="📡 Scanning...", foreground="#95a5a6", font=("Arial", 14))
        self.lbl_device_status.pack(side=tk.BOTTOM, pady=5)

        self.btn_action = tk.Button(frame, text="START TIMER", bg="#2ecc71", font=("Arial", 14, "bold"), command=self.start_timer_action)
        self.btn_action.pack(fill=tk.X, side=tk.BOTTOM, pady=10)
        self.timer_running = False

    def start_timer_action(self):
        self.timer_running = True
        self.btn_action.config(text="COMPLETED (Input Reps)", bg="#e67e22", command=self.input_results)
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
        e_reps.insert(0, str(self.target_reps_list[idx]))
        e_reps.pack(pady=10); e_reps.select_range(0, tk.END); e_reps.focus_force()
        self.temp_reps_buffer = None

        def save_reps(event=None):
            try: 
                val = int(e_reps.get().strip())
                self.temp_reps_buffer = val
                
                # BADGE LOGIC
                target = self.target_reps_list[idx]
                diff = val - target
                badge = None
                color = "gold"
                
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
        if self.time_left > 0:
            self.time_left -= 1
            self.lbl_timer.config(text=f"{self.time_left}s")
            self.after(1000, self.timer_loop)
        else:
            self.lbl_timer.config(text="TIME UP!", foreground="red")
            self.btn_action.config(text="TIME UP - Enter Reps", bg="#c0392b")
            self.play_beep()

    def sensor_loop(self):
        if not self.workout_active: return
        
        if self.sensor:
            data = self.sensor.get_data()
            hr = data['bpm']
            rmssd = data['rmssd']
            cad = data.get('cadence', 0)

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
                    self.logger.log(hr, rmssd, cad, f"Ch {chart} - Lvl {level}", f"C{chart}-Ex {self.current_exercise_idx+1}: {name}", log_status, data.get('battery_volts'))

                try:
                    txt = f"♥ {hr} BPM"
                    if cad > 0: txt += f" | 👟 {cad} spm"
                    if hasattr(self, 'lbl_hr'): self.lbl_hr.config(text=txt)
                    if hasattr(self, 'lbl_advice'): self.lbl_advice.config(text=status_text, foreground=status_color)
                except: pass
        
            # Update Device Status Label (Detailed)
            manuf = data.get('manufacturer', 'Unknown')
            serial = data.get('serial')
            bat = data.get('battery_volts')
            uptime = data.get('uptime_hours')
            bpm = data.get('bpm', 0)
            status = data.get('status', 'Initializing')

            if status == "Active" or bpm > 0:
                stat_txt = f"📡 - ✅ {manuf} #{serial}" if serial else f"📡 - ❌ {manuf}"
                if bat: stat_txt += f" | 🔋 {bat}V"
                if uptime and uptime > 0: stat_txt += f" | ⏱ {uptime}h"
            else:
                stat_txt = f"📡 {status}..."

            try:
                if hasattr(self, 'lbl_device_status'):
                        self.lbl_device_status.config(text=stat_txt, foreground="#2ecc71" if bpm > 0 else "#95a5a6")
            except: pass
            
        self.after(1000, self.sensor_loop)

    # --- FINISH & REPORT ---
    def finish_workout(self):
        self.workout_active = False
        if self.logger: self.logger.stop()
        self._clear()

        missed = 0
        for a, t in zip(self.reps_achieved, self.target_reps_list):
            if a < t: missed += 1
        physical_pass = (missed == 0)

        report_text = ["--- SESSION BREAKDOWN ---"]
        warnings = 0
        session_peak_hr = 0
        all_hr, all_rmssd = [], []

        for i, metric in enumerate(self.session_metrics):
            name, hrs, hrvs = metric['name'], metric['hr'], metric['rmssd']
            if not hrs:
                report_text.append(f"{name}: No Data"); continue

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

        chart = self.user_data["current_chart"]
        level = self.user_data["current_level"]
        try:
            next_c, next_l = bx.get_next_level(chart, level)
            perf_c, perf_l = bx.calculate_placement(self.reps_achieved, chart)
        except: next_c, next_l, perf_c, perf_l = chart, level, chart, level

        status, color, reason = "MAINTAIN", "white", ""

        if max_session_hr > (self.true_max_hr * 0.95) or warnings > 1:
            status, color = "DROP LEVEL (Safety)", "#ff5555"
            reason = "Physiological Cost High. Reduce Intensity."
            new_c, new_l = chart, level
        elif not physical_pass:
            if (int(perf_c)*100+int(perf_l)) < ((int(chart)*100+int(level))-2):
                status, color = "RECALIBRATE (Drop)", "#ff5555"
                new_c, new_l = perf_c, perf_l
            else:
                status, color = "REPEAT LEVEL", "#f1c40f"
                new_c, new_l = chart, level
        else:
            if int(perf_c) > int(chart): status, color = f"PROMOTION! (Chart {int(chart)+1})", "#9b59b6"; new_c, new_l = str(int(chart)+1), "1"
            elif int(perf_l) > int(next_l): status, color = f"LEAPFROG! (Level {bx.get_level_display(perf_l)})", "#9b59b6"; new_c, new_l = perf_c, perf_l
            elif end_session_rmssd > self.bio_profile.baseline_rmssd: status, color = "DOUBLE LEVEL UP!", "#50fa7b"; new_c, new_l = bx.get_next_level(next_c, next_l)
            else: status, color = "LEVEL UP", "#8be9fd"; new_c, new_l = next_c, next_l

        # Check for Milestones
        age = self.calculate_age(self.user_data['dob'])
        milestones = bx.check_milestones(age, chart, level, new_c, new_l)
        
        # MILESTONE POPUP
        if milestones:
            m_top = tk.Toplevel(self)
            m_top.title("ACHIEVEMENT UNLOCKED!")
            m_top.geometry("600x400")
            m_top.configure(bg="#8e44ad")
            
            tk.Label(m_top, text="🏆 CONGRATULATIONS! 🏆", font=("Arial", 28, "bold"), fg="#f1c40f", bg="#8e44ad").pack(pady=30)
            
            for m in milestones:
                tk.Label(m_top, text=m, font=("Arial", 22), fg="white", bg="#8e44ad").pack(pady=10)
                
            tk.Button(m_top, text="Woohoo!", command=m_top.destroy, font=("Arial", 16), bg="#f1c40f").pack(pady=30)
            
            # Center Popup
            m_top.update_idletasks()
            w, h = m_top.winfo_width(), m_top.winfo_height()
            x = (m_top.winfo_screenwidth() // 2) - (w // 2)
            y = (m_top.winfo_screenheight() // 2) - (h // 2)
            m_top.geometry(f"+{x}+{y}")
            self.wait_window(m_top)

        # 4. Serialize Detailed Stats for History
        stats_data = []
        for i, metric in enumerate(self.session_metrics):
            name = metric['name']
            hr_data = metric['hr']
            hrv_data = metric['rmssd']
            
            avg_hr_seg = int(sum(hr_data)/len(hr_data)) if hr_data else 0
            max_hr_seg = max(hr_data) if hr_data else 0
            
            # Use raw HRV average, markers will interpret artifact status later
            avg_hrv_seg = int(sum(hrv_data)/len(hrv_data)) if hrv_data else 0
            
            stats_data.append({
                "name": name, 
                "avg_hr": avg_hr_seg, 
                "max_hr": max_hr_seg, 
                "hrv": avg_hrv_seg
            })
        
        stats_json = json.dumps(stats_data)

        self.db_update_level(self.user_id, new_c, new_l)
        self.db_add_history(self.user_id, chart, level, f"{status} -> {new_c}-{bx.get_level_display(new_l)}", avg_session_hr, max_session_hr, end_session_rmssd, self.reps_achieved, stats_json)

        frame = ttk.Frame(self); frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        ttk.Label(frame, text="Workout Complete", style="Header.TLabel").pack()
        ttk.Label(frame, text=f"VERDICT: {status}", font=("Arial", 16, "bold"), foreground=color).pack(pady=5)
        ttk.Label(frame, text=reason, font=("Arial", 12)).pack()

        text_frame = ttk.Frame(frame); text_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        scr = ttk.Scrollbar(text_frame); scr.pack(side=tk.RIGHT, fill=tk.Y)
        txt = tk.Text(text_frame, height=15, font=("Courier", 10), bg="#34495e", fg="white", yscrollcommand=scr.set)
        txt.pack(fill=tk.BOTH, expand=True); txt.insert(tk.END, "\n".join(report_text)); scr.config(command=txt.yview)

        ttk.Button(frame, text="Save & Exit", command=self.show_profile_linker).pack(pady=10)

    # --- HISTORY GRAPH LOGIC ---
    def show_exercise_history(self, exercise_name_query, exercise_idx_query):
        """
        Shows a graph of progress for a specific exercise name.
        exercise_name_query: The string name (e.g. "Toe Touch") to filter by.
        exercise_idx_query: 0-4 (The index in the routine - used as fallback for old data).
        """
        records = self.db_get_history(self.user_id)
        # Sort by ID ascending for time
        records.reverse() 
        
        dates = []
        reps = []
        hrs = []
        hrvs = []
        
        for r in records:
            # Determine if this history record contains the exercise we are looking for
            # 1. Check if we have detailed stats (Best)
            found_in_stats = False
            r_reps = 0
            r_hr = 0
            r_hrv = 0
            
            # Helper to parse old 'exN' columns
            col_key = f"ex{exercise_idx_query+1}"
            legacy_reps = r[col_key] if col_key in r.keys() and r[col_key] else 0
            
            # Try parsing JSON stats
            if 'segment_stats' in r.keys() and r['segment_stats']:
                try:
                    stats = json.loads(r['segment_stats'])
                    for s in stats:
                        if s['name'] == exercise_name_query:
                            r_reps = legacy_reps # Stats don't have reps yet, use column
                            r_hr = s['avg_hr']
                            r_hrv = s['hrv']
                            found_in_stats = True
                            break
                except: pass
                
            # If not found in JSON, do we infer it from Chart/Level?
            if not found_in_stats:
                # We can check if the exercise name matches what this chart is supposed to have
                chart = r['chart']
                details = bx.get_exercise_detail(chart, exercise_idx_query)
                if details['name'] == exercise_name_query:
                    # Match! use legacy data if available
                    r_reps = legacy_reps
                    # We don't have per-exercise HR for old records, so maybe skip HR or use session avg?
                    # Let's use session avg as a rough proxy if missing
                    r_hr = r['avg_hr'] 
                    r_hrv = 0 # No detailed HRV
                else:
                    continue # This record was for a different exercise (e.g. different chart level with different movement)
            
            if r_reps > 0:
                short_date = r['timestamp'].split(" ")[0][5:] # MM-DD
                dates.append(short_date)
                reps.append(r_reps)
                hrs.append(r_hr)
                hrvs.append(r_hrv)
                
        if not dates:
            messagebox.showinfo("History", f"No history data found for {exercise_name_query}")
            return

        # -- PLOT --
        top = tk.Toplevel(self)
        top.title(f"Progress: {exercise_name_query}")
        top.geometry("800x600")
        top.configure(bg="#2c3e50")
        
        fig = Figure(figsize=(8, 6), dpi=100, facecolor="#2c3e50")
        
        # Subplot 1: Reps
        ax1 = fig.add_subplot(211)
        ax1.set_facecolor("#34495e")
        ax1.plot(dates, reps, marker='o', color='#2ecc71', linewidth=2, label="Reps")
        ax1.set_title(f"Reps Count: {exercise_name_query}", color="white")
        ax1.tick_params(colors='white')
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
        ax2.tick_params(colors='white')
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper left')

        canvas = FigureCanvasTkAgg(fig, master=top)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _clear(self):
        for widget in self.winfo_children(): widget.destroy()
    def destroy(self):
        self.workout_active = False; self.dashboard_active = False; self.linker_active = False
        if self.sensor:
            try: self.sensor.stop()
            except: pass
        super().destroy()

if __name__ == "__main__":
    app = Bio5BXApp()
    app.mainloop()