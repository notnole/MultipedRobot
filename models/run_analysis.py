"""
CoM Optimization Model - Main Analysis Script
Sweeps center of mass position and produces performance plots.

Usage: python run_analysis.py
Output: figures saved to code/models/output/
"""
import os
import sys
import math
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))

from config import RobotConfig
from physics_downhill import (
    time_downhill, transition_check,
    normal_forces_on_flat, normal_forces_on_slope
)
from physics_bars import (
    step_climb_energy, velocity_loss_per_bar, time_crossing_one_bar, impact_stagger
)
from physics_settling import (
    bounce_after_bar, settling_distance, turn_traction, time_through_turn
)
from physics_uphill import (
    backward_tip_check, traction_check, terminal_velocity, time_uphill,
    normal_forces_uphill, drive_force_at_speed
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

g = 9.81


# ============================================================
# FLAT SECTION: drive from A to B with servo ramp-up
# ============================================================
def time_flat_section(cfg, distance, v_entry=0.0):
    """Time to cover a flat section with motor drive.

    Euler integration with servo ramp-up and rolling resistance.
    Returns (time, exit_velocity).
    """
    m = cfg.total_mass
    R = cfg.wheel_radius
    dt = 0.0005
    v = v_entry
    x = 0.0
    t = 0.0
    t_since_start = 0.0  # track ramp from entry (reset on re-acceleration)
    F_rolling = cfg.mu_rolling * m * g

    while x < distance and t < 30.0:
        # Servo ramp: limits effective no-load speed
        ramp = min(t / cfg.servo_accel_time, 1.0) if cfg.servo_accel_time > 0 else 1.0
        v_max_current = cfg.v_max * ramp

        omega_wheel = v / R
        omega_max = v_max_current / R
        if omega_max > 0 and omega_wheel < omega_max:
            T_stall = cfg.wheel_torque_stall
            T_wheel = T_stall * (1 - omega_wheel / omega_max)
            F_drive = 2 * T_wheel / R
        else:
            F_drive = 0.0

        # Traction limit
        N_rear = m * g * (cfg.wheelbase - cfg.x_com) / cfg.wheelbase
        F_drive = min(F_drive, cfg.mu_static * N_rear)

        a = (F_drive - F_rolling) / m
        v = max(v + a * dt, 0.0)
        v = min(v, v_max_current)
        x += v * dt
        t += dt

    return t, v


def time_braking(cfg, v_start, v_target):
    """Time and distance to brake from v_start to v_target.

    Braking force = friction (locked wheels or motor braking).
    Returns (time, distance).
    """
    if v_start <= v_target:
        return 0.0, 0.0

    m = cfg.total_mass
    # Braking with motor reversal or friction
    F_brake = cfg.mu_static * m * g * 0.5  # assume 50% of max braking
    a_brake = F_brake / m

    dv = v_start - v_target
    t_brake = dv / a_brake
    d_brake = v_start * t_brake - 0.5 * a_brake * t_brake**2

    return t_brake, d_brake


# ============================================================
# TOTAL TRACK TIME
# ============================================================
def total_track_time(cfg):
    """Compute total estimated track time.

    Sequence:
    1. Downhill (motors engaged, gravity + motor)
    2. Flat to bar 1 (accelerate/maintain speed)
    3. Bar 1 crossing
    4. Flat section + decelerate for turn
    5. U-turn at reduced speed
    6. Accelerate + bar 2 crossing
    7. Flat approach to uphill
    8. Uphill climb

    Returns dict with per-section times and total.
    """
    result = {}

    # 1. Downhill
    t_down, v_down = time_downhill(cfg)
    result['t_downhill'] = t_down
    result['v_after_downhill'] = v_down

    # 2. Flat section to bar 1 (~20 cm estimated)
    flat_to_bar1 = 0.20
    t_flat1, v_at_bar1 = time_flat_section(cfg, flat_to_bar1, v_down)
    result['t_flat1'] = t_flat1
    result['v_at_bar1'] = v_at_bar1

    # 3. Bar 1 + recovery
    t_bar1, v_after_bar1 = time_crossing_one_bar(cfg, v_at_bar1)
    t_bar1 += cfg.bar_recovery_time  # time to regain control after bar
    v_after_bar1 *= 0.5  # significant speed loss during recovery/realignment
    result['t_bar1'] = t_bar1
    result['v_after_bar1'] = v_after_bar1

    # 4. Flat section to turn (~30 cm) + decelerate for turn
    flat_to_turn = 0.30
    t_flat2, v_before_turn = time_flat_section(cfg, flat_to_turn, v_after_bar1)
    result['t_flat_to_turn'] = t_flat2

    # 5. U-turn (includes deceleration to turn speed)
    t_turn, v_after_turn = time_through_turn(cfg, v_before_turn)
    result['t_turn'] = t_turn
    result['v_after_turn'] = v_after_turn

    # 6. Accelerate from turn speed toward bar 2 (~20 cm)
    flat_to_bar2 = 0.20
    t_flat3, v_at_bar2 = time_flat_section(cfg, flat_to_bar2, v_after_turn)
    result['t_flat_to_bar2'] = t_flat3

    # Bar 2 + recovery
    t_bar2, v_after_bar2 = time_crossing_one_bar(cfg, v_at_bar2)
    t_bar2 += cfg.bar_recovery_time
    v_after_bar2 *= 0.5
    result['t_bar2'] = t_bar2
    result['v_after_bar2'] = v_after_bar2

    # 7. Flat approach to uphill (~10 cm) — re-accelerate
    flat_to_uphill = 0.10
    t_flat4, v_at_uphill = time_flat_section(cfg, flat_to_uphill, v_after_bar2)
    result['t_flat_to_uphill'] = t_flat4

    # 8. Uphill climb
    t_up, v_exit = time_uphill(cfg, v_entry=v_at_uphill)
    result['t_uphill'] = t_up
    result['v_exit'] = v_exit

    # Total
    result['t_total'] = (t_down + t_flat1 + t_bar1 +
                         t_flat2 + t_turn +
                         t_flat3 + t_bar2 + t_flat4 + t_up)

    return result


# ============================================================
# PRINT ANALYSIS
# ============================================================
def print_analysis(cfg):
    """Print detailed section-by-section analysis."""
    print("=" * 70)
    print("CoM OPTIMIZATION MODEL - SECTION-BY-SECTION ANALYSIS")
    print("=" * 70)
    print()
    print(f"Robot mass:      {cfg.total_mass*1000:.0f} g")
    print(f"Wheelbase:       {cfg.wheelbase*1000:.0f} mm")
    print(f"Wheel radius:    {cfg.wheel_radius*1000:.0f} mm")
    print(f"CoM position:    x={cfg.x_com*1000:.1f} mm, z={cfg.z_com*1000:.1f} mm")
    print(f"Gear ratio:      1:{cfg.gear_ratio:.0f} (speed-up)")
    print(f"Motor:           {cfg.servo_no_load_rpm:.0f} RPM, {cfg.servo_stall_torque:.2f} Nm")
    print(f"Wheel:           {cfg.wheel_rpm:.0f} RPM, v_max={cfg.v_max*100:.1f} cm/s")
    print(f"Wheel torque:    {cfg.wheel_torque_stall:.4f} Nm/motor ({cfg.wheel_torque_stall/0.0981:.2f} kg-cm)")
    print(f"Max drive force: {cfg.max_drive_force:.1f} N (at stall)")
    print(f"Servo accel:     {cfg.servo_accel_time:.1f} s ramp-up")
    print()

    x_comp, z_comp = cfg.compute_com_from_components()
    print(f"CoM from components: x={x_comp*1000:.1f} mm, z={z_comp*1000:.1f} mm")
    print()

    # Downhill
    print("--- DOWNHILL ---")
    t_d, v_d = time_downhill(cfg)
    print(f"  Time:          {t_d:.2f} s")
    print(f"  Exit velocity: {v_d*100:.1f} cm/s")
    trans = transition_check(cfg, v_d)
    print(f"  Transition:    front overload {trans['front_overload_factor']:.2f}x, "
          f"rear lifts: {trans['rear_lifts']}")
    print()

    # Bar crossing
    print("--- BAR CROSSING ---")
    climb = step_climb_energy(cfg)
    print(f"  Torque needed:  {climb['tau_climb_kgcm']:.2f} kg-cm per wheel")
    print(f"  Torque avail:   {cfg.wheel_torque_stall/0.0981:.2f} kg-cm (at stall)")
    print(f"  Safety factor:  {climb['safety_factor_stall']:.2f}x (stall)")
    print(f"  Min velocity:   {climb['v_min_energy_ms']*100:.1f} cm/s (energy, no motor)")
    print(f"  Impact stagger: {impact_stagger(cfg)*1000:.0f} mm")
    print(f"  Rear wt/wheel:  {climb['W_per_rear_wheel_N']:.2f} N")
    print()

    # Settling
    print("--- POST-BAR SETTLING ---")
    bounce = bounce_after_bar(cfg)
    print(f"  Bounce amp:    {bounce['amplitude_mm']:.2f} mm")
    print(f"  Natural freq:  {bounce['f_natural_Hz']:.1f} Hz")
    print(f"  Settle (95%%):  {bounce['t_settle_95pct_s']:.3f} s")
    print()

    # Turn
    print("--- U-TURN ---")
    v_est = cfg.v_max * 0.5
    trac = turn_traction(cfg, v_est)
    print(f"  At {v_est*100:.0f} cm/s:")
    print(f"    Front grip margin: {trac['front_grip_margin']:.1f}x")
    print(f"    Rear grip margin:  {trac['rear_grip_margin']:.1f}x")
    print(f"    Max safe speed:    {trac['v_max_turn']*100:.0f} cm/s")
    print()

    # Uphill
    print("--- UPHILL ---")
    tip = backward_tip_check(cfg)
    print(f"  Tips backward:   {tip['tips_over']} "
          f"(margin: {tip['safety_margin_deg']:.1f} deg)")
    trac_up = traction_check(cfg)
    print(f"  Traction margin: {trac_up['traction_margin']:.2f}x")
    v_term = terminal_velocity(cfg)
    print(f"  Terminal vel:    {v_term*100:.1f} cm/s")
    t_up, v_exit = time_uphill(cfg)
    print(f"  Climb time:      {t_up:.2f} s (from rest)")
    print()

    # Total
    result = total_track_time(cfg)
    print("--- TOTAL TRACK TIME ---")
    print(f"  Downhill:        {result['t_downhill']:.2f} s  (exit {result['v_after_downhill']*100:.0f} cm/s)")
    print(f"  Flat->bar 1:     {result['t_flat1']:.2f} s")
    print(f"  Bar 1:           {result['t_bar1']:.2f} s")
    print(f"  Flat->turn:      {result['t_flat_to_turn']:.2f} s")
    print(f"  U-turn:          {result['t_turn']:.2f} s")
    print(f"  Flat->bar 2:     {result['t_flat_to_bar2']:.2f} s")
    print(f"  Bar 2:           {result['t_bar2']:.2f} s")
    print(f"  Flat->uphill:    {result['t_flat_to_uphill']:.2f} s")
    print(f"  Uphill:          {result['t_uphill']:.2f} s")
    print(f"  -------------------------")
    print(f"  TOTAL:           {result['t_total']:.2f} s")
    print()


# ============================================================
# SWEEP FUNCTIONS
# ============================================================
def sweep_x_com(cfg_base, x_range, masses=None):
    if masses is None:
        masses = [cfg_base.total_mass]

    results = {}
    for m in masses:
        times = []
        for x in x_range:
            cfg = cfg_base.with_com(x, cfg_base.z_com).with_mass(m)
            tip = backward_tip_check(cfg)
            if tip['tips_over'] or x <= 0.005 or x >= cfg.wheelbase - 0.005:
                times.append(np.nan)
            else:
                try:
                    r = total_track_time(cfg)
                    t = r['t_total']
                    times.append(t if t < 120 else np.nan)
                except Exception:
                    times.append(np.nan)
        results[m] = np.array(times)

    return results


def plot_sensitivity_1d(cfg_base):
    """Plot 1: Total time vs x_com for different masses."""
    x_range = np.linspace(0.02, 0.14, 30)
    masses = [0.250, 0.350, 0.450]

    print("  Computing 1D sensitivity sweep...")
    results = sweep_x_com(cfg_base, x_range, masses)

    fig, ax = plt.subplots(figsize=(8, 5))
    for m in masses:
        times = results[m]
        ax.plot(x_range * 1000, times, label=f"{m*1000:.0f} g", linewidth=2)

    ax.set_xlabel('CoM position from rear axle (mm)')
    ax.set_ylabel('Estimated total track time (s)')
    ax.set_title('Sensitivity: Track Time vs CoM Position')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_xlim(20, 140)
    ax.axvline(cfg_base.x_com * 1000, color='red', linestyle='--', alpha=0.5)

    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'plot_sensitivity_1d.png'), dpi=150)
    print(f"  Saved: plot_sensitivity_1d.png")
    return fig


