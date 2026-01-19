import sqlite3
import os

DB_NAME = "databases/exercises.db3"

# Time limits in seconds (2m, 1m, 1m, 1m, 6m)
TIME_LIMITS = [120, 60, 60, 60, 360]

# AGE TARGETS (Maintenance Goals)
# User request: Age 52 -> Chart 2 C+ (Level 6)
AGE_TARGETS = {
    (15, 15): ("4", "1"),
    (16, 17): ("4", "6"),
    (18, 25): ("5", "5"),
    (26, 29): ("4", "12"),
    (30, 34): ("4", "4"),
    (35, 39): ("3", "8"),
    (40, 44): ("3", "5"),
    (45, 49): ("2", "12"),
    (50, 60): ("2", "6"),
    (61, 99): ("1", "6")
}

# ELITE TARGETS (Flying Crew) - Roughly 1 full chart higher or maxed
ELITE_TARGETS = {
    (18, 24): ("5", "9"),
    (25, 29): ("5", "3"),
    (30, 34): ("4", "8"), 
    (35, 39): ("4", "4"), 
    (40, 44): ("3", "12"), 
    (45, 49): ("3", "9") 
}

# DISPLAY MAP
LEVEL_MAP = {
    1: "D-", 2: "D", 3: "D+",
    4: "C-", 5: "C", 6: "C+",
    7: "B-", 8: "B", 9: "B+",
    10: "A-", 11: "A", 12: "A+"
}


def get_age_goal(age):
    for (min_a, max_a), target in AGE_TARGETS.items():
        if min_a <= age <= max_a:
            return target
    return ("1", "12")

def get_total_score(chart, level):
    return (int(chart) * 12) + int(level)

BADGE_DIR = os.path.join("images", "badges")

def get_badge_image_path(is_elite, min_a, max_a):
    """
    Returns path to badge image if exists, else None.
    Elite: FC{min}-{max}.png or FC{min}.png
    Std: {min}-{max}.png or {min}.png
    """
    prefix = "FC" if is_elite else ""
    suffix = f"{min_a}" if min_a == max_a else f"{min_a}-{max_a}"
    filename = f"{prefix}{suffix}.png"
    return os.path.join(BADGE_DIR, filename) if os.path.exists(os.path.join(BADGE_DIR, filename)) else None

def get_superman_targets(age):
    """
    Returns a list of potential Superman targets (younger than user).
    Each item: {
        'type': 'Standard'|'Elite', 
        'score': int, 
        'title': str, 
        'target': (chart, level), 
        'image_name': str
    }
    """
    targets = []
    
    # helper for age string
    def _fmt_age(min_a, max_a):
        return f"{min_a}" if min_a == max_a else f"{min_a}-{max_a}"
        
    # 1. Standard Targets
    for (min_a, max_a), target in AGE_TARGETS.items():
        if age > max_a:
            targets.append({
                'type': 'Standard',
                'score': get_total_score(target[0], target[1]),
                'title': f"🦸 SUPERMAN (Age {_fmt_age(min_a, max_a)} Level)",
                'target': target,
                'image_name': "SUPERMAN.png"
            })
            
    # 2. Elite Targets
    for (min_a, max_a), target in ELITE_TARGETS.items():
        if age > max_a:
            targets.append({
                'type': 'Elite',
                'score': get_total_score(target[0], target[1]),
                'title': f"🚀 SUPERMAN ELITE (Age {_fmt_age(min_a, max_a)} Level)",
                'target': target,
                'image_name': "ELITESUPERMAN.png"
            })
            
    return targets

