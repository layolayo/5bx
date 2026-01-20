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

# Import your existing drivers
from ant_driver_v1 import AntHrvSensor
from ant_user_profile import UserProfile
import five_bx_data as bx

# Configuration
USER_DB_FILE = "../user_progress.db"
PROFILE_DIR = "../ant_user_profiles"
SESSION_DIR = "../ant_sessions"
IMG_DIR = "../images"
CALIBRATION_EXPIRY_DAYS = 30


class SessionLogger:
    """Logs raw data to CSV for external analysis"""

    def __init__(self, user_name):
        self.user_name = user_name
        self.filename = None
        self.file = None
        self.writer = None

        if not os.path.exists(SESSION_DIR):
            os.makedirs(SESSION_DIR)

    def start(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join([c for c in self.user_name if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
        self.filename = os.path.join(SESSION_DIR, f"session_5bx_{safe_name}_{ts}.csv")

        self.file = open(self.filename, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(
            ["Timestamp", "HR_BPM", "RMSSD_MS", "Raw_RR_MS", "State", "Trend", "Status", "Raw_Packet_Hex"])

    def log(self, hr, rmssd, rr, state, trend, status, packet):
        if self.writer:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.writer.writerow([ts, hr, rmssd, rr, state, trend, status, packet])
            self.file.flush()

    def stop(self):
        if self.file:
            self.file.close()


class Bio5BXApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bio-Adaptive 5BX Trainer")
        self.geometry("1000x900")
        self.configure(bg="#2c3e50")

        self.user_id = None
        self.username = None
        self.user_data = {}
        self.profile_data = {}
        self.calculated_age = 30

        self.true_max_hr = 180

        self.session_metrics = []
        self.logger = None

        # SENSOR INIT
        try:
            self.sensor = AntHrvSensor()
            self.sensor.start()
        except Exception as e:
            print(f"Sensor Error: {e}")
            self.sensor = None

        # State
        self.current_exercise_idx = 0
        self.workout_active = False
        self.timer_running = False
        self.reps_achieved = []
        self.target_reps_list = []
        self.temp_reps_buffer = None

        self._init_db()
        self.show_profile_linker()

    # --- SOUND ENGINE ---
    def play_beep(self):
        system_os = platform.system()
        if system_os == "Windows":
            try:
                import winsound
                winsound.Beep(1000, 700)
            except:
                self.bell()
        elif system_os == "Darwin":
            self.bell()
        else:
            self.bell()
            print('\a')
            try:
                os.system('spd-say "done" &')
            except:
                pass

    # --- SHARED UTILS ---
    def calculate_age(self, dob_str):
        try:
            birth_date = datetime.datetime.strptime(dob_str, "%Y-%m-%d").date()
            today = datetime.date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except:
            return 30

            # --- DATABASE MANAGEMENT ---

    def _init_db(self):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             name
                             TEXT
                             UNIQUE,
                             age
                             INTEGER,
                             linked_file
                             TEXT,
                             current_chart
                             TEXT,
                             current_level
                             TEXT,
                             goal_chart
                             TEXT,
                             goal_level
                             TEXT
                         )''')
            c.execute('''CREATE TABLE IF NOT EXISTS history
            (
                id
                INTEGER
                PRIMARY
                KEY
                AUTOINCREMENT,
                user_id
                INTEGER,
                timestamp
                TEXT,
                chart
                TEXT,
                level
                TEXT,
                verdict
                TEXT,
                avg_hr
                INTEGER,
                max_hr
                INTEGER,
                end_rmssd
                INTEGER,
                FOREIGN
                KEY
                         (
                user_id
                         ) REFERENCES users
                         (
                             id
                         )
                )''')
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
        except:
            return None

    def db_create_user(self, name, age, linked_file, c_chart, c_level, g_chart, g_level):
        try:
            conn = sqlite3.connect(USER_DB_FILE)
            c = conn.cursor()
            c.execute(
                """INSERT INTO users (name, age, linked_file, current_chart, current_level, goal_chart, goal_level)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                      (name, age, linked_file, c_chart, c_level, g_chart, g_level))
            conn.commit()
            conn.close()
        except: pass

    def db_update_level(self, user_id, new_chart, new_level):
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET current_chart=?, current_level=? WHERE id=?", (new_chart, new_level, user_id))
        conn.commit()
        conn.close()

    def db_add_history(self, user_id, chart, level, verdict, avg_hr, max_hr, rmssd):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("""INSERT INTO history (user_id, timestamp, chart, level, verdict, avg_hr, max_hr, end_rmssd)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (user_id, ts, chart, level, verdict, int(avg_hr), int(max_hr), int(rmssd)))
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

    def db_get_last_session(self, user_id):
        conn = sqlite3.connect(USER_DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    # --- SCREEN 1: PROFILE LINKER ---
    def show_profile_linker(self):
        self._clear()
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        ttk.Label(frame, text="Select Calibration Profile", style="Header.TLabel", font=("Helvetica", 20, "bold")).pack(pady=20)

        profiles = glob.glob(os.path.join(PROFILE_DIR, "*_profile.json"))
        if not profiles:
            ttk.Label(frame, text="No Profiles Found!", foreground="red").pack()

        btn_calib = tk.Button(frame, text="Run Calibration Wizard", bg="#95a5a6", font=("Arial", 10), command=self.launch_calibration_app)
        btn_calib.pack(pady=5, anchor="ne")

        self.lst_profiles = tk.Listbox(frame, height=8, font=("Arial", 14))
        self.lst_profiles.pack(fill=tk.X, pady=10)

        for p in profiles:
            name = os.path.basename(p).replace("_profile.json", "").replace("_", " ").title()
            self.lst_profiles.insert(tk.END, name)

        self.btn_load = tk.Button(frame, text="Load User", bg="#2ecc71", font=("Arial", 12, "bold"), command=self.link_and_load)
        self.btn_load.pack(pady=20, fill=tk.X)

        self.lst_profiles.bind('<<ListboxSelect>>', self.check_profile_date)

    def launch_calibration_app(self):
        try:
            subprocess.Popen([sys.executable, "ant_calibration_app.py"])
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch wizard: {e}")

    def check_profile_date(self, event):
        selection = self.lst_profiles.curselection()
        if not selection: return

        selected_text = self.lst_profiles.get(selection[0])
        clean_filename = selected_text.lower().replace(" ", "_") + "_profile.json"
        full_path = os.path.join(PROFILE_DIR, clean_filename)

        try:
            mod_time = os.path.getmtime(full_path)
            file_date = datetime.datetime.fromtimestamp(mod_time)
            now = datetime.datetime.now()
            delta = now - file_date

            if delta.days > CALIBRATION_EXPIRY_DAYS:
                self.btn_load.config(text=f"⚠️ LOAD (Recalibration Due: {delta.days} days old)", bg="#f1c40f")
            else:
                self.btn_load.config(text="Load User", bg="#2ecc71")
        except: pass

    def link_and_load(self):
        selection = self.lst_profiles.curselection()
        if not selection:
            messagebox.showwarning("Select User", "Please select a user from the list.")
            return

        selected_text = self.lst_profiles.get(selection[0])
        clean_filename = selected_text.lower().replace(" ", "_") + "_profile.json"
        self.full_profile_path = os.path.join(PROFILE_DIR, clean_filename)

        try:
            with open(self.full_profile_path, 'r') as f:
                self.profile_data = json.load(f)
        except Exception as e:
            messagebox.showerror("File Error", f"Cannot open profile: {e}")
            return

        raw_name = self.profile_data.get("name", selected_text)
        user_name = raw_name.title()

        if "dob" in self.profile_data:
            self.calculated_age = self.calculate_age(self.profile_data["dob"])
        else:
            self.calculated_age = self.profile_data.get("age", 30)

        existing = self.db_get_user(user_name)
        if not existing:
            goal_c, goal_l = bx.get_age_goal(self.calculated_age)
            self.db_create_user(user_name, self.calculated_age, clean_filename, "1", "1", goal_c, goal_l)

        self.load_user_session(user_name)

    def load_user_session(self, name):
        self.user_data = self.db_get_user(name)
        if not self.user_data:
            messagebox.showerror("Error", f"Could not load data for {name}")
            return

        self.user_id = self.user_data['id']
        self.username = name

        curr = self.profile_data.get('current_stats', {})
        self.bio_profile = UserProfile(name)
        self.bio_profile.baseline_rmssd = curr.get('baseline_rmssd', 40)

        # Max HR Calculation
        profile_max = curr.get('max_hr', 180)
        age_max = 220 - self.calculated_age
        self.true_max_hr = max(profile_max, age_max)
        self.bio_profile.max_hr = self.true_max_hr

        self.show_dashboard()

    # --- SCREEN 2: DASHBOARD ---
    def show_dashboard(self):
        self._clear()
        self.user_data = self.db_get_user(self.username)

        chart = self.user_data["current_chart"]
        level = self.user_data["current_level"]
        disp_level = bx.get_level_display(level)
        targets = bx.get_targets(chart, level)

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        header_text = f"User: {self.username} (Age {self.calculated_age}) | Chart {chart} - Level {disp_level}"
        ttk.Label(frame, text=header_text, font=("Helvetica", 14, "bold")).pack(pady=10)

        # 1. BIO STATS
        stats_frame = ttk.Frame(frame)
        stats_frame.pack(fill=tk.X, pady=5)

        curr = self.profile_data.get('current_stats', {})
        rhr = curr.get('resting_hr', '?')
        rmssd = curr.get('baseline_rmssd', '?')

        max_hr_source = "Profile" if self.bio_profile.max_hr == curr.get('max_hr', 0) else "Age-Predicted"

        lbl_stats = ttk.Label(stats_frame, text=f"❤️ RHR: {rhr} | ⚡ HRV: {rmssd}ms | 🎯 Max HR: {self.true_max_hr} ({max_hr_source})",
                              foreground="#1abc9c", font=("Arial", 11))
        lbl_stats.pack(anchor="center")

        # 2. BUTTON ROW
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)
        tk.Button(btn_frame, text="View History Log", bg="#3498db", fg="white", font=("Arial", 10, "bold"),
                  command=self.show_history_screen).pack(fill=tk.X, padx=20)

        # 3. EXERCISE LIST
        preview = ttk.LabelFrame(frame, text="Today's Targets")
        preview.pack(fill=tk.BOTH, expand=True, pady=10)

        for i, target in enumerate(targets):
            details = bx.get_exercise_detail(chart, i)
            txt = f"{i+1}. {details['name']}: {target} Reps"
            ttk.Label(preview, text=txt, font=("Arial", 12)).pack(anchor='w', padx=10, pady=5)

        btn = tk.Button(frame, text="START WORKOUT (Try Max Reps)", bg="#2ecc71", font=("Arial", 16, "bold"), command=self.start_workout)
        btn.pack(fill=tk.X, pady=20)

        ttk.Label(frame, text="Tip: Do as many reps as possible to Fast-Track!", font=("Arial", 10, "italic")).pack()

    # --- SCREEN 2.5: HISTORY ---
    def show_history_screen(self):
        self._clear()

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(frame, text=f"History: {self.username}", style="Header.TLabel", font=("Helvetica", 18, "bold")).pack(pady=10)

        cols = ("Date", "Level", "Verdict", "HR Stats", "HRV")
        self.hist_tree = ttk.Treeview(frame, columns=cols, show='headings', height=15)

        self.hist_tree.heading("Date", text="Date")
        self.hist_tree.heading("Level", text="Chart-Level")
        self.hist_tree.heading("Verdict", text="Result")
        self.hist_tree.heading("HR Stats", text="Avg / Max HR")
        self.hist_tree.heading("HRV", text="End HRV")

        self.hist_tree.column("Date", width=150)
        self.hist_tree.column("Level", width=100)
        self.hist_tree.column("Verdict", width=250)
        self.hist_tree.column("HR Stats", width=120)
        self.hist_tree.column("HRV", width=80)

        self.hist_tree.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.hist_tree.yview)
        self.hist_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        records = self.db_get_history(self.user_id)
        for r in records:
            lvl_disp = bx.get_level_display(r['level'])
            full_level = f"{r['chart']}-{lvl_disp}"

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
        tk.Button(btn_frame, text="Delete Selected (Undo)", bg="#c0392b", fg="white", command=self.delete_history_item).pack(side=tk.RIGHT)

    def delete_history_item(self):
        selected = self.hist_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a record to delete.")
            return

        db_id = int(selected[0])
        conn = sqlite3.connect(USER_DB_FILE)
        c = conn.cursor()
        c.execute("SELECT MAX(id) FROM history WHERE user_id=?", (self.user_id,))
        max_id = c.fetchone()[0]
        c.execute("SELECT chart, level FROM history WHERE id=?", (db_id,))
        record_data = c.fetchone()
        conn.close()

        is_latest = (db_id == max_id)
        msg = "Are you sure you want to delete this record?"
        if is_latest:
            msg += "\n\n⚠️ UNDO MODE: This is your most recent session.\nDeleting it will revert your stats to what they were BEFORE this session."

        confirm = messagebox.askyesno("Confirm Delete", msg)
        if confirm:
            self.db_delete_history(db_id)
            if is_latest and record_data:
                chart, level = record_data
                self.db_update_level(self.user_id, chart, level)
            self.show_history_screen()

            # --- SCREEN 3: EXERCISE WIZARD ---
    def start_workout(self):
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

        threading.Thread(target=self.sensor_loop, daemon=True).start()
        self.run_exercise_screen()

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

        ttk.Label(frame, text=f"Exercise {idx+1}: {details['name']}", font=("Helvetica", 18, "bold")).pack()

        img_path = os.path.join(IMG_DIR, details['img'])
        if os.path.exists(img_path) and details['img']:
            try:
                load = Image.open(img_path)
                orig_w, orig_h = load.size
                target_w = 400
                target_h = int(target_w * (orig_h / orig_w))
                if target_h > 300:
                    target_h = 300
                    target_w = int(target_h * (orig_w / orig_h))
                load = load.resize((target_w, target_h), Image.Resampling.LANCZOS)
                render = ImageTk.PhotoImage(load)
                img_lbl = tk.Label(frame, image=render, bg="#2c3e50")
                img_lbl.image = render
                img_lbl.pack(pady=10)
            except: pass

        ttk.Label(frame, text=details['desc'], wraplength=700, justify=tk.CENTER, font=("Arial", 12)).pack(pady=10)

        info_frame = ttk.Frame(frame)
        info_frame.pack(pady=10)

        lbl_target = ttk.Label(info_frame, text=f"GOAL: {target}", font=("Courier", 32, "bold"), foreground="#f1c40f")
        lbl_target.pack(side=tk.LEFT, padx=20)

        self.time_left = duration
        self.lbl_timer = ttk.Label(info_frame, text=f"{self.time_left}s", font=("Courier", 32))
        self.lbl_timer.pack(side=tk.RIGHT, padx=20)

        self.lbl_hr = ttk.Label(frame, text="HR: --", font=("Arial", 16))
        self.lbl_hr.pack()
        self.lbl_advice = ttk.Label(frame, text="Get Ready...", foreground="cyan")
        self.lbl_advice.pack()

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
        top.transient(self)
        top.grab_set()

        tk.Label(top, text=f"Reps Completed for\n{details['name']}:", fg="white", bg="#34495e", font=("Arial", 12)).pack(pady=20)
        e_reps = tk.Entry(top, font=("Arial", 14), justify='center')
        e_reps.insert(0, str(self.target_reps_list[idx]))
        e_reps.pack(pady=10)
        e_reps.select_range(0, tk.END)
        e_reps.focus_force()

        self.temp_reps_buffer = None

        def save_reps(event=None):
            val_str = e_reps.get().strip()
            if not val_str: return
            try:
                self.temp_reps_buffer = int(val_str)
                top.destroy()
            except ValueError: pass

        btn = tk.Button(top, text="Confirm", command=save_reps, bg="#2ecc71")
        btn.pack(pady=20)
        top.bind('<Return>', save_reps)
        self.wait_window(top)

        if self.temp_reps_buffer is not None:
            self.reps_achieved.append(self.temp_reps_buffer)
            self.current_exercise_idx += 1
            self.run_exercise_screen()
        else:
            self.input_results()

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

            # --- SENSOR LOOP WITH REAL-TIME PACING ---
    def sensor_loop(self):
        while self.workout_active:
            if not self.sensor: break
            data = self.sensor.get_data()
            hr = data['bpm']
            rmssd = data['rmssd']
            rr = 0

            chart = self.user_data["current_chart"]
            level = self.user_data["current_level"]
            trend = f"C{chart}-Ex {self.current_exercise_idx+1}"

            # --- PACING LOGIC ---
            limit_95 = self.true_max_hr * 0.95
            limit_90 = self.true_max_hr * 0.90
            limit_60 = self.true_max_hr * 0.60

            status_text = "Zone OK"
            status_color = "#2ecc71" # Green
            log_status = "OK"

            if hr >= limit_95:
                status_text = "⚠️ DANGER! STOP NOW"
                status_color = "#e74c3c" # Red
                log_status = "CRITICAL"
            elif hr >= limit_90:
                status_text = "⚠️ Limit Reached - SLOW DOWN"
                status_color = "#e67e22" # Orange
                log_status = "WARNING"
            elif hr < limit_60 and self.current_exercise_idx == 4:
                status_text = "⚡ Push Harder!"
                status_color = "#f1c40f" # Yellow
                log_status = "LOW"

            if hr > 0:
                if self.current_exercise_idx < len(self.session_metrics):
                    self.session_metrics[self.current_exercise_idx]['hr'].append(hr)
                    self.session_metrics[self.current_exercise_idx]['rmssd'].append(rmssd)

                if self.logger:
                    state_str = f"Ch {chart} - Lvl {level}"
                    trend_name = self.session_metrics[self.current_exercise_idx]['name']
                    self.logger.log(hr, rmssd, rr, state_str, f"C{chart}-Ex {self.current_exercise_idx+1}: {trend_name}", log_status, "")

                try:
                    self.lbl_hr.config(text=f"♥ {hr} BPM")
                    self.lbl_advice.config(text=status_text, foreground=status_color)
                except: pass
            time.sleep(1)

    # --- THE REPORT GENERATOR ---
    def generate_detailed_report(self):
        report = []
        warnings = 0

        report.append("--- SESSION BREAKDOWN ---")

        session_peak_hr = 0

        for i, metric in enumerate(self.session_metrics):
            name = metric['name']
            hr_data = metric['hr']
            hrv_data = metric['rmssd']

            if not hr_data:
                report.append(f"{name}: No Data")
                continue

            avg_hr = sum(hr_data)/len(hr_data)
            max_hr = max(hr_data)
            session_peak_hr = max(session_peak_hr, max_hr)

            # Back Arch Artifact Filter
            if "Back Arch" in name or i == 2:
                hrv_str = "(Ignored)"
                avg_hrv = 999
            else:
                avg_hrv = sum(hrv_data)/len(hrv_data) if hrv_data else 0
                hrv_str = f"{avg_hrv:.1f} ms"

            status = "OK"
            if max_hr > (self.true_max_hr * 0.95):
                status = "INTENSE"
                warnings += 1
            if avg_hrv < 10 and "Back Arch" not in name:
                status += " / HIGH STRESS"

            line = f"{name}: Avg HR {int(avg_hr)} | Max {max_hr} | HRV {hrv_str}"
            if "INTENSE" in status or "STRESS" in status:
                line += f"\n   -> ⚠️ {status}"
            report.append(line)

        # --- NEW MAX HR DETECTION ---
        if session_peak_hr > self.true_max_hr and session_peak_hr < 220:
            report.append("\n📈 PHYSIOLOGICAL UPDATE:")
            report.append(f"You exceeded your estimated Max HR ({self.true_max_hr}).")
            report.append(f"New True Max set to: {session_peak_hr} bpm.")
            report.append("(Zones have been adjusted for next time.)")

            self.true_max_hr = session_peak_hr
            self.update_profile_max_hr(session_peak_hr)

            # Warn if they stayed there too long
            warnings += 1
            report.append("\n⚠️ ADVICE: You pushed to your absolute limit today. While impressive, 5BX should be sub-maximal. Dial it back 5% next time.")

        return "\n".join(report), warnings

    def update_profile_max_hr(self, new_max):
        self.bio_profile.max_hr = new_max
        if "current_stats" in self.profile_data:
            self.profile_data['current_stats']['max_hr'] = new_max
            try:
                with open(self.full_profile_path, 'w') as f:
                    json.dump(self.profile_data, f, indent=4)
            except: pass

    # --- SCREEN 4: ANALYSIS (UPDATED) ---
    def finish_workout(self):
        self.workout_active = False
        if self.logger: self.logger.stop()
        self._clear()

        missed_targets = 0
        for achieved, target in zip(self.reps_achieved, self.target_reps_list):
            if achieved < target: missed_targets += 1
        physical_pass = (missed_targets == 0)

        detailed_text, physio_warnings = self.generate_detailed_report()

        all_hr = [h for m in self.session_metrics for h in m['hr']]
        all_rmssd = [r for i, m in enumerate(self.session_metrics) for r in m['rmssd'] if i != 2]

        avg_hr = sum(all_hr)/len(all_hr) if all_hr else 0
        max_hr = max(all_hr) if all_hr else 0
        end_rmssd = all_rmssd[-1] if all_rmssd else 0

        chart = self.user_data["current_chart"]
        level = self.user_data["current_level"]

        try:
            next_chart, next_level = bx.get_next_level(chart, level)
            perf_chart, perf_level = bx.calculate_placement(self.reps_achieved)
        except:
            next_chart, next_level = chart, level
            perf_chart, perf_level = chart, level

        status = "MAINTAIN"
        color = "white"
        reason = ""

        # LOGIC TREE
        if max_hr > (self.true_max_hr * 0.95) or physio_warnings > 1:
            status = "DROP LEVEL (Safety)"
            color = "#ff5555"
            reason = "Physiological Cost too High. Do not advance."
            detailed_text += "\n\nRECOMMENDATION: Reduce intensity. Your HR is hitting the Red Zone."
            new_chart, new_level = chart, level

        elif not physical_pass:
            curr_val = (int(chart)*100) + int(level)
            perf_val = (int(perf_chart)*100) + int(perf_level)
            if perf_val < (curr_val - 2):
                status = "RECALIBRATE (Drop)"
                color = "#ff5555"
                reason = "Performance significantly below target."
                new_chart, new_level = perf_chart, perf_level
            else:
                status = "REPEAT LEVEL"
                color = "#f1c40f"
                reason = f"Missed {missed_targets} targets."
                new_chart, new_level = chart, level
        else:
            if int(perf_chart) > int(chart):
                status = f"PROMOTION! (Chart {int(chart)+1})"
                color = "#9b59b6"
                new_chart, new_level = str(int(chart) + 1), "1"
            elif int(perf_level) > int(next_level):
                status = f"LEAPFROG! (Level {bx.get_level_display(perf_level)})"
                color = "#9b59b6"
                new_chart, new_level = perf_chart, perf_level
            elif end_rmssd > self.bio_profile.baseline_rmssd:
                status = "DOUBLE LEVEL UP!"
                color = "#50fa7b"
                new_chart, new_level = bx.get_next_level(next_chart, next_level)
                if int(new_chart) > int(chart): new_chart, new_level = str(int(chart)+1), "1"
            else:
                status = "LEVEL UP"
                color = "#8be9fd"
                new_chart, new_level = next_chart, next_level

        next_disp = bx.get_level_display(new_level)
        db_verdict = f"{status} -> {new_chart}-{next_disp}"
        self.db_update_level(self.user_id, new_chart, new_level)
        self.db_add_history(self.user_id, chart, level, db_verdict, avg_hr, max_hr, end_rmssd)

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        ttk.Label(frame, text="Workout Complete", style="Header.TLabel").pack()
        ttk.Label(frame, text=f"VERDICT: {status}", font=("Arial", 16, "bold"), foreground=color).pack(pady=5)
        ttk.Label(frame, text=reason, font=("Arial", 12)).pack()

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        txt_report = tk.Text(text_frame, height=15, font=("Courier", 10), bg="#34495e", fg="white",
                             yscrollcommand=scrollbar.set)
        txt_report.pack(fill=tk.BOTH, expand=True)
        txt_report.insert(tk.END, detailed_text)
        scrollbar.config(command=txt_report.yview)

        ttk.Button(frame, text="Save & Exit", command=self.show_profile_linker).pack(pady=10)

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    def destroy(self):
        self.workout_active = False
        if self.sensor:
            try: self.sensor.stop()
            except: pass
        super().destroy()

if __name__ == "__main__":
    app = Bio5BXApp()
    app.mainloop()