def plot_heatmap_2d(cfg_base):
    """Plot 2: 2D heatmap of (x_com, z_com) -> total track time."""
    x_range = np.linspace(0.02, 0.14, 25)
    z_range = np.linspace(0.015, 0.060, 20)

    print("  Computing 2D heatmap...")
    times = np.full((len(z_range), len(x_range)), np.nan)
    infeasible = np.zeros_like(times, dtype=bool)

    for j, x in enumerate(x_range):
        for i, z in enumerate(z_range):
            cfg = cfg_base.with_com(x, z)
            tip = backward_tip_check(cfg)
            if tip['tips_over'] or x <= 0.005 or x >= cfg.wheelbase - 0.005:
                infeasible[i, j] = True
                continue
            try:
                r = total_track_time(cfg)
                t = r['t_total']
                if t < 120:
                    times[i, j] = t
                else:
                    infeasible[i, j] = True
            except Exception:
                infeasible[i, j] = True

    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.pcolormesh(x_range * 1000, z_range * 1000, times,
                       cmap='RdYlGn_r', shading='auto')
    fig.colorbar(im, ax=ax, label='Total track time (s)')

    # Hatch infeasible
    ax.contourf(x_range * 1000, z_range * 1000,
                infeasible.astype(float),
                levels=[0.5, 1.5], colors='none', hatches=['///'], alpha=0)
    ax.contour(x_range * 1000, z_range * 1000,
               infeasible.astype(float),
               levels=[0.5], colors='black', linewidths=1.5)

    ax.plot(cfg_base.x_com * 1000, cfg_base.z_com * 1000,
            'k*', markersize=15, label='Current CoM')
    x_comp, z_comp = cfg_base.compute_com_from_components()
    ax.plot(x_comp * 1000, z_comp * 1000,
            'wo', markersize=10, markeredgecolor='black', label='CoM from components')

    ax.set_xlabel('CoM x-position from rear axle (mm)')
    ax.set_ylabel('CoM height above ground (mm)')
    ax.set_title('Track Time vs Center of Mass Position')
    ax.legend(loc='upper left')

    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'plot_heatmap_2d.png'), dpi=150)
    print(f"  Saved: plot_heatmap_2d.png")
    return fig