def check_milestones(age, s_old_c, s_old_l, s_new_c, s_new_l, c_old_c, c_old_l, c_new_c, c_new_l):
    badges = []
    
    # Calculate scores
    s_score_old = get_total_score(s_old_c, s_old_l)
    s_score_new = get_total_score(s_new_c, s_new_l)
    c_score_old = get_total_score(c_old_c, c_old_l)
    c_score_new = get_total_score(c_new_c, c_new_l)
    
    def check_threshold(target_c, target_l, title, is_elite=False, age_range=None, custom_img=None):
        t_score = get_total_score(target_c, target_l)
        
        # Did we cross it?
        s_crossed = (s_score_old < t_score <= s_score_new)
        c_crossed = (c_score_old < t_score <= c_score_new)
        
        if not s_crossed and not c_crossed: return
        
        # Determine status
        s_pass = (s_score_new >= t_score)
        c_pass = (c_score_new >= t_score)
        
        suffix = ""
        if s_pass and c_pass:
            if s_crossed and c_crossed: suffix = "\n(FULL UNLOCK!)"
            elif s_crossed: suffix = "\n(STRENGTH COMPLETED)"
            elif c_crossed: suffix = "\n(CARDIO COMPLETED)"
        elif s_crossed:
            suffix = "\n(STRENGTH ONLY)"
        elif c_crossed:
            suffix = "\n(CARDIO ONLY)"
            
        final_text = f"{title}{suffix}"
        
        # Image
        img = None
        if custom_img:
            img = os.path.join(BADGE_DIR, custom_img)
        elif age_range:
            img = get_badge_image_path(is_elite, age_range[0], age_range[1])
            
        badges.append({'text': final_text, 'image': img})

    # 1. Check Age Targets
    for (min_a, max_a), target in AGE_TARGETS.items():
        if min_a <= age <= max_a:
             # This is the user's primary age target
             check_threshold(target[0], target[1], "🏆 AGE TARGET REACHED", False, (min_a, max_a))
    
    # 2. Check Elite Targets
    has_elite = False
    e_c, e_l = "1", "1"
    e_range = (age, age)
    for (min_a, max_a), t in ELITE_TARGETS.items():
        if min_a <= age <= max_a:
            e_c, e_l = t
            e_range = (min_a, max_a)
            has_elite = True
            break
            
    if has_elite:
        check_threshold(e_c, e_l, "✈️ FLYING CREW ELITE", True, e_range)
        
    # 3. Check Superman Targets (Younger Age Groups)
    # Check if user exceeds their own age target and meets younger targets
    user_target_c, user_target_l = get_age_goal(age)
    user_target_score = get_total_score(user_target_c, user_target_l)
    
    if s_score_new > user_target_score or c_score_new > user_target_score:
        # Collect candidates separately for the two schemes
        std_candidates = []
        elite_candidates = []
        
        # Use Helper
        all_targets = get_superman_targets(age)
        
        for t in all_targets:
            t_score = t['score']
            target = t['target']
            
            # Did we cross it? (Strict: Must meet BOTH now, and wasn't meeting BOTH before)
            s_pass = (s_score_new >= t_score)
            c_pass = (c_score_new >= t_score)
            s_was_pass = (s_score_old >= t_score)
            c_was_pass = (c_score_old >= t_score)
            
            # Unlocked if passing BOTH now, but wasn't passing BOTH before
            unlocked = (s_pass and c_pass) and (not s_was_pass or not c_was_pass)
            
            if unlocked:
                candidate = {
                    'score': t_score,
                    'title': t['title'],
                    'target': target,
                    'elite': (t['type'] == 'Elite'),
                    'img': t['image_name']
                }
                
                if t['type'] == 'Standard':
                    std_candidates.append(candidate)
                else:
                    elite_candidates.append(candidate)
                    
        # 3. Award Best of Each Scheme
        
        # Best Standard
        if std_candidates:
            std_candidates.sort(key=lambda x: x['score'], reverse=True)
            best = std_candidates[0]
            check_threshold(best['target'][0], best['target'][1], best['title'], best['elite'], None, best['img'])

        # Best Elite
        if elite_candidates:
            elite_candidates.sort(key=lambda x: x['score'], reverse=True)
            best = elite_candidates[0]
            check_threshold(best['target'][0], best['target'][1], best['title'], best['elite'], None, best['img'])
        
    return badges


