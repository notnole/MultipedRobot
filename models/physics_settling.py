"""
Section 2b: Post-Bar Settling and Turn Grip Analysis
Models the vertical oscillation after bar crossing and checks
whether the robot has enough grip during the U-turn.
"""
import math

g = 9.81


def natural_frequency(cfg):
    """Natural frequency of the robot bouncing on its tires.

    Modeled as a mass-spring system:
        omega_n = sqrt(k / m)
        f_n = omega_n / (2*pi)

    The tire stiffness k is the combined stiffness of all contact points.
    """
    omega_n = math.sqrt(cfg.tire_stiffness / cfg.total_mass)
    f_n = omega_n / (2 * math.pi)
    return omega_n, f_n


def bounce_after_bar(cfg, drop_height=None):
    """Model the vertical oscillation after a wheel drops off a bar.

    When the wheel clears the bar top and drops back to the surface,
    it falls by approximately the bar height h.

    The impact velocity is v_impact = sqrt(2*g*h).
    This excites a damped oscillation.

    Returns dict with oscillation parameters.
    """
    h = drop_height if drop_height is not None else cfg.bar_height
    v_impact = math.sqrt(2 * g * h)

    omega_n, f_n = natural_frequency(cfg)
    zeta = cfg.damping_ratio

    # Initial amplitude from impact velocity
    # For a damped oscillator hit with velocity v0:
    #   A = v0 / (omega_n * sqrt(1 - zeta^2))
    omega_d = omega_n * math.sqrt(1 - zeta**2)  # damped frequency
    A0 = v_impact / omega_d  # initial amplitude in meters

    # Time to decay to 5% of initial amplitude
    # envelope: A(t) = A0 * exp(-zeta * omega_n * t)
    # A(t)/A0 = 0.05 -> t = -ln(0.05) / (zeta * omega_n)
    if zeta * omega_n > 0:
        t_settle = -math.log(0.05) / (zeta * omega_n)
    else:
        t_settle = float('inf')

    return {
        'v_impact_ms': v_impact,
        'amplitude_m': A0,
        'amplitude_mm': A0 * 1000,
        'omega_n': omega_n,
        'omega_d': omega_d,
        'f_natural_Hz': f_n,
        'f_damped_Hz': omega_d / (2 * math.pi),
        'damping_ratio': zeta,
        't_settle_95pct_s': t_settle,
    }


def settling_distance(cfg, v_forward, drop_height=None):
    """Distance the robot travels before bounce settles to 5%.

    d = v_forward * t_settle

    Returns dict with distance and whether the robot has settled
    before reaching the turn.
    """
    bounce = bounce_after_bar(cfg, drop_height)
    d = v_forward * bounce['t_settle_95pct_s']

    return {
        'd_settle_m': d,
        'd_settle_mm': d * 1000,
        't_settle_s': bounce['t_settle_95pct_s'],
        'bounce_amplitude_mm': bounce['amplitude_mm'],
    }


def normal_force_during_bounce(cfg, t, drop_height=None):
    """Time-varying normal force during post-bar oscillation.

    The spring force variation adds/subtracts from the static weight:
        F_spring(t) = k * A0 * exp(-zeta*omega_n*t) * cos(omega_d*t)

    Total normal force = m*g + F_spring(t)
    If this goes negative, the wheel lifts off momentarily.

    Returns (N_total, fraction_of_static_weight) at time t.
    """
    bounce = bounce_after_bar(cfg, drop_height)
    A0 = bounce['amplitude_m']
    omega_n = bounce['omega_n']
    omega_d = bounce['omega_d']
    zeta = cfg.damping_ratio

    # Spring force variation
    F_spring = cfg.tire_stiffness * A0 * math.exp(-zeta * omega_n * t) * math.cos(omega_d * t)

    N_static = cfg.total_mass * g
    N_total = N_static - F_spring  # minus because upward displacement reduces contact force

    return N_total, N_total / N_static


