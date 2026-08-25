"""
Cryo-con Model 32 black-body controller backend.

The controller is reached through the persistent udev alias ``/dev/blackbody``.
The alias is wrapped as a VISA serial resource so the physical ``ttyUSB``
number may change between Raspberry Pi boots without changing this module.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from datetime import datetime
from typing import Any

import pyvisa as visa

from default_config import BBCON_NAME

class BBCON:
    """Driver for the Cryo-con Model 32 black-body controller."""

    LINUX_ADDRESS = "ASRL/dev/blackbody::INSTR"
    WINDOWS_ADDRESS = "ASRL12::INSTR"
    VALID_RANGES = ("LOW", "MID", "HI")

    def __init__(
        self,
        addr: str | None = None,
        verbose: int = 1,
        *,
        resource_manager: Any | None = None,
        visa_backend: str = "@py",
        timeout_ms: int = 10_000,
        query_delay_s: float = 0.2,
        min_command_interval_s: float = 0.1,
    ) -> None:
        """
        
        Open and verify the serial connection.

        With RLock() implementend in self._io_lock and self._last_io_time,
        the class adds two layers of protection in the comunication with Cryo-Con
        The first layer avoids concurrent access to the device, while the
        second layer guarantees that the minimmum time between two commands is
        waited and respected.

        Parameters
        ----------
        addr:
            VISA resource address. On the Raspberry Pi the default is the
            stable udev alias ``ASRL/dev/blackbody::INSTR``.
        verbose:
            ``0`` disables connection messages, ``1`` reports success and
            ``2`` also prints the identification string.
        resource_manager:
            Optional ResourceManager injection, mainly useful for tests.
        visa_backend:
            VISA backend used when this class creates its own manager.
        timeout_ms:
            VISA read/write timeout in milliseconds.
        query_delay_s:
            Delay between the write and read phases of a VISA query.
        min_command_interval_s:
            Minimum separation between controller transactions. The Model 32
            should not be queried more frequently than about once per 100 ms.

        Raises
        ------
        ConnectionError
            If the VISA resource cannot be opened or does not answer ``*IDN?``.
        """

        if addr is None:
            addr = (
                self.WINDOWS_ADDRESS
                if sys.platform == "win32"
                else self.LINUX_ADDRESS
            )

        self.addr = addr
        self.device: Any | None = None
        self._io_lock = threading.RLock()
        self._last_io_time = 0.0
        self._min_command_interval_s = max(0.0, float(min_command_interval_s))
        self._resource_manager = (
            resource_manager
            if resource_manager is not None
            else visa.ResourceManager(visa_backend)
        )

        try:
            self.device = self._resource_manager.open_resource(
                self.addr,
                send_end=True,
                query_delay=float(query_delay_s),
            )
            self._configure_serial(timeout_ms=timeout_ms)
            identification = self.query("*IDN?")
            if not identification:
                raise RuntimeError("empty reply to *IDN?")
        except Exception as exc:
            self.close(verbose=False)
            raise ConnectionError(
                f"Black Body Controller not detected at {self.addr}: {exc}"
            ) from exc

        if verbose >= 1:
            print("\x1b[1;32m✅ Black Body Controller communication successful\x1b[0m")
        if verbose >= 2:
            print(f"\x1b[1;32mModel:\x1b[0m {identification}")

    @property
    def connected(self) -> bool:
        """Return whether a VISA session is currently open."""

        return self.device is not None

    def _configure_serial(self, timeout_ms: int) -> None:
        device = self._require_device()
        device.baud_rate = 9600
        device.data_bits = 8
        device.parity = visa.constants.Parity.none
        device.stop_bits = visa.constants.StopBits.one

        try:
            device.flow_control = visa.constants.VI_ASRL_FLOW_NONE
        except AttributeError:
            pass

        device.write_termination = "\r\n"
        device.read_termination = None
        device.timeout = int(timeout_ms)

        # Some VISA backends need the serial termination attributes set
        # explicitly when read_termination is None.
        try:
            device.set_visa_attribute(visa.constants.VI_ATTR_TERMCHAR, ord("\n"))
            device.set_visa_attribute(
                visa.constants.VI_ATTR_ASRL_END_IN,
                visa.constants.VI_ASRL_END_TERMCHAR,
            )
        except (AttributeError, visa.errors.VisaIOError):
            pass

    def _require_device(self) -> Any:
        if self.device is None:
            raise RuntimeError("Black Body Controller is not connected")
        return self.device

    def _wait_for_io_slot(self) -> None:
        elapsed = time.monotonic() - self._last_io_time
        wait_time = self._min_command_interval_s - elapsed
        if wait_time > 0:
            time.sleep(wait_time)

    def __enter__(self) -> "BBCON":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            self.stop_control()
        except Exception:
            pass

        self.close(verbose=False)

        if exc_type is not None:
            print(
                "\x1b[1;31m⚠️ Exception occurred inside BBCON context:\x1b[0m",
                exc_val,
            )
        return False

    def close(self, verbose: bool = True) -> None:
        """Close the controller session without changing its control state."""

        with self._io_lock:
            device, self.device = self.device, None
            if device is None:
                if verbose:
                    print("\x1b[1;33m⚠️ No active Cryo-con Model 32 connection\x1b[0m")
                return

            try:
                device.close()
            except Exception as exc:
                if verbose:
                    print(f"\x1b[1;31m✗ Error closing Cryo-con Model 32:\x1b[0m {exc}")
                return

        if verbose:
            print("\x1b[1;32m✅ Cryo-con Model 32 connection closed\x1b[0m")

    def command(self, command: str) -> None:
        """Send one SCPI command to the controller."""

        with self._io_lock:
            device = self._require_device()
            self._wait_for_io_slot()
            try:
                device.write(str(command))
            finally:
                self._last_io_time = time.monotonic()

    def query(self, query: str) -> str:
        """Send one SCPI query and return a reply without line terminators."""

        with self._io_lock:
            device = self._require_device()
            self._wait_for_io_slot()
            try:
                answer = device.query(str(query))
            finally:
                self._last_io_time = time.monotonic()

        return str(answer).strip()

    def query_identification(self) -> str:
        return self.query("*IDN?")

    def query_power(self) -> float:
        """Return loop 1 heater output as a percentage of full scale."""

        return _parse_float(self.query("LOOP 1:OUTPWR?"))

    def query_current(self) -> tuple[str, float, float]:
        """Return the legacy heater percentage, current and power estimate.

        The current/power conversion is retained from the original ``sctlib``
        implementation. Its units depend on the controller/heater configuration.
        """

        percentage = self.query("LOOP 1:HTRR?")
        control_range = self.query("LOOP 1:RANGE?").upper()
        percentage_value = _parse_float(percentage)

        factors = {"LOW": 1.0, "MID": 0.33, "HI": 0.1}
        try:
            current = factors[control_range] * percentage_value
        except KeyError as exc:
            raise ValueError(f"Unexpected heater range: {control_range!r}") from exc

        power = current**2 * 50
        return percentage, current, power

    def query_temperature(self) -> float:
        """Return input A temperature in the channel's configured units."""

        return _parse_float(self.query("INPUT A:TEMPER?"))

    def query_resistance(self) -> float:
        """Reject the incorrect resistance query present in the old class.

        The previous implementation sent ``INPUT A:TEMPER?`` and therefore
        returned temperature, not resistance. A verified, non-state-changing
        resistance query must be defined before this method can be exposed.
        """

        raise NotImplementedError(
            "query_resistance() was disabled because the original method returned "
            "temperature; no verified Model 32 resistance command is configured"
        )

    def query_variance(self) -> float:
        """Return input A temperature variance since the statistics reset."""

        return _parse_float(self.query("INPUT A:VARIANCE?"))

    def query_deviance(self) -> float:
        """Return input A standard deviation since the statistics reset."""

        variance = self.query_variance()
        if variance < 0:
            raise ValueError(f"Controller returned a negative variance: {variance}")
        return math.sqrt(variance)

    def set_PID(self, PID: tuple[float, float, float] | None) -> None:
        """Set loop 1 proportional, integral and differential gains."""

        if PID is None:
            return
        if not isinstance(PID, tuple) or len(PID) != 3:
            raise ValueError("PID must be a three-element tuple: (P, I, D)")

        p_gain, i_gain, d_gain = (float(value) for value in PID)
        self.command(f"LOOP 1:PGAIN {p_gain}")
        self.command(f"LOOP 1:IGAIN {i_gain}")
        self.command(f"LOOP 1:DGAIN {d_gain}")

    def query_PID(self, verbose: int = 1) -> tuple[str, str, str]:
        """Return loop 1 PID gains as controller reply strings."""

        p_gain = self.query("LOOP 1:PGAIN?")
        i_gain = self.query("LOOP 1:IGAIN?")
        d_gain = self.query("LOOP 1:DGAIN?")

        if verbose >= 1:
            print(f"\x1b[1;32mPID values:\x1b[0m {p_gain} {i_gain} {d_gain}")
        return p_gain, i_gain, d_gain

    @classmethod
    def _normalise_range(cls, control_range: str) -> str:
        value = str(control_range).strip().upper()
        if value == "HIGH":
            value = "HI"
        if value not in cls.VALID_RANGES:
            raise ValueError(
                f"Invalid heater range {control_range!r}; use LOW, MID or HI"
            )
        return value

    def query_range(self) -> str:
        return self.query("LOOP 1:RANGE?").upper()

    def set_range(self, control_range: str) -> None:
        try:
            self.command(f"LOOP 1:RANGE {self._normalise_range(control_range)}")
            return True
        except Exception as e:
            print(f"❌Error occurred while setting heater range for {BBCON_NAME}\nReason: {e}")
            return False
        
    def query_setpoint(self) -> float:
        return _parse_float(self.query("LOOP 1:SETPT?"))

    def set_setpoint(self, temperature: float, verbose: bool = True) -> bool:
        """ Temperature must be in Kelvin."""
        try:
            value = float(temperature)
        except Exception as e:
            print(f"❌Invalid temperature setpoint for {BBCON_NAME}: {temperature}\nReason: {e}")
            return False
        
        try:
            self.command(f"LOOP 1:SETPT {value}")
            if verbose: print(f"Set temperature setpoint for {BBCON_NAME} to {value} K.")
            return True
        except Exception as e:
            print(f"❌Setting temperature setpoint for {BBCON_NAME} failed\nReason: {e}")
            return False

    def start_control(self) -> None:
        self.command("CONTROL")

    def stop_control(self) -> None:
        self.command("STOP")

    def config(
        self,
        PID: tuple[float, float, float] | None = None,
        RANGE: str = "LOW",
        MAXPWR: float = 100.0,
    ) -> None:
        """Configure loop 1 for PID control and print the resulting settings."""

        control_range = self._normalise_range(RANGE)
        max_power_value = float(MAXPWR)
        if not 0.0 <= max_power_value <= 100.0:
            raise ValueError("MAXPWR must be between 0 and 100 percent")

        self.command("LOOP 1:TYPE PID")
        self.set_range(control_range)
        self.command(f"LOOP 1:MAXPWR {max_power_value}")
        self.set_PID(PID)

        control_type = self.query("LOOP 1:TYPE?")
        print(f"\x1b[1;32mControl type is:\x1b[0m {control_type}")

        self.query_PID()
        current_range = self.query_range()
        max_power = self.query("LOOP 1:MAXPWR?")
        self.set_setpoint(0.0)
        setpoint = self.query_setpoint()

        print(
            f"\x1b[1;32mRange:\x1b[0m {current_range} "
            f"\x1b[1;32mSetpoint:\x1b[0m {setpoint} "
            f"\x1b[1;32mMaxPower:\x1b[0m {max_power}%"
        )

    def go_to_temp(
        self,
        T: float | None = None,
        PID: tuple[float, float, float] | None = None,
        RANGE: str | None = None,
        MAXSET: float = 10.0,
        MAXPWR: float = 100.0,
        timeout: float = 300.0,
        navg: int = 10,
        sigma: float = 5.0,
        tolerance: float = 0.01,
        max_acceptable_std: float = 0.01,
    ) -> bool:
        """Start PID control and wait for stable temperature.

        ``sigma`` is retained for API compatibility with the original class;
        stability is determined by ``tolerance`` and ``max_acceptable_std``.
        """

        del sigma
        import numpy as np

        if navg < 1:
            raise ValueError("navg must be at least 1")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        target = self.query_temperature() if T is None else float(T)
        max_setpoint = float(MAXSET)
        if target > max_setpoint:
            target = max_setpoint
            print(f"\x1b[1;33mWARNING: T is limited to {max_setpoint} K\x1b[0m")

        control_range = self._normalise_range(RANGE or "LOW")
        max_power = float(MAXPWR)
        if not 0.0 <= max_power <= 100.0:
            raise ValueError("MAXPWR must be between 0 and 100 percent")

        self.set_PID(PID)
        self.query_PID()
        self.set_range(control_range)
        self.command(f"LOOP 1:MAXSET {max_setpoint}")
        self.set_setpoint(target)
        self.command(f"LOOP 1:MAXPWR {max_power}")

        current_range = self.query_range()
        setpoint = self.query_setpoint()
        configured_max_power = self.query("LOOP 1:MAXPWR?")
        print(
            f"\x1b[1;32mRange:\x1b[0m {current_range} "
            f"\x1b[1;32mSetpoint:\x1b[0m {setpoint:.3f} K "
            f"\x1b[1;32mMaxPower:\x1b[0m {configured_max_power}%"
        )

        self.start_control()
        start = datetime.now().timestamp()

        while True:
            try:
                temperatures: list[float] = []
                for _ in range(navg):
                    power = self.query_power()
                    temperature = self.query_temperature()

                    temperatures.append(temperature)
                    print(
                        "\r\x1b[2K\x1b[1;34m"
                        f"Heater: {power:.3f}%, Temp: {temperature:.3f} K, "
                        f"Target: {target:.3f} K\x1b[0m",
                        end="",
                        flush=True,
                    )
                    time.sleep(0.1)

                mean = float(np.mean(temperatures))
                std = float(np.std(temperatures))
                elapsed = datetime.now().timestamp() - start

                if abs(mean - target) < tolerance and std < max_acceptable_std:
                    print(f"\n\x1b[1;32mStable at {mean:.3f} K (±{std:.3f} K)\x1b[0m")
                    return True

                if elapsed > timeout:
                    print(
                        f"\n\x1b[1;33mTimeout ({elapsed:.1f}s), "
                        f"last: {mean:.3f} K ± {std:.3f} K\x1b[0m"
                    )
                    return False
            except Exception as exc:
                try:
                    self.stop_control()
                except Exception:
                    pass
                print(f"\n\x1b[1;31mError: {exc}\x1b[0m")
                return False


def _parse_float(value: str) -> float:
    """Extract the first float-looking token from a controller reply."""

    text = str(value).strip()
    numeric_characters = "+-0123456789.eE"
    token: list[str] = []

    for character in text:
        if character in numeric_characters:
            token.append(character)
        elif token:
            break

    if not token:
        raise ValueError(f"No numeric content in reply: {text!r}")
    return float("".join(token))


# Backward-compatible name used by the original sctlib implementation.
_parse__float = _parse_float