def get_earned_badges(s_chart, s_level, c_chart, c_level, user_age=100):
    """
    Returns a list of dicts: {'title': str, 'details': str, 'image': path, 'status': str, ...}
    Status can be: "FULLY ACHIEVED", "Strength Only", "Cardio Only"
    """
    badges = []
    
    s_score = get_total_score(str(s_chart), str(s_level))
    c_score = get_total_score(str(c_chart), str(c_level))
    
    # Track Best Superman Performance
    best_superman_std = None # (score, badge_dict)
    best_superman_elite = None
    
    # Check all Age Targets
    for (min_a, max_a), target in AGE_TARGETS.items():
        t_c, t_l = target
        t_score = get_total_score(t_c, t_l)
        
        strength_pass = (s_score >= t_score)
        cardio_pass = (c_score >= t_score)
        
        if strength_pass or cardio_pass:
            status = "PARTIAL"
            status_text = ""
            if strength_pass and cardio_pass:
                status_text = "✨ FULLY ACHIEVED ✨"
            elif strength_pass:
                status_text = "💪 Strength Only"
            else:
                status_text = "❤️ Cardio Only"

            age_str = f"{min_a}" if min_a == max_a else f"{min_a}-{max_a}"
            lvl_disp = get_level_display(t_l)
            
            title = f"Age {age_str} Standard"
            details = f"Chart {t_c} / Level {lvl_disp}"
            img = get_badge_image_path(False, min_a, max_a)
            
            # Score: Base score
            badge_entry = {'title': title, 'details': details, 'image': img, 'type': 'Standard', 'score': t_score, 'status': status_text}
            badges.append(badge_entry)
            
            # Check Superman (Pass + Younger Age)
            # (Refactored to separate block below)
            
    # Check all Elite Targets
    for (min_a, max_a), target in ELITE_TARGETS.items():
        t_c, t_l = target
        t_score = get_total_score(t_c, t_l)
        
        strength_pass = (s_score >= t_score)
        cardio_pass = (c_score >= t_score)
        
        if strength_pass or cardio_pass:
            status = "PARTIAL"
            status_text = ""
            if strength_pass and cardio_pass:
                status_text = "✨ FULLY ACHIEVED ✨"
            elif strength_pass:
                status_text = "💪 Strength Only"
            else:
                status_text = "❤️ Cardio Only"
                
            age_str = f"{min_a}" if min_a == max_a else f"{min_a}-{max_a}"
            lvl_disp = get_level_display(t_l)
            
            title = f"Age {age_str} Elite"
            details = f"Chart {t_c} / Level {lvl_disp}"
            img = get_badge_image_path(True, min_a, max_a)
            
            badges.append({'title': title, 'details': details, 'image': img, 'type': 'Elite', 'score': t_score + 500, 'status': status_text})

            # Check Elite Superman
            # (Refactored to separate block below)

    # Calculate Best Supermans using Helper (Cleaner Logic)
    all_superman_targets = get_superman_targets(user_age)
    
    for t in all_superman_targets:
        t_score = t['score']
        target = t['target']
        
        # Check against user score to see if achieved
        t_c, t_l = target
        t_score_val = get_total_score(t_c, t_l)
        
        strength_pass = (s_score >= t_score_val)
        cardio_pass = (c_score >= t_score_val)
        
        # STRICT: Must have BOTH to earn Superman Badge
        if strength_pass and cardio_pass:
            status_text = "✨ FULLY ACHIEVED ✨"

            details_sup = f"Chart {t_c} / Level {get_level_display(t_l)}"
            
            # Construct Candidate
            candidate = (t_score_val, {
                'title': t['title'],
                'details': details_sup + "\n" + status_text,
                'image': os.path.join(BADGE_DIR, t['image_name']),
                'type': 'Superman' if t['type'] == 'Standard' else 'Superman Elite',
                'score': t_score_val + (1000 if t['type'] == 'Standard' else 2000),
                'status': status_text
            })
            
            # Update Best (Max Algorithm)
            if t['type'] == 'Standard':
                if best_superman_std is None or t_score_val > best_superman_std[0]:
                    best_superman_std = candidate
            else:
                if best_superman_elite is None or t_score_val > best_superman_elite[0]:
                    best_superman_elite = candidate

    # Append Best Supermans
    if best_superman_std: badges.append(best_superman_std[1])
    if best_superman_elite: badges.append(best_superman_elite[1])
    
    # Sort by score desc
    badges.sort(key=lambda x: x['score'], reverse=True)
    return badges


def get_level_display(level_int):
    try:
        val = int(level_int)
        return LEVEL_MAP.get(val, str(val))
    except:
        return str(level_int)


# --- DATABASE CONNECTION ---


