import threading
import struct
import collections
import math
import time
from openant.easy.node import Node
from openant.easy.channel import Channel
from openant.devices import ANTPLUS_NETWORK_KEY


class AntHrvSensor:
    def __init__(self):
        self.running = False
        self.bpm = 0
        self.rr_ms = 0
        self.rmssd = 0.0
        self.status = "Initializing"

        # --- METADATA FIELDS ---
        self.manufacturer_id = None
        self.serial_number = None
        self.model_number = None
        self.hw_version = None
        self.sw_version = None
        self.battery_voltage = None
        self.battery_status = "Unknown"
        # -----------------------

        self.raw_rr_ms = 0
        self.last_packet_hex = ""

        self.rr_buffer = collections.deque(maxlen=30)
        self.filter_buffer = collections.deque(maxlen=5)
        self.consecutive_rejections = 0

        self.node = None
        self.channel = None
        self.thread = None  # Track thread for joining

        self.last_beat_time = None
        self.last_beat_count = None
        self.last_data_time = time.time()

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stops the driver and waits for clean USB release"""
        self.running = False

        # 1. Signal the Node to stop (breaks the loop)
        if self.node:
            try:
                self.node.stop()
            except:
                pass

        # 2. CRITICAL: Wait for thread to clean up USB resources
        # If we don't wait, Python kills the thread while it holds the USB handle
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def get_data(self):
        """Returns data snapshot with metadata"""
        time_since_update = time.time() - self.last_data_time

        status_out = self.status
        if time_since_update > 4.0 and self.status == "Active":
            status_out = "Signal Lost"
            self.bpm = 0

        # Manufacturer Map
        manuf_name = "Unknown"
        if self.manufacturer_id == 1:
            manuf_name = "Garmin"
        elif self.manufacturer_id == 123:
            manuf_name = "Polar"
        elif self.manufacturer_id == 33:
            manuf_name = "Wahoo"
        elif self.manufacturer_id is not None:
            manuf_name = f"ID {self.manufacturer_id}"

        return {
            'bpm': self.bpm,
            'rmssd': self.rmssd,
            'rr_ms': self.rr_ms,
            'status': status_out,
            'manufacturer': manuf_name,
            'serial': self.serial_number,
            'battery_volts': self.battery_voltage,
            'battery_state': self.battery_status,
            'sw_version': self.sw_version
        }

    def _on_data(self, data):
        self.last_data_time = time.time()

        try:
            self.last_packet_hex = bytes(data).hex()
        except:
            self.last_packet_hex = ""

        # 1. PARSE METADATA PAGES
        page = data[0] & 0x7F

        if page == 7:  # Battery
            coarse = data[3] & 0x0F
            fractional = data[2] / 256.0
            self.battery_voltage = round(coarse + fractional, 2)
            state_map = {1: "New", 2: "Good", 3: "Ok", 4: "Low", 5: "Critical"}
            self.battery_status = state_map.get((data[3] & 0x70) >> 4, "Unknown")

        elif page == 2:  # Manufacturer
            self.manufacturer_id = data[1]
            self.serial_number = (data[3] << 8) | data[2]

        elif page == 3:  # Version
            self.hw_version = data[1]
            self.sw_version = data[2]
            self.model_number = data[3]

        # 2. PARSE HR
        self.bpm = data[7]

        # 3. PARSE RR (Timing)
        beat_count = data[6]
        beat_time_raw = (data[5] << 8) | data[4]
        beat_time = beat_time_raw / 1024.0

        if self.last_beat_time is not None:
            if beat_time < self.last_beat_time:
                beat_time += 64.0

            if beat_count != self.last_beat_count:
                delta = beat_time - self.last_beat_time
                self.raw_rr_ms = int(delta * 1000)

                # Disconnect Filter (>1.5s gap)
                if delta > 1.5:
                    self.filter_buffer.clear()
                    self.last_beat_time = beat_time_raw / 1024.0
                    self.last_beat_count = beat_count
                    return

                if self._is_valid_beat(delta):
                    self.rr_ms = self.raw_rr_ms
                    self.rr_buffer.append(self.rr_ms)
                    self.filter_buffer.append(delta)
                    self.rmssd = self._calculate_rmssd_safe()
                    self.status = "Active"

        self.last_beat_time = beat_time_raw / 1024.0
        self.last_beat_count = beat_count

    def _is_valid_beat(self, rr_sec):
        if rr_sec < 0.27 or rr_sec > 1.5: return False
        if len(self.filter_buffer) > 0:
            avg = sum(self.filter_buffer) / len(self.filter_buffer)
            if abs(rr_sec - avg) > (avg * 0.3):
                self.consecutive_rejections += 1
                return False
        self.consecutive_rejections = 0
        return True

    def _calculate_rmssd_safe(self):
        if len(self.rr_buffer) < 2: return 0.0
        try:
            diffs = [self.rr_buffer[i] - self.rr_buffer[i - 1] for i in range(1, len(self.rr_buffer))]
            sq_diffs = [d * d for d in diffs]
            return math.sqrt(sum(sq_diffs) / len(sq_diffs))
        except:
            return 0.0

    def _run_loop(self):
        try:
            self.node = Node()
            self.node.set_network_key(0, ANTPLUS_NETWORK_KEY)
            self.channel = self.node.new_channel(Channel.Type.BIDIRECTIONAL_RECEIVE)
            self.channel.on_broadcast_data = self._on_data
            self.channel.on_burst_data = self._on_data

            # Use Wildcard to ensure connection
            self.channel.set_id(0, 0, 0)

            self.channel.set_rf_freq(57)
            self.channel.set_period(8070)
            self.channel.open()
            self.node.start()  # Blocks here until stopped

        except Exception as e:
            self.status = f"Error: {e}"
        finally:
            # --- CLEANUP ALWAYS RUNS ---
            self.running = False
            if self.channel:
                try:
                    self.channel.close()
                except:
                    pass
            if self.node:
                try:
                    self.node.stop()
                except:
                    pass
            # Note: Node.stop() usually releases the USB interface in openant