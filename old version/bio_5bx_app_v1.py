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
from PIL import Image, ImageTk

# Import your existing drivers
from ant_driver_v1 import AntHrvSensor
from ant_user_profile import UserProfile
import five_bx_data as bx

# Configuration
USER_DB_FILE = "../user_progress.db"
PROFILE_DIR = "../ant_user_profiles"
IMG_DIR = "../images"
CALIBRATION_EXPIRY_DAYS = 30


class Bio5BXApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bio-Adaptive 5BX Trainer")
        self.geometry("1000x850")
        self.configure(bg="#2c3e50")

        self.user_id = None
        self.username = None
        self.user_data = {}
        self.profile_data = {}
        self.calculated_age = 30

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
        self.hr_history = []
        self.rmssd_history = []
        self.reps_achieved = []
        self.target_reps_list = []
        self.temp_reps_buffer = None

        self._init_db()
        self.show_profile_linker()

    # --- LINUX COMPATIBLE SOUND ---
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
        else:  # Linux
            self.bell()
            print('\a')

    # --- SHARED UTILS ---
    def calculate_age(self, dob_str):
        try:
            birth_date = datetime.datetime.strptime(dob_str, "%Y-%m-%d").date()
            today = datetime.date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except:
            return 30

            # --- DATABASE MANAGEMENT (SQLite) ---

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
                         FOREIGN KEY(user_id) REFERENCES users(id)
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
            c.execute("""INSERT INTO users (name, age, linked_file, current_chart, current_level, goal_chart, goal_level)
                         VALUES (?, ?, ?, ?, ?, ?, ?)""",
                      (name, age, linked_file, c_chart, c_level, g_chart, g_level))
            conn.commit()
            conn.close()
        except:
            pass

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

        ttk.Label(frame, text="Select Calibration Profile", style="Header.TLabel", font=("Helvetica", 20, "bold")).pack(
            pady=20)

        profiles = glob.glob(os.path.join(PROFILE_DIR, "*_profile.json"))
        if not profiles:
            ttk.Label(frame, text="No Profiles Found!", foreground="red").pack()

        # --- NEW: CALIBRATION LAUNCHER ---
        btn_calib = tk.Button(frame, text="Run Calibration Wizard", bg="#95a5a6", font=("Arial", 10),
                              command=self.launch_calibration_app)
        btn_calib.pack(pady=5, anchor="ne")
        # ---------------------------------

        self.lst_profiles = tk.Listbox(frame, height=8, font=("Arial", 14))
        self.lst_profiles.pack(fill=tk.X, pady=10)

        for p in profiles:
            name = os.path.basename(p).replace("_profile.json", "").replace("_", " ").title()
            self.lst_profiles.insert(tk.END, name)

        self.btn_load = tk.Button(frame, text="Load User", bg="#2ecc71", font=("Arial", 12, "bold"),
                                  command=self.link_and_load)
        self.btn_load.pack(pady=20, fill=tk.X)

        self.lst_profiles.bind('<<ListboxSelect>>', self.check_profile_date)

    def launch_calibration_app(self):
        try:
            # Use sys.executable to ensure we use the same python interpreter (venv friendly)
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
        except:
            pass

    def link_and_load(self):
        selection = self.lst_profiles.curselection()
        if not selection:
            messagebox.showwarning("Select User", "Please select a user from the list.")
            return

        selected_text = self.lst_profiles.get(selection[0])
        clean_filename = selected_text.lower().replace(" ", "_") + "_profile.json"
        full_path = os.path.join(PROFILE_DIR, clean_filename)

        try:
            with open(full_path, 'r') as f:
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

        self.load_user_session(user_name, full_path)

    def load_user_session(self, name, profile_path):
        self.user_data = self.db_get_user(name)
        if not self.user_data:
            messagebox.showerror("Error", f"Could not load data for {name}")
            return

        self.user_id = self.user_data['id']
        self.username = name

        curr = self.profile_data.get('current_stats', {})
        self.bio_profile = UserProfile(name)
        self.bio_profile.max_hr = curr.get('max_hr', 180)
        self.bio_profile.baseline_rmssd = curr.get('baseline_rmssd', 40)

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

        # 1. BIO STATS ROW
        stats_frame = ttk.Frame(frame)
        stats_frame.pack(fill=tk.X, pady=5)

        curr = self.profile_data.get('current_stats', {})
        rhr = curr.get('resting_hr', '?')
        rmssd = curr.get('baseline_rmssd', '?')
        rec = curr.get('recovery_score', '?')

        lbl_stats = ttk.Label(stats_frame, text=f"❤️ RHR: {rhr}  |  ⚡ HRV: {rmssd}ms  |  🔋 Rec: {rec}",
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
            txt = f"{i + 1}. {details['name']}: {target} Reps"
            ttk.Label(preview, text=txt, font=("Arial", 12)).pack(anchor='w', padx=10, pady=5)

        btn = tk.Button(frame, text="START WORKOUT (Try Max Reps)", bg="#2ecc71", font=("Arial", 16, "bold"),
                        command=self.start_workout)
        btn.pack(fill=tk.X, pady=20)

        ttk.Label(frame, text="Tip: Do as many reps as possible to Fast-Track!", font=("Arial", 10, "italic")).pack()

    # --- SCREEN 2.5: HISTORY LOG ---
    def show_history_screen(self):
        self._clear()

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(frame, text=f"History: {self.username}", style="Header.TLabel", font=("Helvetica", 18, "bold")).pack(
            pady=10)

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
            if "LEAPFROG" in r['verdict']:
                tag = "super"
            elif "LEVEL UP" in r['verdict']:
                tag = "good"
            elif "PROMOTION" in r['verdict']:
                tag = "good"
            elif "REPEAT" in r['verdict']:
                tag = "bad"
            elif "DROP" in r['verdict']:
                tag = "drop"

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
        tk.Button(btn_frame, text="Delete Selected (Undo)", bg="#c0392b", fg="white",
                  command=self.delete_history_item).pack(side=tk.RIGHT)

    # --- UNDO / DELETE LOGIC ---
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
        else:
            msg += "\n(Deleting old history will not affect current level)"

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
        self.hr_history = []
        self.rmssd_history = []
        self.reps_achieved = []

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

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # 1. Header
        ttk.Label(frame, text=f"Exercise {idx + 1}: {details['name']}", font=("Helvetica", 18, "bold")).pack()

        # 2. Image (ASPECT RATIO FIX)
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
            except:
                pass

        # 3. Description
        ttk.Label(frame, text=details['desc'], wraplength=700, justify=tk.CENTER, font=("Arial", 12)).pack(pady=10)

        # 4. Target & Timer
        info_frame = ttk.Frame(frame)
        info_frame.pack(pady=10)

        lbl_target = ttk.Label(info_frame, text=f"GOAL: {target}", font=("Courier", 32, "bold"), foreground="#f1c40f")
        lbl_target.pack(side=tk.LEFT, padx=20)

        self.time_left = duration
        self.lbl_timer = ttk.Label(info_frame, text=f"{self.time_left}s", font=("Courier", 32))
        self.lbl_timer.pack(side=tk.RIGHT, padx=20)

        # 5. Live Bio
        self.lbl_hr = ttk.Label(frame, text="HR: --", font=("Arial", 16))
        self.lbl_hr.pack()
        self.lbl_advice = ttk.Label(frame, text="Get Ready...", foreground="cyan")
        self.lbl_advice.pack()

        # 6. Controls
        self.btn_action = tk.Button(frame, text="START TIMER", bg="#2ecc71", font=("Arial", 14, "bold"),
                                    command=self.start_timer_action)
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

        tk.Label(top, text=f"Reps Completed for\n{details['name']}:", fg="white", bg="#34495e",
                 font=("Arial", 12)).pack(pady=20)

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
            except ValueError:
                pass

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
            self.play_beep()  # <--- SOUND ADDED

    def sensor_loop(self):
        while self.workout_active:
            if not self.sensor: break
            data = self.sensor.get_data()
            hr = data['bpm']
            rmssd = data['rmssd']
            if hr > 0:
                self.hr_history.append(hr)
                self.rmssd_history.append(rmssd)
                try:
                    self.lbl_hr.config(text=f"♥ {hr} BPM")
                    max_hr = self.bio_profile.max_hr
                    if hr > (max_hr * 0.9):
                        self.lbl_advice.config(text="⚠️ TOO HIGH!", foreground="red")
                    elif hr < (max_hr * 0.6) and self.current_exercise_idx == 4:
                        self.lbl_advice.config(text="⚡ PUSH!", foreground="yellow")
                    else:
                        self.lbl_advice.config(text="✅ Zone OK", foreground="#2ecc71")
                except:
                    pass
            time.sleep(1)

    # --- SCREEN 4: ANALYSIS (WITH DESTINATION LOGGING) ---
    def finish_workout(self):
        self.workout_active = False
        self._clear()

        missed_targets = 0
        for achieved, target in zip(self.reps_achieved, self.target_reps_list):
            if achieved < target:
                missed_targets += 1

        physical_pass = (missed_targets == 0)

        avg_hr = sum(self.hr_history) / len(self.hr_history) if self.hr_history else 0
        max_hr = max(self.hr_history) if self.hr_history else 0
        end_rmssd = self.rmssd_history[-1] if self.rmssd_history else 0
        baseline = self.bio_profile.baseline_rmssd

        status = "MAINTAIN"
        color = "white"
        reason = ""

        chart = self.user_data["current_chart"]
        level = self.user_data["current_level"]

        try:
            next_chart, next_level = bx.get_next_level(chart, level)
            perf_chart, perf_level = bx.calculate_placement(self.reps_achieved)
        except Exception as e:
            next_chart, next_level = chart, level
            perf_chart, perf_level = chart, level

        # --- LOGIC ENGINE ---
        if max_hr > (self.bio_profile.max_hr * 0.95):
            status = "DROP LEVEL (Safety)"
            color = "#ff5555"
            reason = f"DANGER: Max HR {max_hr} BPM is unsafe. Reducing intensity."
            new_chart, new_level = chart, level

        elif not physical_pass:
            curr_val = (int(chart) * 100) + int(level)
            perf_val = (int(perf_chart) * 100) + int(perf_level)

            if perf_val < (curr_val - 2):
                status = "RECALIBRATE (Drop)"
                color = "#ff5555"
                reason = "Performance was significantly below target. Adjusting down."
                new_chart, new_level = perf_chart, perf_level
            else:
                status = "REPEAT LEVEL"
                color = "#f1c40f"
                reason = f"Missed {missed_targets} targets. Try again tomorrow."
                new_chart, new_level = chart, level

        else:
            # SUCCESS
            if int(perf_chart) > int(chart):
                status = f"PROMOTION! (Chart {int(chart) + 1})"
                color = "#9b59b6"
                reason = "Mastered this Chart. Moving to next Chart (Level 1)."
                new_chart = str(int(chart) + 1)
                new_level = "1"

            elif int(perf_level) > int(next_level):
                status = f"LEAPFROG! (Level {bx.get_level_display(perf_level)})"
                color = "#9b59b6"
                reason = "Crushed the targets! Skipping ahead."
                new_chart, new_level = perf_chart, perf_level

            elif end_rmssd > baseline:
                status = "DOUBLE LEVEL UP!"
                color = "#50fa7b"
                reason = "Elite Recovery detected. Skipping one level."
                new_chart, new_level = bx.get_next_level(next_chart, next_level)
                if int(new_chart) > int(chart):
                    new_chart = str(int(chart) + 1)
                    new_level = "1"

            else:
                status = "LEVEL UP"
                color = "#8be9fd"
                reason = "Solid Pass. Promoting."
                new_chart, new_level = next_chart, next_level

        # --- FIX: LOG THE DESTINATION IN HISTORY ---
        next_disp = bx.get_level_display(new_level)
        db_verdict = f"{status} -> {new_chart}-{next_disp}"
        # -------------------------------------------

        self.db_update_level(self.user_id, new_chart, new_level)
        self.db_add_history(self.user_id, chart, level, db_verdict, avg_hr, max_hr, end_rmssd)

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(frame, text="Workout Complete", style="Header.TLabel").pack(pady=10)

        res_text = (
            f"Physical: {'PASS' if physical_pass else 'MISS'}\n"
            f"Avg HR: {int(avg_hr)} bpm\n"
            f"Max HR: {max_hr} bpm\n"
            f"End HRV: {int(end_rmssd)} ms\n\n"
            f"VERDICT: {status}\n"
            f"(Next Session: Chart {new_chart} - {next_disp})"
        )
        ttk.Label(frame, text=res_text, font=("Courier", 16), justify=tk.CENTER).pack(pady=20)
        ttk.Label(frame, text=reason, foreground=color, font=("Arial", 12)).pack()

        ttk.Button(frame, text="Save & Exit", command=self.show_profile_linker).pack(pady=20)

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    def destroy(self):
        self.workout_active = False
        if self.sensor:
            try:
                self.sensor.stop()
            except:
                pass
        super().destroy()


if __name__ == "__main__":
    app = Bio5BXApp()
    app.mainloop()