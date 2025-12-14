# focusbox/scheduler.py

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime
from typing import List, Optional

from robot_hat import Music

from .google_calendar import ScheduledBlock
from .box import BoxHardware


class Mode(Enum):
    IDLE = auto()
    FOCUS = auto()
    SLEEP = auto()
    EMERGENCY = auto()


class GateState(Enum):
    """
    Gate before locking:
      - WAIT_PHONE: event started, but we haven't confirmed phone is inside
      - LOCKED: phone is inside and box locked
    """
    WAIT_PHONE = auto()
    LOCKED = auto()


@dataclass
class State:
    mode: Mode = Mode.IDLE
    gate: GateState = GateState.WAIT_PHONE
    active_block: Optional[ScheduledBlock] = None


class FocusBoxStateMachine:
    """
    Scheduler-driven state machine:
      - When entering FOCUS/SLEEP:
          1) prompt user to place phone (loop sound)
          2) wait until box.is_phone_present() is True
          3) play success sound
          4) box.lock()
      - When leaving event (IDLE):
          box.unlock() + play unlock sound
      - EMERGENCY:
          unlock immediately
    """

    def __init__(
        self,
        box: BoxHardware,
        music: Optional[Music] = None,
        # Audio paths (relative or absolute)
        wait_music_path: str = "../musics/slow-trail-Ahjay_Stelino.mp3",
        placed_sfx_path: str = "../musics/placed.mp3",
        unlock_sfx_path: str = "../musics/unlock.mp3",
        # Timing
        phone_poll_period_s: float = 1.0,
        # Behavior
        require_phone_for_lock: bool = True,
    ):
        self.box = box
        self.music = music or Music()

        self.wait_music_path = wait_music_path
        self.placed_sfx_path = placed_sfx_path
        self.unlock_sfx_path = unlock_sfx_path

        self.phone_poll_period_s = max(0.1, phone_poll_period_s)
        self.require_phone_for_lock = require_phone_for_lock

        self.state = State()
        self._last_phone_check_ts: Optional[datetime] = None
        self._wait_music_playing = False

    # ---------- external API ----------

    def update(self, now: datetime, schedule: List[ScheduledBlock]):
        """
        Call periodically (e.g., every 0.2~2s). It:
          - selects current active calendar block
          - transitions mode
          - runs phone-gate + lock logic
        """
        if self.state.mode == Mode.EMERGENCY:
            # In emergency, we do nothing except remain unlocked.
            return

        active, _nxt = self._find_current_and_next(now, schedule)

        if active is None:
            self._enter_mode(Mode.IDLE, None)
            return

        if active.mode == "FOCUS":
            self._enter_mode(Mode.FOCUS, active)
        elif active.mode == "SLEEP":
            self._enter_mode(Mode.SLEEP, active)
        else:
            # Unknown mode in schedule -> fall back to IDLE
            self._enter_mode(Mode.IDLE, None)

        # If we are in FOCUS/SLEEP, run the gate logic
        if self.state.mode in (Mode.FOCUS, Mode.SLEEP):
            self._handle_phone_gate(now)

    def emergency_unlock(self):
        """
        Hardware button can call this.
        """
        print("[State] EMERGENCY UNLOCK triggered!")
        self._stop_wait_music()
        self.box.unlock()
        self.state.mode = Mode.EMERGENCY
        self.state.active_block = None
        self.state.gate = GateState.WAIT_PHONE

    # ---------- core logic ----------

    def _handle_phone_gate(self, now: datetime):
        """
        Gate logic:
          - WAIT_PHONE: play waiting audio (loop) + poll sensor
          - LOCKED: ensure box remains locked (optional)
        """
        if not self.require_phone_for_lock:
            # Immediately lock when mode active
            if not self.box.is_locked:
                self._stop_wait_music()
                self.box.lock()
                self.state.gate = GateState.LOCKED
            return

        # If already locked, nothing to do
        if self.state.gate == GateState.LOCKED:
            if not self.box.is_locked:
                # If something unlocked it unexpectedly, re-lock (optional)
                self.box.lock()
            return

        # WAIT_PHONE state:
        self._start_wait_music()

        # Rate-limit sensor polling
        if self._last_phone_check_ts is not None:
            dt = (now - self._last_phone_check_ts).total_seconds()
            if dt < self.phone_poll_period_s:
                return

        self._last_phone_check_ts = now

        present = False
        try:
            present = self.box.is_phone_present()
        except Exception as e:
            print(f"[PhoneDetect] error: {e}")

        if present:
            print("[PhoneDetect] Phone detected -> locking")
            self._stop_wait_music()
            self._play_sfx(self.placed_sfx_path)

            # Lock using motors
            self.box.lock()
            self.state.gate = GateState.LOCKED

    # ---------- transitions ----------

    def _enter_mode(self, mode: Mode, block: Optional[ScheduledBlock]):
        if mode == self.state.mode and block == self.state.active_block:
            return

        print(f"[State] {self.state.mode.name} → {mode.name}")

        # leaving FOCUS/SLEEP -> stop wait music
        if self.state.mode in (Mode.FOCUS, Mode.SLEEP) and mode == Mode.IDLE:
            self._stop_wait_music()

        self.state.mode = mode
        self.state.active_block = block

        if mode == Mode.IDLE:
            # Unlock and play unlock sound (only if actually locked)
            if self.box.is_locked:
                self.box.unlock()
                self._play_sfx(self.unlock_sfx_path)
            self.state.gate = GateState.WAIT_PHONE

        elif mode in (Mode.FOCUS, Mode.SLEEP):
            # Entering a lock-requiring period:
            # start gate as WAIT_PHONE (will lock when detected)
            self.state.gate = GateState.WAIT_PHONE
            self._last_phone_check_ts = None

        elif mode == Mode.EMERGENCY:
            self._stop_wait_music()
            self.box.unlock()
            self.state.gate = GateState.WAIT_PHONE

    # ---------- schedule helpers ----------

    def _find_current_and_next(self, now: datetime, schedule: List[ScheduledBlock]):
        active = None
        nxt = None
        for block in sorted(schedule, key=lambda b: b.start):
            if block.start <= now < block.end:
                active = block
            elif block.start > now:
                nxt = block
                break
        return active, nxt

    # ---------- audio helpers ----------

    def _start_wait_music(self):
        if self._wait_music_playing:
            return
        try:
            self.music.music_play(self.wait_music_path)
            self._wait_music_playing = True
            print(f"[Music] waiting loop: {self.wait_music_path}")
        except Exception as e:
            print(f"[Music] cannot play wait music: {e}")

    def _stop_wait_music(self):
        if not self._wait_music_playing:
            return
        try:
            self.music.music_stop()
        except Exception as e:
            print(f"[Music] cannot stop wait music: {e}")
        self._wait_music_playing = False

    def _play_sfx(self, path: str):
        """
        Play a short one-shot effect.
        NOTE: robot_hat Music API might be single-channel; if it interrupts current audio,
        that's okay because we stop waiting music before sfx in our flow.
        """
        if not path:
            return
        try:
            self.music.music_play(path)
            print(f"[Music] sfx: {path}")
        except Exception as e:
            print(f"[Music] cannot play sfx {path}: {e}")
