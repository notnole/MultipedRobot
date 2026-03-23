"""
Section 2: Per-Wheel Bar Crossing at 45 Degrees
Models the energy and force requirements for climbing over rectangular bars
when they are oriented at 45 degrees to the travel direction.

Key insight: at 45 deg, one wheel hits the bar first. The stagger distance
along the travel direction equals the robot's track width for 45 deg bars.
"""
import math

g = 9.81


def bar_climb_force(W_wheel, R, h):
    """Force needed for a wheel to climb over a rectangular bar.

    Reused from scripts/bar_climbing_physics.py.
    F = W_wheel * sqrt(2*R*h - h^2) / (R - h)
    """
    if R <= h:
        return float('inf')
    numerator = math.sqrt(2 * R * h - h**2)
    denominator = R - h
    return W_wheel * numerator / denominator


def bar_climb_torque(W_wheel, R, h):
    """Torque at the axle needed to climb over a bar.

    tau = W_wheel * R * sqrt(2*R*h - h^2) / (R - h)
    """
    if R <= h:
        return float('inf')
    numerator = math.sqrt(2 * R * h - h**2)
    denominator = R - h
    return W_wheel * R * numerator / denominator


def impact_stagger(cfg):
    """Distance along travel direction between the two rear wheels
    hitting the same bar, given the bar angle.

    For 45 deg bars: stagger = track_width.
    """
    alpha = cfg.bar_angle_rad
    return cfg.track_width * math.tan(alpha)


def weight_on_each_wheel(cfg, on_slope=False):
    """Weight on each rear wheel and front axle.

    Returns (W_per_rear_wheel, W_front_total).
    """
    m = cfg.total_mass
    L = cfg.wheelbase
    x = cfg.x_com

    if on_slope:
        theta = cfg.slope_angle_rad
        N_front = m * g * (math.cos(theta) * x - math.sin(theta) * cfg.z_com) / L
        N_rear_total = m * g * math.cos(theta) - N_front
    else:
        N_front = m * g * x / L
        N_rear_total = m * g * (L - x) / L

    W_per_rear = N_rear_total / 2
    return W_per_rear, N_front


def step_climb_energy(cfg, on_slope=False):
    """Energy and force analysis for per-wheel bar climbing.

    At 45 deg bars, one wheel climbs at a time. The other wheel
    is on flat ground and can assist.
    """
    R = cfg.wheel_radius
    h = cfg.bar_height

    W_per_rear, W_front = weight_on_each_wheel(cfg, on_slope)

    # Torque needed at the climbing wheel
    tau_climb = bar_climb_torque(W_per_rear, R, h)
    tau_climb_kgcm = tau_climb / 0.0981

    # Available torque per wheel from servo (at stall, through gearbox)
    T_avail = cfg.wheel_torque_stall
    safety_factor = T_avail / tau_climb if tau_climb > 0 else float('inf')

    # CoM rise when one rear wheel lifts over bar
    # Rear wheel at x=0, front at x=L, CoM at x=x_com
    # When rear wheel rises by h, CoM rises by h * (L - x_com) / L
    delta_z_com = h * (cfg.wheelbase - cfg.x_com) / cfg.wheelbase

    # Minimum approach velocity from energy balance (no motor help)
    v_min_energy = math.sqrt(2 * g * delta_z_com)

    F_climb = bar_climb_force(W_per_rear, R, h)

    return {
        'tau_climb_Nm': tau_climb,
        'tau_climb_kgcm': tau_climb_kgcm,
        'T_available_Nm': T_avail,
        'safety_factor_stall': safety_factor,
        'safety_factor_50pct': safety_factor * 0.5,
        'F_climb_N': F_climb,
        'delta_z_com_m': delta_z_com,
        'v_min_energy_ms': v_min_energy,
        'W_per_rear_wheel_N': W_per_rear,
        'W_front_N': W_front,
    }


def velocity_loss_per_bar(cfg, v_approach, on_slope=False):
    """Velocity after crossing one bar, using energy balance.

    Energy lost: lifting CoM over two climb events (one per rear wheel).
    Energy added: motor work over the crossing distance, using the
    speed-dependent torque curve at the actual approach speed.

    Returns velocity after clearing the bar.
    """
    m = cfg.total_mass
    h = cfg.bar_height
    R = cfg.wheel_radius

    # CoM rise per wheel climb
    delta_z = h * (cfg.wheelbase - cfg.x_com) / cfg.wheelbase

    # Two climb events per bar (staggered)
    energy_loss_lift = 2 * m * g * delta_z
    energy_loss_rolling = 2 * cfg.mu_rolling * m * g * h
    total_energy_loss = energy_loss_lift + energy_loss_rolling

    KE_before = 0.5 * m * v_approach**2

    # Motor energy during crossing: use force at actual speed
    d_climb = math.sqrt(2 * R * h - h**2)
    d_total = 2 * d_climb + impact_stagger(cfg)

    # Drive force at approach speed (speed-dependent torque)
    omega_wheel = v_approach / R
    omega_nl = cfg.wheel_no_load_omega
    if omega_wheel < omega_nl and omega_nl > 0:
        T_stall_wheel = cfg.wheel_torque_stall
        T_wheel = T_stall_wheel * (1 - omega_wheel / omega_nl)
        F_drive = 2 * T_wheel / R
    else:
        F_drive = 0.0

    energy_from_motors = F_drive * d_total

    KE_after = KE_before - total_energy_loss + energy_from_motors
    KE_after = max(KE_after, 0.0)

    v_after = math.sqrt(2 * KE_after / m)
    return v_after


def time_crossing_one_bar(cfg, v_approach):
    """Time to cross one bar.

    Approximate: distance / average velocity.
    """
    R = cfg.wheel_radius
    h = cfg.bar_height
    d_climb = math.sqrt(2 * R * h - h**2)
    d_total = 2 * d_climb + impact_stagger(cfg)

    v_after = velocity_loss_per_bar(cfg, v_approach)
    v_avg = (v_approach + v_after) / 2

    if v_avg > 0:
        return d_total / v_avg, v_after
    else:
        return float('inf'), 0.0
