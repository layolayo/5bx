class UserProfile:
    def __init__(self, name):
        self.name = name
        # Default Generic Values (Overwritten after calibration)
        self.resting_hr = 60
        self.max_hr = 180
        self.baseline_rmssd = 40
        self.stress_hr_threshold = 80
        self.recovery_score = 50

    def calibrate(self, rest_data, stress_data, recovery_data):
        """
        Updates thresholds based on the Calibration Protocol.
        """
        self.resting_hr = rest_data['avg_hr']
        self.baseline_rmssd = rest_data['avg_rmssd']

        # Stress threshold is usually 15% above resting HR with lower HRV
        self.stress_hr_threshold = self.resting_hr * 1.15

        # Recovery Capacity (High number = Fit)
        self.recovery_score = recovery_data['peak_rmssd']

    def get_state(self, current_hr, current_rmssd):
        """
        Personalized Analysis Logic with Dynamic Filters
        """
        # 1. ARTIFACT TRAP (Dynamic)
        # Old Rule: If HR > 110 and RMSSD > 90 -> Noise.
        # New Rule: If HR > 110 and RMSSD > 4x Baseline (or 250ms cap) -> Noise.
        # This prevents fit users (High Baseline) from getting flagged as noise.
        noise_ceiling = max(250, self.baseline_rmssd * 4.0)

        if current_hr > 110 and current_rmssd > noise_ceiling:
            return "⚠️ SIGNAL NOISE"

        # 2. INTENSE EXERTION (Zone 3+)
        if current_hr > 115:
            # Vagal Rebound check: Lowered from 2.0x to 1.5x to catch subtle recovery
            if current_rmssd > (self.baseline_rmssd * 1.5):
                return "🔋 ACTIVE RECOVERY"
            return "🏃 EXERTION"

        # 3. WARM-UP / MODERATE ACTIVITY (Zone 2)
        if current_hr > 100:
            if current_rmssd > (self.baseline_rmssd * 1.8):
                return "🔋 ACTIVE RECOVERY"
            return "🏃 EXERTION"

        # 4. STRESS / ACTIVITY
        if current_hr > self.stress_hr_threshold:
            if current_rmssd < (self.baseline_rmssd * 0.6):
                return "⚠️ STRESS/ACTIVITY"
            return "😐 NEUTRAL"

        # 5. DEEP ZEN
        if current_hr <= (self.resting_hr + 5) and current_rmssd > self.baseline_rmssd:
            return "🧘 DEEP ZEN"

        return "😐 NEUTRAL"