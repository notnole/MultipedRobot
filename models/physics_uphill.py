"""
Section 3: Uphill Climb Dynamics
Computes traction limits, tip-over checks, terminal velocity, and climb time.
"""
import math

g = 9.81


def normal_forces_uphill(cfg):
    """Normal forces on front and rear axles going uphill.

    On an incline (rear wheels downhill, front wheels uphill):
    - Gravity component along slope shifts load toward the rear
    - Higher CoM amplifies rearward shift (good for rear-wheel traction,
      but risk of tipping backward if extreme)

    Returns (N_front, N_rear).
    """
    m = cfg.total_mass
    L = cfg.wheelbase
    theta = cfg.slope_angle_rad
    x = cfg.x_com
    z = cfg.z_com

    N_front = m * g * (math.cos(theta) * x - math.sin(theta) * z) / L
    N_rear = m * g * math.cos(theta) - N_front

    return N_front, N_rear


def backward_tip_check(cfg):
    """Check if the robot tips backward on the uphill slope.

    Tip-over occurs when N_front = 0:
        tan(theta) = x_com / z_com

    Returns dict with tip-over analysis.
    """
    theta = cfg.slope_angle_rad
    x = cfg.x_com
    z = cfg.z_com

    if z > 0:
        tip_angle_rad = math.atan(x / z)
        tip_angle_deg = math.degrees(tip_angle_rad)
    else:
        tip_angle_rad = math.pi / 2
        tip_angle_deg = 90.0

    N_front, N_rear = normal_forces_uphill(cfg)
    tips_over = N_front <= 0
    safety_margin = tip_angle_deg - cfg.slope_angle_deg

    return {
        'tips_over': tips_over,
        'tip_angle_deg': tip_angle_deg,
        'slope_angle_deg': cfg.slope_angle_deg,
        'safety_margin_deg': safety_margin,
        'N_front': N_front,
        'N_rear': N_rear,
        'x_com_over_z_com': x / z if z > 0 else float('inf'),
    }


def traction_check(cfg):
    """Check if rear wheels can transmit the required driving force.

    Max traction = mu_static * N_rear.
    Required force = m*g*sin(theta) + rolling resistance.
    """
    m = cfg.total_mass
    theta = cfg.slope_angle_rad
    N_front, N_rear = normal_forces_uphill(cfg)

    F_gravity = m * g * math.sin(theta)
    F_rolling = cfg.mu_rolling * m * g * math.cos(theta)
    F_required = F_gravity + F_rolling

    F_traction_max = cfg.mu_static * N_rear

    return {
        'F_gravity': F_gravity,
        'F_rolling': F_rolling,
        'F_required': F_required,
        'F_traction_max': F_traction_max,
        'traction_margin': F_traction_max / F_required if F_required > 0 else float('inf'),
        'slips': F_traction_max < F_required,
        'N_rear': N_rear,
    }


def drive_force_at_speed(cfg, v):
    """Driving force available at the wheels at a given speed.

    Servo torque follows a linear torque-speed curve:
        T_servo = T_stall * (1 - omega_servo / omega_no_load_servo)

    After the speed-up gearbox (1:5):
        - Wheel speed = 5 x servo speed
        - Wheel torque = servo torque / 5

    Two motors share the drive.

    Returns total driving force (N) from both rear wheels.
    """
    R = cfg.wheel_radius
    omega_wheel = v / R
    omega_no_load = cfg.wheel_no_load_omega

    if omega_wheel >= omega_no_load:
        return 0.0

    # Torque at wheel per motor (already accounts for gear ratio)
    T_stall_wheel = cfg.wheel_torque_stall
    T_wheel = T_stall_wheel * (1 - omega_wheel / omega_no_load)

    F_drive = 2 * T_wheel / R
    return F_drive


def terminal_velocity(cfg):
    """Terminal velocity on the uphill slope.

    At terminal velocity, drive force = gravity + rolling resistance.
    """
    m = cfg.total_mass
    theta = cfg.slope_angle_rad
    R = cfg.wheel_radius

    F_resist = m * g * (math.sin(theta) + cfg.mu_rolling * math.cos(theta))
    T_stall_wheel = cfg.wheel_torque_stall

    # Check if the robot can start (stall force > resistance)
    F_stall = 2 * T_stall_wheel / R
    if F_stall <= F_resist:
        return 0.0

    omega_nl = cfg.wheel_no_load_omega
    v_term = R * omega_nl * (1 - F_resist * R / (2 * T_stall_wheel))
    return max(v_term, 0.0)


def time_uphill(cfg, v_entry=0.0):
    """Time to traverse the uphill slope using Euler integration.

    Equation of motion:
        m * dv/dt = F_drive(v) - m*g*sin(theta) - mu_r*m*g*cos(theta)

    Accounts for servo acceleration time (ramp-up delay).

    Returns (time, exit_velocity).
    """
    m = cfg.total_mass
    theta = cfg.slope_angle_rad
    F_resist = m * g * (math.sin(theta) + cfg.mu_rolling * math.cos(theta))

    dt = 0.0005  # 0.5 ms time step
    v = v_entry
    x = 0.0
    t = 0.0
    max_time = 60.0

    while x < cfg.slope_length and t < max_time:
        # Servo ramp: limits the effective no-load speed, not the torque.
        # At t=0, the servo provides full stall torque but can't spin fast yet.
        ramp = min(t / cfg.servo_accel_time, 1.0) if cfg.servo_accel_time > 0 else 1.0
        v_max_current = cfg.v_max * ramp

        # Torque-speed curve with ramped speed limit
        omega_wheel = v / cfg.wheel_radius
        omega_max_current = v_max_current / cfg.wheel_radius
        if omega_max_current > 0 and omega_wheel < omega_max_current:
            T_stall = cfg.wheel_torque_stall
            T_wheel = T_stall * (1 - omega_wheel / omega_max_current)
            F_drive = 2 * T_wheel / cfg.wheel_radius
        else:
            F_drive = 0.0

        # Traction limit
        _, N_rear = normal_forces_uphill(cfg)
        F_traction_max = cfg.mu_static * N_rear
        F_drive = min(F_drive, F_traction_max)

        a = (F_drive - F_resist) / m

        v_new = v + a * dt
        if v_new < 0:
            return float('inf'), 0.0

        v = v_new
        x += v * dt
        t += dt

    return t, v