def plot_section_breakdown(cfg_base):
    """Plot 3: Stacked bar chart of time per section."""
    x_positions = [0.03, 0.05, 0.08, 0.10, 0.13]

    sections = ['t_downhill', 't_flat1', 't_bar1', 't_flat_to_turn', 't_turn',
                't_flat_to_bar2', 't_bar2', 't_flat_to_uphill', 't_uphill']
    section_labels = ['Downhill', 'Flat 1', 'Bar 1', 'Flat->Turn', 'U-Turn',
                      'Flat->Bar2', 'Bar 2', 'Flat->Up', 'Uphill']

    data = {s: [] for s in sections}
    valid_labels = []

    print("  Computing section breakdown...")
    for x in x_positions:
        cfg = cfg_base.with_com(x, cfg_base.z_com)
        tip = backward_tip_check(cfg)
        if tip['tips_over']:
            continue
        try:
            r = total_track_time(cfg)
            if r['t_total'] > 120:
                continue
            for s in sections:
                data[s].append(min(r[s], 30))
            valid_labels.append(f"x={x*1000:.0f}mm")
        except Exception:
            continue

    if not valid_labels:
        print("  No valid configs for breakdown.")
        return None

    fig, ax = plt.subplots(figsize=(9, 5))
    x_pos = np.arange(len(valid_labels))
    bottom = np.zeros(len(valid_labels))

    colors = plt.cm.Set2(np.linspace(0, 1, len(sections)))
    for s, sl, color in zip(sections, section_labels, colors):
        values = np.array(data[s])
        ax.bar(x_pos, values, bottom=bottom, label=sl, color=color, width=0.6)
        bottom += values

    ax.set_xticks(x_pos)
    ax.set_xticklabels(valid_labels)
    ax.set_ylabel('Time (s)')
    ax.set_title('Per-Section Time Breakdown by CoM Position')
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8)

    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'plot_section_breakdown.png'), dpi=150)
    print(f"  Saved: plot_section_breakdown.png")
    return fig


