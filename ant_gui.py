import time
import collections
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button
from matplotlib.patches import Rectangle
import tkinter as tk
from tkinter import filedialog
import json
import os
import csv
import glob
import datetime
import sys

# IMPORT YOUR DRIVERS
from ant_driver import AntHrvSensor
from ant_user_profile import UserProfile

# --- CONFIGURATION ---
HISTORY_SEC = 60
UPDATE_INTERVAL_MS = 250  # 4Hz
CONFIG_FILE = "ant_config.json"
PROFILE_DIR = "ant_user_profiles"
SESSION_DIR = "ant_sessions"

# --- TREND LOGIC ---
TRANSITION_MAP = {
    ("NEUTRAL", "STRESS"): ("⚠️ STRESS ONSET", "#ff5555"),
    ("STRESS", "FLOW"): ("🌊 COPING SUCCESS", "#8be9fd"),
    ("EXERTION", "ACTIVE RECOVERY"): ("🔋 VAGAL REBOUND", "#50fa7b"),
    ("EXERTION", "STRESS"): ("❌ FAILED RECOVERY", "#ffb86c"),
    ("ACTIVE RECOVERY", "DEEP ZEN"): ("🧘 SUCCESSFUL COOL-DOWN", "#50fa7b"),
    ("STRESS", "BURNOUT"): ("💀 SYSTEM CRASH", "#ff5555"),
    ("DEEP ZEN", "STRESS"): ("⚡ AROUSAL SPIKE", "#ffb86c"),
}


