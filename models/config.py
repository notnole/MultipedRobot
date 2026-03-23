"""
Center of Mass Optimization Model - Configuration
All robot and track parameters in one place as a mutable dataclass.
"""
from dataclasses import dataclass, field
import math


@dataclass
class RobotConfig:
    # --- Mass and geometry (measured) ---
    total_mass: float = 0.350           # kg (estimate, weigh the robot)
    wheelbase: float = 0.157            # m (47mm rear overhang + 130mm frame - 20mm front offset)
    track_width: float = 0.140          # m between rear wheels (estimate, measure)
    wheel_radius: float = 0.030         # m (30mm, measured)
    ground_clearance: float = 0.020     # m (20mm, measured)

    # --- Center of mass position (optimization variables) ---
    # Origin: rear axle contact point on ground
    # x_com: positive = toward front axle
    # z_com: height above ground
    x_com: float = 0.080                # m (default: roughly mid-wheelbase)
    z_com: float = 0.030                # m (low profile)

    # --- Component masses for feasibility map ---
    # Each: (name, mass_kg, x_pos_m, z_pos_m) relative to rear axle on ground
    components: list = field(default_factory=lambda: [
        ("MG996R drive A",    0.055, -0.010, 0.030),
        ("MG996R drive B",    0.055, -0.010, 0.030),
        ("MG996R steering",   0.055,  0.137, 0.030),   # near front axle
        ("Planetary gearbox", 0.040,  0.000, 0.030),
        ("Arduino UNO",       0.025,  0.070, 0.045),
        ("Frame (plywood)",   0.060,  0.065, 0.025),    # frame center
        ("Wheels + axles",    0.030,  0.000, 0.030),
        ("Wiring + misc",     0.020,  0.070, 0.035),
    ])

    # --- Drivetrain (measured / from specs) ---
    servo_stall_torque: float = 1.0     # N-m per motor (~1 Nm as measured)
    servo_no_load_rpm: float = 60.0     # RPM at motor output shaft
    gear_ratio: float = 5.0             # 1:5 speed-up (fastest mode currently used)
    drivetrain_efficiency: float = 0.97  # from drivetrain analysis
    servo_accel_time: float = 1.5       # seconds for servo to ramp from 0 to full speed

    # --- Friction ---
    mu_static: float = 0.80             # static friction, rubber on plywood
    mu_rolling: float = 0.02            # rolling resistance coefficient

    # --- Track ---
    slope_angle_deg: float = 17.0
    slope_length: float = 0.425         # m along slope surface
    bar_height: float = 0.015           # m (1.5 cm)
    bar_angle_deg: float = 45.0         # bars at 45 deg to travel direction
    num_bars: int = 2                   # 2 bars, one before turn, one after
    flat_length_bottom: float = 0.773   # m bottom section total
    path_width: float = 0.380           # m track path width

    # --- Settling model (estimated, tune with experiments) ---
    tire_stiffness: float = 1000.0      # N/m (rubber on plywood, estimated)
    damping_ratio: float = 0.4          # dimensionless (estimated)

    # --- Turn ---
    turn_radius: float = 0.150          # m (tight U-turn in 380mm wide path)
    turn_speed: float = 0.15            # m/s (~15 cm/s, slow maneuvering speed)
    bar_recovery_time: float = 0.5      # s, time to regain control after each bar

    # --- Derived properties ---
    @property
    def slope_angle_rad(self):
        return math.radians(self.slope_angle_deg)

    @property
    def bar_angle_rad(self):
        return math.radians(self.bar_angle_deg)

    @property
    def weight(self):
        return self.total_mass * 9.81

    @property
    def wheel_rpm(self):
        """Wheel RPM after gearbox."""
        return self.servo_no_load_rpm * self.gear_ratio

    @property
    def wheel_no_load_omega(self):
        """No-load wheel angular velocity in rad/s."""
        return self.wheel_rpm * 2 * math.pi / 60

    @property
    def v_max(self):
        """Maximum speed from motor (no-load), in m/s."""
        return self.wheel_no_load_omega * self.wheel_radius

    @property
    def wheel_torque_stall(self):
        """Max torque at the wheel (after gearbox), per motor.

        Speed-up gearing: torque is DIVIDED by ratio, not multiplied.
        """
        return self.servo_stall_torque / self.gear_ratio * self.drivetrain_efficiency

    @property
    def max_drive_force(self):
        """Max driving force at stall (both motors), in N."""
        return 2 * self.wheel_torque_stall / self.wheel_radius

    def compute_com_from_components(self):
        """Calculate CoM from component list. Returns (x_com, z_com)."""
        total_m = sum(c[1] for c in self.components)
        x = sum(c[1] * c[2] for c in self.components) / total_m
        z = sum(c[1] * c[3] for c in self.components) / total_m
        return x, z

    def with_com(self, x_com, z_com):
        """Return a copy with different CoM position."""
        import copy
        cfg = copy.copy(self)
        cfg.x_com = x_com
        cfg.z_com = z_com
        return cfg

    def with_mass(self, total_mass):
        """Return a copy with different total mass."""
        import copy
        cfg = copy.copy(self)
        cfg.total_mass = total_mass
        return cfg
