# box.py
"""
Focus Box hardware interface using robot_hat.

Reuses the same wiring style as PiCar-X:
- motor_pins default: ['D4', 'D5', 'P13', 'P12']
  (left_dir, right_dir, left_pwm, right_pwm)
- grayscale_pins default: ['A0','A1','A2']
- ultrasonic_pins default: ['D2','D3'] (trig, echo)

Main API:
    box = BoxHardware(...)
    box.lock()
    box.unlock()
    present = box.is_phone_present()

Notes on phone detection:
- Ultrasonic is usually better for "is something inside the box" because it measures distance.
- Grayscale is reflectance-based; it can work if mounted close to where the phone sits and calibrated.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Literal, Optional

from robot_hat import Pin, ADC, PWM, Servo, fileDB
from robot_hat import Grayscale_Module, Ultrasonic, utils


def constrain(x, lo, hi):
    return max(lo, min(hi, x))


@dataclass
class PhoneDetectConfig:
    sensor: Literal["ultrasonic", "grayscale"] = "ultrasonic"

    # Ultrasonic: phone present if distance <= threshold_cm
    ultrasonic_threshold_cm: float = 10.0
    ultrasonic_samples: int = 3
    ultrasonic_delay_s: float = 0.05

    # Grayscale: phone present if (avg reading) crosses threshold
    # You must calibrate this based on your mounting + phone surface.
    # In many setups: closer object -> reading changes significantly.
    grayscale_threshold: float = 700.0
    grayscale_samples: int = 5
    grayscale_delay_s: float = 0.02


class BoxHardware:
    CONFIG = "/opt/focusbox/focusbox.conf"

    # Same PWM constants as your PiCarX
    PERIOD = 4095
    PRESCALER = 10

    def __init__(
        self,
        motor_pins: List[str] = ["D4", "D5", "P13", "P12"],
        grayscale_pins: List[str] = ["A0", "A1", "A2"],
        ultrasonic_pins: List[str] = ["D2", "D3"],
        config_path: str = CONFIG,
        detect: PhoneDetectConfig = PhoneDetectConfig(),
        # Lock motion tuning:
        lock_speed: int = 70,           # 0..100
        unlock_speed: int = 70,         # 0..100
        lock_duration_s: float = 1.2,   # how long to run motors to lock
        unlock_duration_s: float = 1.2, # how long to run motors to unlock
    ):
        # Reset robot_hat MCU (same pattern as PiCarX)
        utils.reset_mcu()
        time.sleep(0.2)

        self.detect_cfg = detect

        # Config DB (same as PiCarX)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        self.config_file = fileDB(config_path, 0o777, os.getlogin())

        # ---- motors init (mirrors PiCarX wiring & calibration) ----
        self.left_dir = Pin(motor_pins[0])
        self.right_dir = Pin(motor_pins[1])
        self.left_pwm = PWM(motor_pins[2])
        self.right_pwm = PWM(motor_pins[3])

        self.motor_direction_pins = [self.left_dir, self.right_dir]
        self.motor_speed_pins = [self.left_pwm, self.right_pwm]

        # Load motor direction calibration (same key as PiCarX)
        cali_dir = self.config_file.get("picarx_dir_motor", default_value="[1, 1]")
        self.cali_dir_value = [int(i.strip()) for i in cali_dir.strip().strip("[]").split(",")]

        # Speed calibration (keep simple, you can extend later)
        self.cali_speed_value = [0, 0]

        for pin in self.motor_speed_pins:
            pin.period(self.PERIOD)
            pin.prescaler(self.PRESCALER)

        # ---- sensors init ----
        # Grayscale module
        adc0, adc1, adc2 = [ADC(pin) for pin in grayscale_pins]
        self.grayscale = Grayscale_Module(adc0, adc1, adc2, reference=None)

        # Allow storing a grayscale reference (optional)
        # If you used PiCarX before, these keys may already exist in the config.
        ref = self.config_file.get("focusbox_grayscale_ref", default_value="")
        if ref:
            try:
                ref_list = [float(i) for i in ref.strip().strip("[]").split(",")]
                if len(ref_list) == 3:
                    self.grayscale.reference(ref_list)
            except Exception:
                pass

        # Ultrasonic
        trig, echo = ultrasonic_pins
        self.ultrasonic = Ultrasonic(Pin(trig), Pin(echo, mode=Pin.IN, pull=Pin.PULL_DOWN))

        # ---- lock tuning ----
        self.lock_speed = constrain(lock_speed, 0, 100)
        self.unlock_speed = constrain(unlock_speed, 0, 100)
        self.lock_duration_s = max(0.0, lock_duration_s)
        self.unlock_duration_s = max(0.0, unlock_duration_s)

        self._locked = False

    # ---------------- Motor control (adapted from PiCarX) ----------------

    def set_motor_speed(self, motor_index: int, speed: int):
        """
        motor_index: 1 for left motor, 2 for right motor
        speed: -100..100
        """
        speed = constrain(speed, -100, 100)
        m = motor_index - 1

        if speed >= 0:
            direction = 1 * self.cali_dir_value[m]
        else:
            direction = -1 * self.cali_dir_value[m]

        speed_abs = abs(speed)

        # Same mapping from your PiCarX:
        # if speed != 0: speed = int(speed/2) + 50
        if speed_abs != 0:
            pwm_percent = int(speed_abs / 2) + 50
        else:
            pwm_percent = 0

        pwm_percent = pwm_percent - self.cali_speed_value[m]
        pwm_percent = constrain(pwm_percent, 0, 100)

        # Same direction pin logic as PiCarX
        if direction < 0:
            self.motor_direction_pins[m].high()
            self.motor_speed_pins[m].pulse_width_percent(pwm_percent)
        else:
            self.motor_direction_pins[m].low()
            self.motor_speed_pins[m].pulse_width_percent(pwm_percent)

    def stop_motors(self):
        # Execute twice (same as PiCarX) for better stop reliability
        for _ in range(2):
            self.motor_speed_pins[0].pulse_width_percent(0)
            self.motor_speed_pins[1].pulse_width_percent(0)
            time.sleep(0.002)

    def _run_both_motors(self, speed_left: int, speed_right: int, duration_s: float):
        self.set_motor_speed(1, speed_left)
        self.set_motor_speed(2, speed_right)
        time.sleep(duration_s)
        self.stop_motors()

    # ---------------- Locking API ----------------

    @property
    def is_locked(self) -> bool:
        return self._locked

    def lock(self):
        """
        Pull string to lock lid. Assumes positive speed pulls in the lock direction.
        If your winding direction is opposite, swap signs or flip calibration.
        """
        if self._locked:
            return

        # Run both motors same direction to pull string
        s = int(self.lock_speed)
        self._run_both_motors(+s, +s, self.lock_duration_s)
        self._locked = True
        print("[Box] LOCKED")

    def unlock(self):
        """
        Release string to unlock lid. Assumes negative speed releases.
        If opposite, swap signs.
        """
        if not self._locked:
            return

        s = int(self.unlock_speed)
        self._run_both_motors(-s, -s, self.unlock_duration_s)
        self._locked = False
        print("[Box] UNLOCKED")

    # ---------------- Phone detection ----------------

    def get_distance_cm(self) -> float:
        """
        Ultrasonic read() typically returns distance (often cm in many robot_hat impls).
        """
        return float(self.ultrasonic.read())

    def get_grayscale(self) -> List[float]:
        """
        Returns [v0, v1, v2]
        """
        return list.copy(self.grayscale.read())

    def is_phone_present(self) -> bool:
        """
        Returns True if sensor indicates phone is placed.

        Recommended: ultrasonic
          - reliable if you mount sensor facing the phone area
          - choose a threshold (e.g., <= 10 cm)

        Grayscale:
          - works only if close to phone surface & calibrated
        """
        if self.detect_cfg.sensor == "ultrasonic":
            return self._phone_present_ultrasonic()

        if self.detect_cfg.sensor == "grayscale":
            return self._phone_present_grayscale()

        raise ValueError(f"Unknown sensor mode: {self.detect_cfg.sensor}")

    def _phone_present_ultrasonic(self) -> bool:
        samples = []
        for _ in range(max(1, self.detect_cfg.ultrasonic_samples)):
            d = self.get_distance_cm()
            samples.append(d)
            time.sleep(self.detect_cfg.ultrasonic_delay_s)

        # robust-ish: use min distance (object presence tends to drop distance)
        d_min = min(samples)
        present = d_min <= self.detect_cfg.ultrasonic_threshold_cm
        print(f"[Box] Ultrasonic d_min={d_min:.2f}cm -> present={present}")
        return present

    def _phone_present_grayscale(self) -> bool:
        avgs = []
        for _ in range(max(1, self.detect_cfg.grayscale_samples)):
            vals = self.get_grayscale()
            avg = sum(vals) / 3.0
            avgs.append(avg)
            time.sleep(self.detect_cfg.grayscale_delay_s)

        avg_mean = sum(avgs) / len(avgs)

        # Depending on mounting, "present" might mean avg goes UP or DOWN.
        # This default assumes avg gets LOWER when phone is close (common with some reflectance setups).
        # If your readings increase instead, flip the comparator.
        present = avg_mean <= self.detect_cfg.grayscale_threshold
        print(f"[Box] Grayscale avg={avg_mean:.1f} -> present={present}")
        return present

    # ---------------- Optional helpers ----------------

    def set_grayscale_reference(self, ref3: List[float]):
        """
        Store a reference in config. Useful if you want to use grayscale.status API later.
        """
        if not (isinstance(ref3, list) and len(ref3) == 3):
            raise ValueError("ref3 must be a list of 3 numbers")
        self.grayscale.reference(ref3)
        self.config_file.set("focusbox_grayscale_ref", str(ref3))
        print(f"[Box] Saved grayscale reference: {ref3}")


# Simple manual test
if __name__ == "__main__":
    box = BoxHardware(
        detect=PhoneDetectConfig(sensor="ultrasonic", ultrasonic_threshold_cm=10.0)
    )

    print("Phone present?", box.is_phone_present())
    print("Locking...")
    box.lock()
    time.sleep(1)
    print("Unlocking...")
    box.unlock()