def get_exercise_detail(chart, idx, variant="Standard"):
    if not os.path.exists(DB_NAME):
        return {"name": f"Exercise {idx + 1}", "desc": "DB Not Found", "img": ""}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Handle Split Chart String (e.g., "2/1")
    s_chart = str(chart)
    if "/" in s_chart:
        parts = s_chart.split("/")
        if len(parts) >= 2:
            if idx < 4: s_chart = parts[0]
            else: s_chart = parts[1]
            
    # Resolve DB Exercise ID
    db_ex_id = idx + 1
    if idx == 4: # Exercise 5
        if "Run" in variant and "Stationary" not in variant:
             db_ex_id = 6
        elif "Walk" in variant:
             db_ex_id = 7
    
    # Retrieve name from DB with fallback
    try:
        cursor.execute("SELECT instructions, image, name FROM Instructions WHERE chart=? AND exercise=?", (s_chart, db_ex_id))
        row = cursor.fetchone()
        conn.close()

        if row:
            desc = row[0]
            img_file = row[1] if row[1] else f"c{chart}_ex{idx + 1}.png"
            db_name = row[2]  # New Column
            
            # Generic Fallback (used only if DB name is truly missing)
            fallback_names = ["Flexibility", "Sit-up", "Back Arch", "Push-up", "Cardio"]

            # Logic: Use DB name -> Generic Fallback -> "Exercise X"
            fallback_name = fallback_names[idx] if idx < len(fallback_names) else f"Exercise {idx+1}"
            name_to_use = db_name if db_name else fallback_name
            
            # Override Name if Variant (Still applies dynamic logic)
            if idx == 4:
                if db_ex_id == 6: name_to_use = "Run (Distance)"
                elif db_ex_id == 7: name_to_use = "Walk (Distance)"
                
            return {"name": name_to_use, "desc": desc, "img": img_file}
    except:
        pass
    return {"name": f"Exercise {idx + 1}", "desc": "See Manual", "img": ""}


def get_targets(chart, level):
    if not os.path.exists(DB_NAME): return [5, 5, 5, 5, 100, 0, 0]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Check if new columns exist first (backward compatibility safely)
        # But we know we updated DB. Let's just try-catch or assume V10 DB.
        cursor.execute("SELECT ex1, ex2, ex3, ex4, ex5, ex5_run, ex5_walk FROM ExerciseTimes WHERE chart=? AND level=?", (chart, level))
        row = cursor.fetchone()
        conn.close()
        # Returns [ex1, ex2, ex3, ex4, ex5, run_time, walk_time]
        return list(row) if row else [5, 5, 5, 5, 100, 0, 0]
    except:
        # Fallback to old schema if fails
        try:
             cursor.execute("SELECT ex1, ex2, ex3, ex4, ex5 FROM ExerciseTimes WHERE chart=? AND level=?", (chart, level))
             row = cursor.fetchone()
             conn.close()
             return list(row) + [0, 0] if row else [5, 5, 5, 5, 100, 0, 0]
        except:
             if conn: conn.close()
             return [5, 5, 5, 5, 100, 0, 0]


def get_next_level(current_chart, current_level):
    c = int(current_chart)
    l = int(current_level)
    if l < 12:
        return str(c), str(l + 1)
    elif c < 6:
        return str(c + 1), "1"
    else:
        return "6", "12"


# --- THE NEW LEAPFROG LOGIC ---
def calculate_placement(reps_achieved, current_chart="1"):
    """
    Finds the highest Level *within the current chart* where ALL requirements are met.
    reps_achieved: [r1, r2, r3, r4, r5]
    current_chart: str or int
    """
    if not os.path.exists(DB_NAME): return str(current_chart), "1"

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # "Weakest Link" Logic:
    # Find all levels where the target <= what user did
    # Sort by hardest (Level Desc) within CURRENT CHART.
    
    sql = """
    SELECT chart, level 
    FROM ExerciseTimes 
    WHERE chart = ?
      AND ex1 <= ? 
      AND ex2 <= ? 
      AND ex3 <= ? 
      AND ex4 <= ? 
      AND ex5 <= ?
    ORDER BY level DESC
    LIMIT 1
    """

    try:
        # Prepend current_chart to args
        args = [str(current_chart)] + list(reps_achieved)
        cursor.execute(sql, tuple(args))
        row = cursor.fetchone()
        conn.close()

        if row:
            return str(row[0]), str(row[1])
        else:
            # If they didn't meet even the lowest level requirements
            return "1", "1"
    except Exception as e:
        print(f"Placement Error: {e}")
        return "1", "1"
def calculate_strength_placement(reps_list, current_chart="1"):
    """
    Check placement based ONLY on Exercises 1-4 (Strength).
    reps_list: [r1, r2, r3, r4, r5] (we only use 0-3)
    """
    if not os.path.exists(DB_NAME): return str(current_chart), "1"
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Check Ex 1-4
    sql = """
    SELECT chart, level 
    FROM ExerciseTimes 
    WHERE chart = ?
      AND ex1 <= ? 
      AND ex2 <= ? 
      AND ex3 <= ? 
      AND ex4 <= ?
    ORDER BY level DESC
    LIMIT 1
    """
    try:
        args = [str(current_chart)] + list(reps_list[:4])
        cursor.execute(sql, tuple(args))
        row = cursor.fetchone()
        conn.close()
        if row: return str(row[0]), str(row[1])
        return str(current_chart), "1"
    except:
        if conn: conn.close()
        return str(current_chart), "1"