class SessionLogger:
    def __init__(self, user_name):
        self.user_name = user_name
        self.filename = None
        self.file = None
        self.writer = None

        if not os.path.exists(SESSION_DIR):
            os.makedirs(SESSION_DIR)

    def start(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(SESSION_DIR, f"session_{self.user_name}_{ts}.csv")

        self.file = open(self.filename, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow([
            "Timestamp", "HR_BPM", "RMSSD_MS", "Raw_RR_MS",
            "State", "Trend", "Status", "Raw_Packet_Hex"
        ])
        print(f"\n[LOGGER] Recording started: {self.filename}")

    def log(self, hr, rmssd, raw_rr, state, trend, status, raw_hex):
        if self.writer:
            self.writer.writerow([
                datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                hr, f"{rmssd:.1f}", raw_rr, state, trend, status, raw_hex
            ])

    def stop(self):
        if self.file:
            self.file.close()
            print(f"[LOGGER] Session saved: {self.filename}")
            self.file = None
            self.writer = None


class BiofeedbackApp:
    def __init__(self):
        # 1. Init Config & Folders
        self._ensure_dirs()

        # 2. Load Last Profile
        last_profile_path = self._load_config()
        self.user = self._load_profile_from_path(last_profile_path)

        self.logger = SessionLogger(self.user.name)

        print("Initializing Sensor...")
        self.sensor = AntHrvSensor()
        self.sensor.start()

        self.is_recording = False

        self.history_len = int(HISTORY_SEC * (1000 / UPDATE_INTERVAL_MS))
        self.hr_buffer = collections.deque(np.zeros(self.history_len), maxlen=self.history_len)
        self.rmssd_buffer = collections.deque(np.zeros(self.history_len), maxlen=self.history_len)

        self.last_state_label = "NEUTRAL"
        self.trend_message = "MONITORING (Passive)"
        self.trend_color = "gray"

        # Calculate dynamic Y-limit based on user profile
        self.y_limit = max(150, self.user.baseline_rmssd * 4)

        self.setup_gui()

    def _ensure_dirs(self):
        if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)
        if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    return data.get('last_profile_path', None)
            except:
                pass
        return None

    def _save_config(self, profile_path):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'last_profile_path': profile_path}, f)

    def _load_profile_from_path(self, path):
        if path and os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                p = UserProfile(data['name'])
                p.resting_hr = data.get('resting_hr', 60)
                p.baseline_rmssd = data.get('baseline_rmssd', 40)
                p.stress_hr_threshold = data.get('stress_hr_threshold', 80)
                p.max_hr = data.get('max_hr', 180)
                print(f"✅ Loaded Profile: {p.name}")
                return p
            except Exception as e:
                print(f"Error loading profile: {e}")

        print(f"Using Default Profile")
        return UserProfile("Default")

    def open_profile_selector(self, event):
        root = tk.Tk()
        root.withdraw()

        file_path = filedialog.askopenfilename(
            initialdir=PROFILE_DIR,
            title="Select Profile JSON",
            filetypes=[("JSON files", "*.json")]
        )

        root.destroy()

        if file_path:
            self.user = self._load_profile_from_path(file_path)
            self._save_config(file_path)
            self.logger = SessionLogger(self.user.name)

            # --- UPDATE MAP SCALE ---
            # Recalculate ceiling to fit this specific user
            self.y_limit = max(150, self.user.baseline_rmssd * 4)
            self.ax_map.set_ylim(0, self.y_limit)
            self.ax_rv.set_ylim(0, self.y_limit)
            self.ax_map.set_xlim(40, self.user.max_hr)
            self.ax_hr.set_ylim(40, self.user.max_hr)

            # Clear and Redraw Zones
            for p in list(self.ax_map.patches):
                p.remove()
            for t in list(self.ax_map.texts):
                t.remove()

            self.draw_regions()
            print(f"Switched user to {self.user.name}")

    def toggle_session(self, event):
        if not self.is_recording:
            # START
            print("\n>>> RECORDING STARTED <<<")
            self.is_recording = True
            self.logger.start()

            self.hr_buffer.clear()
            self.rmssd_buffer.clear()
            self.hr_buffer.extend(np.zeros(self.history_len))
            self.rmssd_buffer.extend(np.zeros(self.history_len))

            self.trend_message = "● RECORDING"
            self.trend_color = "#ff5555"
            self.txt_trend.set_text(self.trend_message)
            self.txt_trend.set_color(self.trend_color)

            self.btn_toggle.label.set_text("STOP & SAVE")
            self.btn_toggle.color = '#ff5555'
            self.btn_toggle.hovercolor = '#ff6b6b'

        else:
            # STOP
            print("\n>>> RECORDING STOPPED <<<")
            self.is_recording = False
            self.logger.stop()

            self.trend_message = "SESSION SAVED"
            self.trend_color = "yellow"

            self.btn_toggle.label.set_text("START NEW SESSION")
            self.btn_toggle.color = '#50fa7b'
            self.btn_toggle.hovercolor = '#69ff94'

            self.txt_status.set_text("SAVED")
            self.txt_status.set_color("yellow")

    def setup_gui(self):
        plt.style.use('dark_background')
        self.fig = plt.figure(figsize=(12, 10))

        grid = plt.GridSpec(4, 2, height_ratios=[1, 1, 2, 0.2])

        # --- GRAPHS ---
        self.ax_hr = self.fig.add_subplot(grid[0, :])
        self.line_hr, = self.ax_hr.plot([], [], color='#ff5555', lw=2)
        self.ax_hr.set_ylabel('HR (bpm)', color='#ff5555', fontweight='bold')
        self.ax_hr.set_ylim(40, self.user.max_hr)
        self.ax_hr.grid(True, alpha=0.2)

        self.ax_rv = self.fig.add_subplot(grid[1, :], sharex=self.ax_hr)
        self.line_rv, = self.ax_rv.plot([], [], color='#8be9fd', lw=2)
        self.ax_rv.set_ylabel('HRV (ms)', color='#8be9fd', fontweight='bold')
        self.ax_rv.set_ylim(0, self.y_limit)  # Dynamic Limit
        self.ax_rv.grid(True, alpha=0.2)

        # --- STATE MAP ---
        self.ax_map = self.fig.add_subplot(grid[2, :])
        self.ax_map.set_xlabel('Heart Rate (Speed)', fontsize=12)
        self.ax_map.set_ylabel('RMSSD (Flexibility)', fontsize=12)
        self.ax_map.set_xlim(40, self.user.max_hr)
        self.ax_map.set_ylim(0, self.y_limit)  # Dynamic Limit
        self.ax_map.grid(True, alpha=0.1)

        self.draw_regions()

        self.scat = self.ax_map.scatter([], [], c=[], cmap='cool', s=100, edgecolors='white', zorder=10)

        # --- TEXT ---
        self.txt_status = self.fig.text(0.5, 0.95, "SYSTEM READY", ha='center', fontsize=20, color='white',
                                        fontweight='bold')
        self.txt_trend = self.fig.text(0.5, 0.92, "", ha='center', fontsize=14, color='gray')
        self.txt_live = self.fig.text(0.95, 0.95, "Connecting...", ha='right', fontsize=12, color='gray',
                                      fontfamily='monospace')
        self.txt_profile = self.fig.text(0.05, 0.95, f"USER: {self.user.name.upper()}", ha='left', fontsize=12,
                                         color='#bd93f9', fontweight='bold')

        # --- BUTTONS ---
        ax_btn_rec = self.fig.add_axes([0.35, 0.02, 0.3, 0.06])
        self.btn_toggle = Button(ax_btn_rec, 'START RECORDING', color='#50fa7b', hovercolor='#69ff94')
        self.btn_toggle.label.set_color('black')
        self.btn_toggle.label.set_fontweight('bold')
        self.btn_toggle.on_clicked(self.toggle_session)

        ax_btn_prof = self.fig.add_axes([0.75, 0.02, 0.2, 0.06])
        self.btn_profile = Button(ax_btn_prof, 'CHANGE USER', color='0.3', hovercolor='0.5')
        self.btn_profile.label.set_color('white')
        self.btn_profile.on_clicked(self.open_profile_selector)

    def draw_regions(self):
        u = self.user

        # 1. EXERTION (Red)
        exertion_height = u.baseline_rmssd * 2.5
        self.ax_map.add_patch(
            Rectangle((u.stress_hr_threshold, 0), u.max_hr, exertion_height, color='#ff5555', alpha=0.1))
        self.ax_map.text(u.max_hr - 10, 10, "EXERTION", color='#ff5555', ha='right', fontweight='bold')

        # 2. STRESS (Orange)
        stress_height = u.baseline_rmssd * 0.6
        self.ax_map.add_patch(
            Rectangle((u.resting_hr, 0), u.stress_hr_threshold - u.resting_hr, stress_height, color='#ffb86c',
                      alpha=0.2))
        self.ax_map.text(u.stress_hr_threshold, 5, "STRESS", color='#ffb86c', ha='right', fontweight='bold')

        # 3. ZEN (Green)
        self.ax_map.add_patch(
            Rectangle((40, u.baseline_rmssd), (u.resting_hr + 5) - 40, self.y_limit, color='#50fa7b', alpha=0.1))
        self.ax_map.text(u.resting_hr, self.y_limit - 10, "ZEN", color='#50fa7b', ha='right', fontweight='bold')

        # 4. RECOVERY (Blue)
        recov_height = self.y_limit - exertion_height
        self.ax_map.add_patch(
            Rectangle((u.stress_hr_threshold, exertion_height), u.max_hr, recov_height, color='#8be9fd', alpha=0.1))
        self.ax_map.text(u.max_hr - 10, self.y_limit - 10, "RECOVERY", color='#8be9fd', ha='right', fontweight='bold')

    def update(self, frame):
        data = self.sensor.get_data()
        hr = data['bpm']
        rmssd = data['rmssd']
        raw_rr = data.get('raw_rr_ms', 0)
        raw_hex = data.get('raw_hex', "")
        staleness = data.get('staleness', 0)

        self.txt_profile.set_text(f"USER: {self.user.name.upper()}")

        live_color = "#50fa7b" if staleness < 2.0 and hr > 0 else "#ff5555"
        status_str = "ACTIVE" if staleness < 2.0 else "NO SIGNAL"
        self.txt_live.set_text(f"LIVE: {hr} BPM | {rmssd:.0f} ms | {status_str}")
        self.txt_live.set_color(live_color)

        if not self.is_recording:
            return self.line_hr, self.line_rv, self.scat, self.txt_status, self.txt_trend, self.txt_live, self.txt_profile

        state_raw = self.user.get_state(hr, rmssd)

        signal_status = "OK"
        if staleness > 1.5:
            signal_status = "LOST"
            state_raw = "⚠️ SIGNAL LOST"
        elif "NOISE" in state_raw:
            signal_status = "NOISE"

        self.logger.log(hr, rmssd, raw_rr, state_raw, self.trend_message, signal_status, raw_hex)

        state_clean = state_raw.split(" ")[-1]
        if "RECOVERY" in state_raw: state_clean = "ACTIVE RECOVERY"
        if "EXERTION" in state_raw: state_clean = "EXERTION"
        if "STRESS" in state_raw: state_clean = "STRESS"
        if "ZEN" in state_raw: state_clean = "DEEP ZEN"
        if "NOISE" in state_raw: state_clean = "NOISE"

        if state_clean != self.last_state_label and hr > 0 and state_clean != "NOISE":
            key = (self.last_state_label, state_clean)
            if key in TRANSITION_MAP:
                self.trend_message, self.trend_color = TRANSITION_MAP[key]
            else:
                self.trend_message = f"{self.last_state_label} ➔ {state_clean}"
                self.trend_color = "gray"
            self.last_state_label = state_clean

        self.hr_buffer.append(hr)
        self.rmssd_buffer.append(rmssd)

        x = np.arange(len(self.hr_buffer))
        self.line_hr.set_data(x, self.hr_buffer)
        self.line_rv.set_data(x, self.rmssd_buffer)
        self.ax_hr.set_xlim(0, len(self.hr_buffer))

        tail_len = 20
        if len(self.hr_buffer) > tail_len:
            tail_x = list(self.hr_buffer)[-tail_len:]
            tail_y = list(self.rmssd_buffer)[-tail_len:]

            self.scat.set_offsets(np.c_[tail_x, tail_y])

            if "NOISE" in state_raw:
                self.scat.set_array(np.full(len(tail_x), 0.5))
                self.scat.set_cmap('gray')
            else:
                self.scat.set_array(np.linspace(0, 1, len(tail_x)))
                self.scat.set_cmap('cool')

        self.txt_status.set_text(state_raw)
        if "LOST" in state_raw or "NOISE" in state_raw:
            self.txt_status.set_color("red")
        elif "RECOVERY" in state_raw:
            self.txt_status.set_color("#50fa7b")
        elif "EXERTION" in state_raw:
            self.txt_status.set_color("#ff5555")
        elif "STRESS" in state_raw:
            self.txt_status.set_color("#ffb86c")
        else:
            self.txt_status.set_color("white")

        self.txt_trend.set_text(self.trend_message)
        self.txt_trend.set_color(self.trend_color)

        return self.line_hr, self.line_rv, self.scat, self.txt_status, self.txt_trend, self.txt_live, self.txt_profile

    def run(self):
        ani = FuncAnimation(self.fig, self.update, interval=UPDATE_INTERVAL_MS, blit=False, cache_frame_data=False)
        plt.show()
        if self.sensor:
            self.sensor.stop()


if __name__ == "__main__":
    app = BiofeedbackApp()
    app.run()