def min_normal_force_during_bounce(cfg, drop_height=None):
    """Find the minimum normal force during the bounce.

    The minimum occurs at the first downward peak of the oscillation.
    For an underdamped system, this happens at approximately t = 0
    (the impact itself) or the first oscillation peak.

    Returns the minimum normal force as a fraction of static weight.
    """
    bounce = bounce_after_bar(cfg, drop_height)
    omega_d = bounce['omega_d']

    # Check at the first negative peak
    # The first minimum of cos(omega_d * t) after t=0 is at t=0 itself
    # (cosine starts at 1, so the spring force is maximum positive,
    #  meaning normal force is minimum)
    N_at_impact, frac = normal_force_during_bounce(cfg, 0.0, drop_height)

    # Also check at half period (next peak)
    if omega_d > 0:
        t_half = math.pi / omega_d
        N_at_half, frac_half = normal_force_during_bounce(cfg, t_half, drop_height)
        if N_at_half < N_at_impact:
            return N_at_half, frac_half

    return N_at_impact, frac


def turn_traction(cfg, v_turn):
    """Check traction during the U-turn.

    The centripetal force required: F_c = m * v^2 / r
    Available lateral friction: F_f = mu * N

    CoM position affects weight distribution on front (steering) wheels
    vs rear (drive) wheels. Both must maintain traction:
    - Front wheels need lateral grip for steering
    - Rear wheels need lateral grip to not slide out

    Returns dict with grip margins for front and rear.
    """
    m = cfg.total_mass
    r = cfg.turn_radius
    L = cfg.wheelbase
    x = cfg.x_com

    F_centripetal = m * v_turn**2 / r

    # Static weight distribution on flat ground
    N_front = m * g * x / L
    N_rear = m * g * (L - x) / L

    # Lateral force demand is distributed proportionally to axle loads
    # (simplified bicycle model)
    F_lat_front = F_centripetal * (L - x) / L  # front axle lateral force
    F_lat_rear = F_centripetal * x / L          # rear axle lateral force

    # Available friction
    F_grip_front = cfg.mu_static * N_front
    F_grip_rear = cfg.mu_static * N_rear

    # Margins
    front_margin = F_grip_front / F_lat_front if F_lat_front > 0 else float('inf')
    rear_margin = F_grip_rear / F_lat_rear if F_lat_rear > 0 else float('inf')

    # Maximum safe speed (limited by the tighter axle)
    # F_c = m*v^2/r <= mu*N  for each axle proportionally
    # The binding constraint determines max speed
    v_max_front = math.sqrt(cfg.mu_static * g * r) if N_front > 0 else 0
    v_max_rear = math.sqrt(cfg.mu_static * g * r) if N_rear > 0 else 0
    v_max = min(v_max_front, v_max_rear)

    return {
        'F_centripetal': F_centripetal,
        'F_lat_front': F_lat_front,
        'F_lat_rear': F_lat_rear,
        'F_grip_front': F_grip_front,
        'F_grip_rear': F_grip_rear,
        'front_grip_margin': front_margin,
        'rear_grip_margin': rear_margin,
        'v_max_turn': v_max,
        'can_turn_at_speed': front_margin >= 1.0 and rear_margin >= 1.0,
    }


def time_through_turn(cfg, v_entry):
    """Estimate time for the U-turn.

    The turn is tight (380mm path, ~270mm wide robot). The robot must:
    1. Decelerate to the turn maneuvering speed
    2. Navigate a semicircle (or multi-point turn)
    3. The exit speed is the turn speed (must re-accelerate after)

    Returns (time, exit_velocity).
    """
    r = cfg.turn_radius
    traction = turn_traction(cfg, v_entry)

    # Turn speed: limited by grip AND practical control
    v_turn = min(cfg.turn_speed, traction['v_max_turn'])

    # Time to decelerate from entry speed to turn speed
    if v_entry > v_turn:
        # Braking: assume moderate braking force
        F_brake = cfg.mu_static * cfg.total_mass * g * 0.5
        a_brake = F_brake / cfg.total_mass
        t_decel = (v_entry - v_turn) / a_brake
    else:
        t_decel = 0
        v_turn = v_entry

    # Semicircle arc + some extra for steering adjustments
    arc_length = math.pi * r * 1.3  # 30% extra for maneuvering overhead

    if v_turn > 0:
        t_arc = arc_length / v_turn
    else:
        t_arc = float('inf')

    t_total = t_decel + t_arc
    return t_total, v_turn