def calculate_cardio_placement(reps_list, current_chart="1"):
    """
    Check placement based ONLY on Exercise 5 (Cardio).
    reps_list: [r1, r2, r3, r4, r5] (we only use 4)
    """
    if not os.path.exists(DB_NAME): return str(current_chart), "1"
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Check Ex 5 Only
    sql = """
    SELECT chart, level 
    FROM ExerciseTimes 
    WHERE chart = ?
      AND ex5 <= ?
    ORDER BY level DESC
    LIMIT 1
    """
    try:
        args = [str(current_chart), reps_list[4]]
        cursor.execute(sql, tuple(args))
        row = cursor.fetchone()
        conn.close()
        if row: return str(row[0]), str(row[1])
        return str(current_chart), "1"
    except:
        if conn: conn.close()
        return str(current_chart), "1"

# Helper to map Charts to Run/Walk Distances
def get_run_walk_distance_group(chart, mode):
    # Returns a list of Charts that share the same distance for this mode
    # based on CARDIO_CONFIG
    c = str(chart)
    group = []
    
    # Run: Chart 1 (0.5m), Chart 2-6 (1m)
    if "Run" in mode:
        if c == "1": return ["1"]
        else: return ["2", "3", "4", "5", "6"]
        
    # Walk: Chart 1 (1m), Chart 2-4 (2m). (Charts 5-6 have no walk)
    if "Walk" in mode:
        if c == "1": return ["1"]
        else: return ["2", "3", "4"]
        
    return [c]

def calculate_cardio_time_placement(time_secs, mode, current_chart):
    if not os.path.exists(DB_NAME): return str(current_chart), "1"
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Determine Valid Charts (Same Distance)
    valid_charts = get_run_walk_distance_group(current_chart, mode)
    placeholders = ','.join('?' for _ in valid_charts)
    
    # 2. Select Max Level where Target Time >= User Time (Lower is Better for User)
    col = "ex5_run" if "Run" in mode else "ex5_walk"
    
    sql = f"""
    SELECT chart, level 
    FROM ExerciseTimes 
    WHERE chart IN ({placeholders})
      AND {col} >= ?
      AND {col} > 0
    ORDER BY chart DESC, level DESC
    LIMIT 1
    """
    
    try:
        args = valid_charts + [time_secs]
        cursor.execute(sql, tuple(args))
        row = cursor.fetchone()
        conn.close()
        
        if row: return str(row[0]), str(row[1])
        
        # If no result, it means user didn't beat ANY target in the group?
        # Or maybe they are slower than Level 1?
        # Fallback to Level 1 of lowest chart in group? 
        # Or Just return Current (Maintain).
        return str(current_chart), "1" # Fallback
        
    except:
        if conn: conn.close()
        return str(current_chart), "1"
# Used for UI Labels. Logic assumes 'ex5_run' and 'ex5_walk' columns exist.
CARDIO_CONFIG = {
    "1": {"run": "1/2 Mile (0.8 km) Run", "walk": "1 Mile (1.6 km) Walk"},
    "2": {"run": "1 Mile (1.6 km) Run", "walk": "2 Mile (3.2 km) Walk"},
    "3": {"run": "1 Mile (1.6 km) Run", "walk": "2 Mile (3.2 km) Walk"},
    "4": {"run": "1 Mile (1.6 km) Run", "walk": "2 Mile (3.2 km) Walk"},
    "5": {"run": "1 Mile (1.6 km) Run", "walk": None},
    "6": {"run": "1 Mile (1.6 km) Run", "walk": None}
}

def get_cardio_config(chart):
    # Returns dict or default
    return CARDIO_CONFIG.get(str(chart), {"run": "Run", "walk": "Walk"})

def get_time_target(chart, level, mode):
    """
    Returns time target in seconds for Chart/Level/Mode (Run/Walk).
    """
    if not os.path.exists(DB_NAME): return 600
    
    col = "ex5_run" if "Run" in mode else "ex5_walk"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT {col} FROM ExerciseTimes WHERE chart=? AND level=?", (chart, level))
        row = cursor.fetchone()
    except:
        row = None
    conn.close()
    
    if row and row[0]: return row[0]
    return 600 # Fallback
