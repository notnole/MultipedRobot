"""
Section 1: Downhill Descent Dynamics
Computes acceleration, exit velocity, traversal time, and transition loads.

Key insight: the robot doesn't free-fall down the slope. The motors may be
engaged (driving or braking), and the driver must control speed to safely
approach the bar at the bottom. The practical exit speed is limited by
the need to stop/slow before the first bar.
"""
import math

g = 9.81


def normal_forces_on_slope(cfg):
    """Normal forces on front and rear axles on a slope.

    On a decline (robot going downhill nose-first):
    - Gravity along slope shifts load toward the front
    - Higher CoM amplifies this shift

    Returns (N_front, N_rear).
    """
    m = cfg.total_mass
    L = cfg.wheelbase
    theta = cfg.slope_angle_rad
    x = cfg.x_com
    z = cfg.z_com

    N_front = m * g * (math.cos(theta) * x + math.sin(theta) * z) / L
    N_rear = m * g * math.cos(theta) - N_front

    return N_front, N_rear


def normal_forces_on_flat(cfg):
    """Normal forces on flat ground."""
    m = cfg.total_mass
    L = cfg.wheelbase
    x = cfg.x_com

    N_front = m * g * x / L
    N_rear = m * g * (L - x) / L
    return N_front, N_rear


def freefall_acceleration(cfg):
    """Acceleration if coasting downhill with motors disengaged.

    a = g * (sin(theta) - mu_rolling * cos(theta))
    """
    theta = cfg.slope_angle_rad
    a = g * (math.sin(theta) - cfg.mu_rolling * math.cos(theta))
    return max(a, 0.0)


def freefall_velocity_at_bottom(cfg):
    """Speed at bottom if coasting from rest (theoretical maximum)."""
    a = freefall_acceleration(cfg)
    return math.sqrt(2 * a * cfg.slope_length)


def driven_downhill_time(cfg):
    """Time to descend with motors engaged (driving downhill).

    The motors help accelerate but are speed-limited.
    Uses Euler integration with servo ramp-up.

    Returns (time, exit_velocity).
    """
    m = cfg.total_mass
    theta = cfg.slope_angle_rad
    R = cfg.wheel_radius
    dt = 0.0005
    v = 0.0
    x = 0.0
    t = 0.0

    F_gravity_along = m * g * math.sin(theta)
    F_rolling = cfg.mu_rolling * m * g * math.cos(theta)

    while x < cfg.slope_length and t < 30.0:
        # Servo ramp: limits effective no-load speed
        ramp = min(t / cfg.servo_accel_time, 1.0) if cfg.servo_accel_time > 0 else 1.0
        v_max_current = cfg.v_max * ramp

        # Motor force with ramped speed limit
        omega_wheel = v / R
        omega_max = v_max_current / R
        if omega_max > 0 and omega_wheel < omega_max:
            T_stall_wheel = cfg.wheel_torque_stall
            T_wheel = T_stall_wheel * (1 - omega_wheel / omega_max)
            F_motor = 2 * T_wheel / R
        else:
            F_motor = 0.0

        # Traction limit on motor force
        _, N_rear = normal_forces_on_slope(cfg)
        F_traction = cfg.mu_static * N_rear
        F_motor = min(F_motor, F_traction)

        # Net force: gravity helps, rolling resists, motor helps
        F_net = F_gravity_along - F_rolling + F_motor
        a = F_net / m

        v = v + a * dt
        # Cap at motor max speed (can't go faster than no-load)
        v = min(v, cfg.v_max)
        x += v * dt
        t += dt

    return t, v


def coast_downhill_time(cfg):
    """Time to descend with motors OFF (gravity only, rolling resistance).

    Returns (time, exit_velocity).
    """
    a = freefall_acceleration(cfg)
    if a <= 0:
        return float('inf'), 0.0
    t = math.sqrt(2 * cfg.slope_length / a)
    v = a * t
    return t, v


def time_downhill(cfg):
    """Best-case downhill time (motors engaged).

    Returns (time, exit_velocity).
    """
    return driven_downhill_time(cfg)


def transition_check(cfg, v_bottom):
    """Check dynamics at the slope-to-flat transition.

    Returns dict with load factors and risk assessment.
    """
    L = cfg.wheelbase
    theta = cfg.slope_angle_rad

    R_curve = L / (1 - math.cos(theta)) if (1 - math.cos(theta)) > 0 else float('inf')

    if R_curve > 0 and v_bottom > 0:
        a_centripetal = v_bottom**2 / R_curve
    else:
        a_centripetal = 0

    m = cfg.total_mass
    N_front_static, N_rear_static = normal_forces_on_flat(cfg)
    delta_N = m * a_centripetal
    delta_front = delta_N * cfg.x_com / L
    delta_rear = delta_N * (L - cfg.x_com) / L

    N_front_dynamic = N_front_static + delta_front
    N_rear_dynamic = N_rear_static + delta_rear

    return {
        'v_bottom': v_bottom,
        'a_centripetal': a_centripetal,
        'a_centripetal_g': a_centripetal / g,
        'N_front_static': N_front_static,
        'N_front_dynamic': N_front_dynamic,
        'N_rear_static': N_rear_static,
        'N_rear_dynamic': N_rear_dynamic,
        'front_overload_factor': N_front_dynamic / N_front_static if N_front_static > 0 else float('inf'),
        'rear_lifts': N_rear_dynamic < 0,
    }
