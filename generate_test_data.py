import sqlite3
import json
import five_bx_data as bx
import datetime
import random

DB_FILE = "user_progress.db"

def create_test_user():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Create User (Start at Chart 2, Level 12 (A+) to allow demotion room)
    c.execute("INSERT OR IGNORE INTO users (name, age, linked_file, current_chart, current_level, goal_chart, goal_level) VALUES (?, ?, ?, ?, ?, ?, ?)",
              ("Test", 30, "test_profile.json", "2", "12", "6", "12"))
    conn.commit()
    
    c.execute("SELECT id FROM users WHERE name='Test'")
    uid = c.fetchone()['id']
    conn.close()
    return uid

def get_progression_desc(old_c, old_l, new_c, new_l, status, score_old, score_new):
    if status != "UP": return "MAINTAIN" 
    diff = score_new - score_old
    n_disp = bx.get_level_display(new_l)
    dest = f"C{new_c} {n_disp}"
    if diff > 1: return f"LEAPFROG to {dest}"
    if str(new_c) != str(old_c): return f"PROMOTION to {dest}"
    return f"LEVEL UP to {dest}"

def generate_data():
    uid = create_test_user()
    print(f"Generating FULL PROGRESSION data for User ID: {uid}")
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Clear existing history
    c.execute("DELETE FROM history WHERE user_id=?", (uid,))
    conn.commit()
    
    # Simulation Params (Start High)
    current_s_c, current_s_l = "2", "12"
    current_c_c, current_c_l = "2", "12"
    
    max_score = bx.get_total_score("6", "12")
    day = 0
    max_days = 20 # Short run, just to prove demotion
    
    # Start date
    start_date = datetime.date.today() - datetime.timedelta(days=20)
    
    # Tracking Fail Streaks
    consecutive_s = 0
    consecutive_c = 0
    
    while day < max_days:
        s_score = bx.get_total_score(current_s_c, current_s_l)
        c_score = bx.get_total_score(current_c_c, current_c_l)
        
        date_str = (start_date + datetime.timedelta(days=day)).strftime("%Y-%m-%d 18:00:00")
        
        # Targets
        s_targets = bx.get_targets(current_s_c, current_s_l)
        c_targets = bx.get_targets(current_c_c, current_c_l)
        
        s_outcome = "PASS"
        if 5 <= day <= 7: 
            s_outcome = "FAIL" # Force 3 Strikes on Days 5, 6, 7
            print(f"Day {day}: Forcing STRENGTH FAIL")

        c_outcome = "PASS" # Ignore Cardio failures for this test

        # Initialize reps
        reps = [0]*5

        # Regular Probabilities (if not forced)
        if s_outcome == "PASS":
            s_roll = random.random()
            if s_roll < 0.2: s_outcome = "FAIL" # 20%
            elif s_roll > 0.8: s_outcome = "CRUSH" # 20%
            
        if c_outcome == "PASS":
            c_roll = random.random()
            if c_roll < 0.2: c_outcome = "FAIL"
            elif c_roll > 0.8: c_outcome = "CRUSH"
        
        # If maxed out, force PASS (Maintain Max) unless specifically testing failure at top
        if s_score >= max_score: s_outcome = "PASS"
        if c_score >= max_score: c_outcome = "PASS"

        # Apply Strength
        for i in range(4):
            tgt = s_targets[i]
            if s_outcome == "FAIL": reps[i] = max(0, tgt - random.randint(1, 3))
            elif s_outcome == "CRUSH": reps[i] = tgt + random.randint(3, 8)
            else: reps[i] = tgt + random.randint(0, 2)
            
        # Calculate Logic
        
        # 1. Strength
        s_missed = 0
        for i in range(4):
            if reps[i] < s_targets[i]: s_missed += 1
            
        s_status = "MAINTAIN"
        s_new_c, s_new_l = current_s_c, current_s_l
        s_score_curr = bx.get_total_score(current_s_c, current_s_l)
        s_score_perf = s_score_curr
        
        if s_missed == 0 and s_score_curr < max_score:
            consecutive_s = 0 # Reset
            s_perf_c, s_perf_l = bx.calculate_strength_placement(reps, current_s_c)
            s_score_perf_calc = bx.get_total_score(s_perf_c, s_perf_l)
            
            # Force Next Check
            s_next_c, s_next_l = bx.get_next_level(current_s_c, current_s_l)
            s_score_next = bx.get_total_score(s_next_c, s_next_l)
            
            final_score = s_score_perf_calc
            final_c, final_l = s_perf_c, s_perf_l
            
            if s_score_perf_calc < s_score_next:
                final_score = s_score_next
                final_c, final_l = s_next_c, s_next_l
                
            if final_score > s_score_curr:
                s_status = "UP"
                s_new_c, s_new_l = final_c, final_l
                s_score_perf = final_score
        else:
            if s_missed > 0:
                consecutive_s += 1
                if consecutive_s >= 3:
                    s_status = "DOWN"
                    consecutive_s = 0
                    s_perf_c, s_perf_l = bx.calculate_strength_placement(reps, current_s_c)
                    s_new_c, s_new_l = s_perf_c, s_perf_l
                    s_score_perf = bx.get_total_score(s_new_c, s_new_l)
            else:
                 consecutive_s = 0 # Passed maxed out

        # 2. Cardio
        c_status = "MAINTAIN"
        c_new_c, c_new_l = current_c_c, current_c_l
        c_score_curr = bx.get_total_score(current_c_c, current_c_l)
        c_score_perf = c_score_curr
        
        # Pick Mode (Randomize)
        # 60% Stationary, 20% Run, 20% Walk
        # Unless forced fail implies a specific mode? No, assume mode is user choice.
        # We stick to one mode for a "session" usually.
        mode_roll = random.random()
        c_mode = "Stationary"
        if mode_roll > 0.8: c_mode = "Run"
        elif mode_roll > 0.6: c_mode = "Walk"
        
        # Generate Performance Data based on Mode
        c_val = 0
        c_tgt = 0 
        
        if c_mode == "Stationary":
            c_tgt = c_targets[4]
            if c_outcome == "FAIL": c_val = max(0, c_tgt - random.randint(10, 50))
            elif c_outcome == "CRUSH": c_val = c_tgt + random.randint(10, 30)
            else: c_val = c_tgt + random.randint(0, 5) # Pass
            reps[4] = c_val
        else:
            # Run/Walk - Need Target Time
            # We'll just assume a quick lookup
            bx_conn = sqlite3.connect(bx.DB_NAME)
            cursor = bx_conn.cursor()
            col = "ex5_run" if c_mode == "Run" else "ex5_walk"
            try:
                cursor.execute(f"SELECT {col} FROM ExerciseTimes WHERE chart=? AND level=?", (int(current_c_c), int(current_c_l)))
                row = cursor.fetchone()
                c_tgt = row[0] if row and row[0] else 300 # Fallback 5m (safer)
            except:
                c_tgt = 300
            bx_conn.close()
            
            # Time: Lower is Better
            if c_outcome == "FAIL": c_val = c_tgt + random.randint(10, 120) # Slower
            elif c_outcome == "CRUSH": c_val = max(60, c_tgt - random.randint(30, 90)) # Faster
            else: c_val = max(60, c_tgt - random.randint(5, 20)) # Pass (slightly faster)
            reps[4] = c_val

        # Evaluate Performance
        passed = False
        perf_c, perf_l = current_c_c, current_c_l
        
        if c_mode == "Stationary":
            passed = (c_val >= c_tgt)
        else:
            passed = (c_val <= c_tgt) # Time limit

        if passed and c_score_curr < max_score: 
             # FORCE UP if Passed
             c_status = "UP"
             
             # Metric 1: Next Level (Minimum Guarantee)
             c_next_c, c_next_l = bx.get_next_level(current_c_c, current_c_l)
             score_next = bx.get_total_score(c_next_c, c_next_l)
             
             # Metric 2: Placement (Leapfrog)
             if c_mode == "Stationary":
                 p_c, p_l = bx.calculate_cardio_placement(reps, current_c_c)
             else:
                 p_c, p_l = bx.calculate_cardio_time_placement(c_val, c_mode, current_c_c)
             score_place = bx.get_total_score(p_c, p_l)
             
             # Take Max
             if score_place > score_next:
                 c_new_c, c_new_l = p_c, p_l
                 c_score_perf = score_place
             else:
                 c_new_c, c_new_l = c_next_c, c_next_l
                 c_score_perf = score_next
        else:
            # Failed or Maxed
            if not passed:
                consecutive_c += 1
                if consecutive_c >= 3:
                     c_status = "DOWN"
                     consecutive_c = 0
                     # Recalculate based on failure input
                     if c_mode == "Stationary":
                        c_perf_c, c_perf_l = bx.calculate_cardio_placement(reps, current_c_c)
                     else:
                        c_perf_c, c_perf_l = bx.calculate_cardio_time_placement(c_val, c_mode, current_c_c)
                     
                     c_new_c, c_new_l = c_perf_c, c_perf_l
                     c_score_perf = bx.get_total_score(c_new_c, c_new_l)
            else:
                consecutive_c = 0 # Passed but maxed out?
        
        # Verdict Strings
        def get_v_desc(old_c, old_l, new_c, new_l, status, score_old, score_new):
             if status == "DOWN":
                 n_disp = bx.get_level_display(new_l)
                 return f"DEMOTION to C{new_c} {n_disp}"
             return get_progression_desc(old_c, old_l, new_c, new_l, status, score_old, score_new)

        s_v = get_v_desc(current_s_c, current_s_l, s_new_c, s_new_l, s_status, s_score_curr, s_score_perf)
        c_v = get_v_desc(current_c_c, current_c_l, c_new_c, c_new_l, c_status, c_score_curr, c_score_perf)
        final_verdict = f"Strength ({s_v}) / Cardio ({c_v})"
        
        # JSON Stats
        seg_data = []
        for i in range(5):
            seg_data.append({
                "name": f"Exercise {i+1}",
                "avg_hr": random.randint(120, 150),
                "max_hr": random.randint(155, 175),
                "hrv": random.randint(20, 60),
                "status": "INTENSE" if i == 4 and reps[4] > c_tgt else ""
            })
            
        stats_payload = {
            "version": "2.0",
            "segments": seg_data,
            "badges": [],
            "verdict_reason": "Synthetic Data Generation"
        }
        
        # Insert
        chart_str = f"{current_s_c}/{current_c_c}" if current_s_c != current_c_c else str(current_s_c)
        level_str = f"{current_s_l}/{current_c_l}" if current_s_l != current_c_l else str(current_s_l)
        
        # Prepare Insert Data
        final_type = "Standard"
        final_dur = 0
        if c_mode in ["Run", "Walk"]:
            final_type = c_mode
            final_dur = int(reps[4])
        
        c.execute("""
            INSERT INTO history 
            (user_id, timestamp, chart, level, verdict, ex1, ex2, ex3, ex4, ex5, ex5_type, ex5_duration, segment_stats, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, date_str, chart_str, level_str, final_verdict, 
              reps[0], reps[1], reps[2], reps[3], reps[4], 
              final_type, final_dur, json.dumps(stats_payload), ""))
        
        # Advance state for next day
        current_s_c, current_s_l = s_new_c, s_new_l
        current_c_c, current_c_l = c_new_c, c_new_l
        
        day += 1
        
    # Final User Update
    final_chart = f"{current_s_c}/{current_c_c}" if current_s_c != current_c_c else str(current_s_c)
    final_level = f"{current_s_l}/{current_c_l}" if current_s_l != current_c_l else str(current_s_l)
    
    # Correct columns used here - UPDATE SPLIT COLUMNS TOO
    c.execute("""
        UPDATE users 
        SET current_chart=?, current_level=?,
            strength_chart=?, strength_level=?,
            cardio_chart=?, cardio_level=?
        WHERE id=?
    """, (final_chart, final_level, 
          current_s_c, current_s_l,
          current_c_c, current_c_l,
          uid))
    conn.commit()
    conn.close()
    
    print(f"Done. Generated {day} records. Final Level: Chart {final_chart} Level {final_level}")

if __name__ == "__main__":
    generate_data()
