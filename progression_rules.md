# 5BX Progression Rules

This document outlines the algorithms used to determine level progression in the Bio-Adaptive 5BX App.

## 1. The Core Rule: "Meet the Target"

The fundamental rule of 5BX is simple: **You must meet the target repetitions (or time) for your current level to advance.**

-   **Pass**: If you perform >= Target Reps (or <= Target Time), you qualify for promotion.
-   **Miss**: If you perform < Target Reps, you **MAINTAIN** your current level. You do not drop down unless you choose to, but you cannot advance.

## 2. Progression Types

When you pass a level, the system calculates *how well* you passed to determine your new level.

### A. LEVEL UP (Standard Progression)
- **Condition**: You met the target target for your *current* level.
- **Result**: You move to the absolute **next level** (e.g., C1 A- -> C1 A).
- **Logic**: The system guarantees at least a 1-step advancement if the target is met.

### B. LEAPFROG (Accelerated Progression)
- **Condition**: Your performance was strong enough to pass a *higher* level than the one you just unlocked.
- **Result**: You skip levels (e.g., C1 A- -> C1 A+).
- **Logic**:
1.  The app checks the database for the **highest level** within your current chart where your performance met (or exceeded) the targets for **ALL** exercises.
2.  If this "Max Performance Level" is higher than the standard "Next Level", you are awarded a "LEAPFROG" to that specific level.
3.  *Note*: Internally, the app uses a "Rank ID" (Chart × 12 + Level) to compare levels, but your performance is judged strictly against the specific rep targets for each exercise.

---

## 3. Split Levels (Strength vs. Cardio)

The 5BX App operates in "Split Mode," assessing Strength (Exercises 1-4) and Cardio (Exercise 5) independently.

### Strength Verdict
-   **Exercises**: 1, 2, 3, 4.
-   **Rule**: You must meet the target reps for **ALL 4** exercises to advance.
-   **Failure**: If you miss the target for even *one* exercise (e.g., Ex 3), the verdict is **MAINTAIN**.
-   **Success**: If all 4 are passed, you advance based on your total score.

### Cardio Verdict
-   **Exercise**: 5 (Stationary, Run, or Walk).
-   **Stationary Rule**: You must meet the target **Reps** (e.g., 400).
-   **Run/Walk Rule**: You must meet or beat the target **Time** (e.g., run 1 mile in 8:00 or less).
-   **Failure**: If reps are too low or time is too slow, the verdict is **MAINTAIN**.

### Combined Result
Your session ending screen will show a split verdict:
> **Strength (LEAPFROG to C2 B+) / Cardio (MAINTAIN)**

This allows you to progress in Strength while holding steady in Cardio (or vice versa) until you are ready to move up.

---

## 4. Historical Data Note

When viewing **History Logs**, you may notice a discrepancy between the **Verdict** and the **Level performed next time**.

-   **The Verdict**: Tells you what the app *recommends* (calculated based on that day's performance).
-   **The Next Record**: Shows what you *actually did* on the next session.

**Why they might differ:**
-   **Old Data**: Migration scripts recalculate verdicts using modern rules, but they cannot change the past facts of which level you actually performed.
-   **User Choice**: You may have manually selected a different level than recommended.
-   **Legacy Rules**: Older versions of the app might have had different targets, so you didn't advance then, even though modern rules say you should have.

## 5. Changing Charts

The 5BX system is divided into **6 Charts**, each with **12 Levels**. Moving from one Chart to the next is a major milestone.

-   **Requirement**: You must reach and pass **Level 12 (A+)** of your current Chart.
-   **The Step Up**: Once you complete Level 12, your next promotion will be to **Level 1 (D-)** of the *next* Chart.
-   **No Skipping**: You cannot "Leapfrog" across charts. Even if your performance is excellent, you must complete the final level of Chart X before starting Chart X+1.
-   **New Challenges**: Moving to a new chart often introduces new exercise variations or significantly higher repetition targets (especially for Chart 2 -> 3). Be prepared for the difficulty spike!