def plot_ballast_analysis(cfg_base):
    """Plot 4: Effect of adding ballast mass."""
    x_range = np.linspace(0.03, 0.13, 20)
    print("  Computing ballast analysis...")

    # Find optimal x_com
    base_results = sweep_x_com(cfg_base, x_range)
    base_times = base_results[cfg_base.total_mass]
    valid_mask = ~np.isnan(base_times)
    if not np.any(valid_mask):
        print("  No valid configs for ballast analysis.")
        return None
    best_x = x_range[valid_mask][np.nanargmin(base_times[valid_mask])]

    added_masses = np.linspace(0, 0.100, 15)
    times_at_optimal = []
    times_at_current = []

    for dm in added_masses:
        m_new = cfg_base.total_mass + dm

        cfg_opt = cfg_base.with_com(best_x, cfg_base.z_com).with_mass(m_new)
        cfg_cur = cfg_base.with_mass(m_new)

        try:
            r = total_track_time(cfg_opt)
            times_at_optimal.append(r['t_total'] if r['t_total'] < 120 else np.nan)
        except Exception:
            times_at_optimal.append(np.nan)

        try:
            r = total_track_time(cfg_cur)
            times_at_current.append(r['t_total'] if r['t_total'] < 120 else np.nan)
        except Exception:
            times_at_current.append(np.nan)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(added_masses * 1000, times_at_optimal, 'b-o', markersize=4,
            label=f'Ballast at optimal x={best_x*1000:.0f}mm', linewidth=2)
    ax.plot(added_masses * 1000, times_at_current, 'r-s', markersize=4,
            label=f'Ballast at current x={cfg_base.x_com*1000:.0f}mm', linewidth=2)

    ax.set_xlabel('Added ballast mass (g)')
    ax.set_ylabel('Estimated total track time (s)')
    ax.set_title('Ballast Cost-Benefit Analysis')
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'plot_ballast_analysis.png'), dpi=150)
    print(f"  Saved: plot_ballast_analysis.png")
    return fig


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    cfg = RobotConfig()

    print_analysis(cfg)

    print("=" * 70)
    print("GENERATING PLOTS...")
    print("=" * 70)
    print()

    plot_sensitivity_1d(cfg)
    plot_heatmap_2d(cfg)
    plot_section_breakdown(cfg)
    plot_ballast_analysis(cfg)

    print()
    print(f"All plots saved to: {OUTPUT_DIR}")
    plt.show()
