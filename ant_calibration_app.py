import tkinter as tk
from tkinter import ttk, messagebox
import time
import json
import statistics
import os
import glob
import datetime
import shutil
import platform
import sys

# Import your existing drivers
# Ensure this points to the new robust driver we just fixed
from ant_driver import AntHrvSensor
from ant_user_profile import UserProfile

# Configuration
PROFILE_DIR = "ant_user_profiles"
BACKUP_DIR = "ant_user_profiles/backups"
PHASE_DURATIONS = {
    "REST": 60,
    "STRESS": 60,
    "EXERTION": 45,
    "RECOVERY": 60
}


class CalibrationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Biofeedback Calibration Wizard")
        self.geometry("600x800")
        self.configure(bg="#2c3e50")

        # Create dirs
        if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)
        if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)

        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#2c3e50")
        style.configure("TLabel", background="#2c3e50", foreground="white", font=("Helvetica", 12))
        style.configure("Header.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("BigMetric.TLabel", font=("Courier", 36, "bold"), foreground="white")
        style.configure("TButton", font=("Helvetica", 10))

        # Data State
        self.sensor = None
        self.user_name = ""
        self.user_dob = ""
        self.user_age = 30
        self.current_phase = ""
        self.is_recording = False
        self.dashboard_active = False  # For the live loop

        self.phase_data_hr = []
        self.phase_data_rmssd = []

        self.results = {
            "rest": {}, "stress": {}, "exertion": {}, "recovery": {}
        }

        self.setup_login_screen()
        
        # --- ROBUST STARTUP LOOP ---
        # Try to connect immediately, but keep retry-ing if resource busy
        self.dashboard_active = True 
        self.init_sensor_loop()

    def init_sensor_loop(self):
        # If we already have a working sensor, do nothing
        if self.sensor and self.sensor.status == "Active":
            return

        try:
            print("Attempting to Init Sensor...")
            if self.sensor: 
                try: self.sensor.stop() 
                except: pass
                
            self.sensor = AntHrvSensor()
            self.sensor.start()
            
            # Give it a moment to stabilize status
            self.after(500, self.check_startup_status)
        except Exception as e:
            print(f"Init Failed: {e}")
            if hasattr(self, 'lbl_device_dash'):
                self.lbl_device_dash.config(text=f"📡 Searching... (Retrying)", foreground="#e67e22")
            # Retry in 2s
            self.after(2000, self.init_sensor_loop)

    def check_startup_status(self):
        # Helper to check if it actually started or failed async
        if not self.sensor: return # Should not happen
        
        # Pull data to check status
        data = self.sensor.get_data()
        status = data.get('status', 'Error')
        
        if status == "Active" or status == "Initializing":
             print("Sensor Active!")
             bat = data.get('battery_volts')
             bat_state = data.get('battery_state', 'Unknown')
             msg = "📡 ANT+ Ready"
             if bat: msg += f" | 🔋 {bat}V ({bat_state})"
             
             if hasattr(self, 'lbl_device_dash'):
                self.lbl_device_dash.config(text=msg, foreground="#2ecc71")
             
             # Start the dashboard loop if not already running
             self.update_dashboard_loop()
        else:
             print(f"Sensor Status: {status}")
             if hasattr(self, 'lbl_device_dash'):
                self.lbl_device_dash.config(text=f"📡 {status}... (Retrying)", foreground="#e67e22")
             # Retry
             self.after(2000, self.init_sensor_loop)

    # --- SOUND ENGINE ---
    def play_beep(self):
        """Cross-platform beep"""
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

    # --- AGE CALCULATION ---
    def calculate_age(self, dob_str):
        try:
            birth_date = datetime.datetime.strptime(dob_str, "%Y-%m-%d").date()
            today = datetime.date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except ValueError:
            return None

    # --- SCREEN 1: LOGIN ---
    def setup_login_screen(self):
        self.clear_screen()
        self.dashboard_active = False  # Stop any background polling

        frame = ttk.Frame(self)
        frame.pack(expand=True, fill=tk.BOTH, padx=40)

        # --- NEW: HARDWARE STATUS LABEL ON START SCREEN ---
        self.lbl_device_dash = ttk.Label(frame, text="📡 Searching...", foreground="#e67e22", font=("Arial", 11))
        self.lbl_device_dash.pack(pady=5)
        # --------------------------------------------------

        ttk.Label(frame, text="Bio-Calibration", style="Header.TLabel").pack(pady=20)

        ttk.Label(frame, text="Select Existing Profile:", foreground="#bd93f9").pack(anchor='w')
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.X, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.lst_users = tk.Listbox(list_frame, height=5, font=("Arial", 12), yscrollcommand=scrollbar.set)
        self.lst_users.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self.lst_users.bind('<<ListboxSelect>>', self.on_user_select)
        scrollbar.config(command=self.lst_users.yview)

        self.load_profiles_list()

        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=20)

        ttk.Label(frame, text="Name (or New User):").pack(anchor='w')
        self.entry_name = ttk.Entry(frame, font=("Arial", 12))
        self.entry_name.pack(fill=tk.X, pady=5)

        ttk.Label(frame, text="Date of Birth (YYYY-MM-DD):").pack(anchor='w')
        self.entry_dob = ttk.Entry(frame, font=("Arial", 12))
        self.entry_dob.pack(fill=tk.X, pady=5)
        self.entry_dob.insert(0, "1980-01-01")

        self.btn_start = ttk.Button(frame, text="Start Calibration", command=self.start_calibration)
        self.btn_start.pack(pady=30, fill=tk.X)

    def load_profiles_list(self):
        profiles = glob.glob(os.path.join(PROFILE_DIR, "*_profile.json"))
        for p in profiles:
            name = os.path.basename(p).replace("_profile.json", "").replace("_", " ").title()
            self.lst_users.insert(tk.END, name)

    def on_user_select(self, event):
        selection = self.lst_users.curselection()
        if not selection: return

        name = self.lst_users.get(selection[0])
        self.entry_name.delete(0, tk.END)
        self.entry_name.insert(0, name)

        try:
            clean_filename = name.lower().replace(" ", "_") + "_profile.json"
            full_path = os.path.join(PROFILE_DIR, clean_filename)
            with open(full_path, 'r') as f:
                data = json.load(f)
                if "dob" in data:
                    self.entry_dob.delete(0, tk.END)
                    self.entry_dob.insert(0, data["dob"])
                else:
                    self.entry_dob.delete(0, tk.END)
            self.btn_start.config(text=f"Update Profile: {name}")
        except:
            pass

    # --- SCREEN 2: INSTRUCTIONS & SENSOR START ---
    def start_calibration(self):
        name = self.entry_name.get().strip()
        dob_str = self.entry_dob.get().strip()

        if not name:
            messagebox.showwarning("Input", "Please enter a name.")
            return

        calculated_age = self.calculate_age(dob_str)
        if calculated_age is None or calculated_age < 5 or calculated_age > 100:
            messagebox.showwarning("Input", "Invalid Date of Birth or Age.")
            return

        self.user_name = name.title()
        self.user_dob = dob_str
        self.user_age = calculated_age

        # Sensor should already be running from background loop
        if not self.sensor or self.sensor.status != "Active":
            # Just warning, but let loop handle it?
            # Or assume loop will catch it eventually.
            pass

        try:
            # self.sensor = AntHrvSensor() # REMOVED: Don't re-init
            # self.sensor.start()          # REMOVED: Already running
            
            self.dashboard_active = True  # Start the loop
            self.show_instruction("REST")
            self.update_dashboard_loop()  # Kick off the polling
        except Exception as e:
            messagebox.showerror("Error", f"ANT+ Stick not found: {e}")

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

        # --- NEW: HARDWARE STATUS LABEL ---
        self.lbl_device_dash = ttk.Label(frame, text="📡 Searching...", foreground="#95a5a6", font=("Arial", 10))
        self.lbl_device_dash.pack(pady=5)
        # ----------------------------------

        if phase == "STRESS":
            self.draw_necker_cube(frame)

        self.btn_next = ttk.Button(frame, text="BEGIN PHASE", command=self.run_phase_timer)
        self.btn_next.pack(pady=20)

        self.lbl_live = ttk.Label(frame, text="Waiting for signal...", foreground="yellow")
        self.lbl_live.pack()
        self.update_live_preview()

    # --- NEW: CONSISTENT STATUS LOOP ---
    def update_dashboard_loop(self):
        if not self.dashboard_active: return

        if self.sensor:
            data = self.sensor.get_data()
            manuf = data.get('manufacturer', 'Unknown')
            serial = data.get('serial')
            batt_v = data.get('battery_volts')
            uptime = data.get('uptime_hours')
            bpm = data.get('bpm', 0)
            status = data.get('status', 'Initializing')

            if status == "Active" or bpm > 0:
                txt = f"✅ {manuf} #{serial}" if serial else f"✅ {manuf}"
                if batt_v: txt += f" | 🔋 {batt_v}V ({batt_state})"
                if uptime and uptime > 0: txt += f" | ⏱ {uptime}h"
                if bpm > 0: txt += f" | ♥ Live HR: {bpm}"

                # Check if label exists before config (in case screen changed)
                if hasattr(self, 'lbl_device_dash'):
                    self.lbl_device_dash.config(text=txt, foreground="#2ecc71")
            else:
                if hasattr(self, 'lbl_device_dash'):
                    self.lbl_device_dash.config(text=f"📡 {status}...", foreground="#95a5a6")

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
        if self.is_recording or self.current_phase == "FINISHED":
            return

        try:
            data = self.sensor.get_data()
            self.lbl_live.config(text=f"♥ {data['bpm']} bpm  |  ⚡ {data['rmssd']:.3f} ms")
            self.after(1000, self.update_live_preview)
        except:
            pass

    # --- PHASE LOGIC ---
    def run_phase_timer(self):
        self.is_recording = True
        self.btn_next.config(state="disabled")
        self.phase_data_hr = []
        self.phase_data_rmssd = []

        duration = PHASE_DURATIONS[self.current_phase]
        self.remaining_time = duration

        self.record_loop()

    def record_loop(self):
        if self.remaining_time > 0:
            try:
                data = self.sensor.get_data()
                if data['bpm'] > 0:
                    self.phase_data_hr.append(data['bpm'])
                    self.phase_data_rmssd.append(data['rmssd'])

                self.lbl_live.config(
                    text=f"RECORDING... {self.remaining_time}s\n♥ {data['bpm']} | ⚡ {data['rmssd']:.3f}")
            except:
                self.lbl_live.config(text=f"RECORDING... {self.remaining_time}s\n(Sensor Signal Lost)")

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

    # --- SAVE PROFILE ---
    def save_profile(self):
        self.current_phase = "FINISHED"
        self.dashboard_active = False  # Stop loop
        self.clear_screen()

        profile = UserProfile(self.user_name)
        profile.calibrate(self.results['rest'], self.results['stress'], self.results['recovery'])
        
        # SYNC LOGIC with Main App: Max(220-Age, Measured Exertion)
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

        filename = f"{self.user_name.lower().replace(' ', '_')}_profile.json"
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
            shutil.copy(full_path, os.path.join(BACKUP_DIR, backup_name))

            try:
                with open(full_path, 'r') as f:
                    old_data = json.load(f)

                if "history" in old_data:
                    final_data["history"] = old_data["history"]

                if "current_stats" in old_data:
                    final_data["history"].append(old_data["current_stats"])
            except Exception as e:
                print(f"Error migrating: {e}")

        with open(full_path, 'w') as f:
            json.dump(final_data, f, indent=4)

        self.show_success_screen(profile, filename)

    def show_success_screen(self, profile, filename):
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(frame, text="Calibration Complete!", style="Header.TLabel", foreground="#50fa7b").pack(pady=10)

        res_text = (
            f"Profile Saved: {filename}\n"
            f"Calculated Age: {self.user_age}\n\n"
            f"Resting HR: {profile.resting_hr:.1f} bpm\n"
            f"Baseline HRV: {profile.baseline_rmssd:.3f} ms\n"
            f"Stress Threshold: >{profile.stress_hr_threshold:.1f} bpm\n"
            f"Max HR: {int(profile.max_hr)} bpm\n"
            f"Recovery Capacity: {profile.recovery_score} ms"
        )

        lbl = ttk.Label(frame, text=res_text, font=("Courier", 12), background="black", padding=10)
        lbl.pack(fill=tk.BOTH, expand=True, pady=10)

        ttk.Button(frame, text="Close", command=self.destroy).pack(pady=20)

    def clear_screen(self):
        for widget in self.winfo_children():
            widget.destroy()

    def destroy(self):
        self.dashboard_active = False
        if self.sensor:
            try:
                self.sensor.stop()
            except:
                pass
        super().destroy()


if __name__ == "__main__":
    app = CalibrationApp()
    app.mainloop()