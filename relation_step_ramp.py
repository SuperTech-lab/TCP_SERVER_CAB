"""
@author: Victor
"""

import math
import statistics
import threading
import time

from collections import deque
from collections.abc import Callable
from typing import Any

from default_config import SAMPLE_CHANNELS
from lakeshore370 import RESISTANCE_RANGE_FULL_SCALE_OHMS


# Tagging the callback types for clarity. 
# These tags correspond to _append_relation_point() and 
# _finalize_relation() from tcp_server.py.
AppendPointCallback      = Callable[..., bool]
FinalizeRelationCallback = Callable[..., tuple[str | None, int]]
MxcTemperatureSampleCallback = Callable[
    [],
    tuple[float | None, float | None],
]

class RelationStepRampController:

    """
    Asynchronous controller for a backend-driven STEP_RAMP relation.

    STEP_RAMP never uses the native Lake Shore setpoint ramp. The backend
    will apply a sequence of discrete MXC setpoints and, at each point,
    wait for stabilization before measuring the selected sample channel.

    This class is deliberately decoupled from tcp_server.py:
    - the Lake Shore object and heater_mutex are injected;
    - relation-buffer writes are performed through append_point;
    - relation finalization is performed through finalize_relation.

    No RELATION_* global is imported or modified directly here.
    """

    VALID_STATES = {
        "CREATED",
        "PREPARE",
        "SET_SETPOINT",
        "WAIT_STABLE",
        "ENABLE_SAMPLE",
        "AUTORANGE",
        "SETTLE",
        "MEASURE",
        "RESTORE_MXC",
        "VERIFY_POINT",
        "STORE_POINT",
        "NEXT_POINT",
        "CLEANUP",
        "COMPLETE",
        "ABORTED",
        "ERROR",
    }

    TERMINAL_STATES = {
        "COMPLETE",
        "ABORTED",
        "ERROR",
    }

    # Conservative hardware settling after a scanner-channel
    # or resistance-range change.
    #
    # The Lake Shore 370 manual reports approximately 2–3 s
    # after a range change and states that scanner-channel
    # changes have similar settling behaviour.
    HARDWARE_SETTLING_AFTER_CHANGE_S = 3.0

    # RDGST? resistance-range status bits.
    R_OVER_STATUS_BIT  = 16
    R_UNDER_STATUS_BIT = 32

    # Lake Shore internal autorange reduces the resistance
    # range below 20 % of the current full-scale value.
    AUTORANGE_LOW_FRACTION = 0.20

    MIN_RESISTANCE_RANGE = 1
    MAX_RESISTANCE_RANGE = 22

    # These constants serve as validation for the wait time
    # read from the LakeShore. According to the manual, 
    # the values must be between 3 - 200 seconds
    MIN_CHANGE_PAUSE_S = 3.0
    MAX_CHANGE_PAUSE_S = 200.0

    def __init__(
        self,
        *,
        lakeshore: Any,
        heater_mutex: Any,
        relation_id: str,
        channel_number: int,
        setpoints_mk: list[float],
        target_mk: float,
        step_mk: float,
        tolerance_mk: float,
        stable_time_s: float,
        stability_timeout_s: float,
        stability_sample_interval_s: float,
        autorange_max_attempts: int,
        resistance_n_samples: int,
        resistance_sample_interval_s: float,
        resistance_max_attempts: int,
        max_std_mk: float | None = None,
        max_slope_mk_per_min: float | None = None,
        point_measurement_max_attempts: int | None = None,
        append_point: AppendPointCallback,
        finalize_relation: FinalizeRelationCallback,
        get_mxc_temperature_sample: MxcTemperatureSampleCallback,
    ):
        """
        Create one STEP_RAMP controller.

        Parameters
        ----------
        lakeshore
            Shared LakeShore370 instance owned by tcp_server.py.

        heater_mutex
            The same mutex used by tcp_server.py to serialize access to
            the Lake Shore. A new independent mutex must not be created
            for the controller.

        relation_id
            Identifier/file name of the RELATION owned by this controller.

        channel_number
            Single sample-resistance channel, selected from
            SAMPLE_CHANNELS. Only this sample channel is measured
            during the STEP_RAMP.

        setpoints_mk
            Complete discrete setpoint sequence in mK, including the first
            and final setpoints.

        target_mk
            Final requested STEP_RAMP temperature in mK.

        step_mk
            Positive step magnitude in mK.

        append_point
            Callback supplied by tcp_server.py. It is expected to be
            compatible with _append_relation_point().

        finalize_relation
            Callback supplied by tcp_server.py. It is expected to be
            compatible with _finalize_relation().
        """

        if lakeshore is None:
            raise ValueError(
                "lakeshore must be a valid LakeShore370 instance."
            )

        if heater_mutex is None:
            raise ValueError(
                "heater_mutex must be provided."
            )

        if not (
            hasattr(heater_mutex, "acquire")
            and hasattr(heater_mutex, "release")
        ):
            raise TypeError(
                "heater_mutex must provide acquire() and release()."
            )

        if not isinstance(relation_id, str) or not relation_id.strip():
            raise ValueError(
                "relation_id must be a non-empty string."
            )

        if (
            isinstance(channel_number, bool)
            or not isinstance(channel_number, int)
        ):
            raise TypeError(
                "channel_number must be an integer."
            )

        if channel_number not in SAMPLE_CHANNELS:
            raise ValueError(
                f"channel_number must be one of {SAMPLE_CHANNELS}."
            )

        if not isinstance(setpoints_mk, list) or not setpoints_mk:
            raise ValueError(
                "setpoints_mk must be a non-empty list."
            )

        try:
            normalized_setpoints = [
                float(value)
                for value in setpoints_mk
            ]

            target_mk = float(target_mk)
            step_mk = float(step_mk)

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "STEP_RAMP temperature values must be numeric."
            ) from exc

        if not all(
            math.isfinite(value)
            for value in normalized_setpoints
        ):
            raise ValueError(
                "All STEP_RAMP setpoints must be finite."
            )

        if not math.isfinite(target_mk):
            raise ValueError(
                "target_mk must be finite."
            )

        if not math.isfinite(step_mk):
            raise ValueError(
                "step_mk must be finite."
            )

        if step_mk <= 0:
            raise ValueError(
                "step_mk must be greater than zero."
            )
        try:
            tolerance_mk = float(tolerance_mk)
            stable_time_s = float(stable_time_s)
            stability_timeout_s = float(
                stability_timeout_s
            )
            stability_sample_interval_s = float(
                stability_sample_interval_s
            )
            resistance_sample_interval_s = float(
                resistance_sample_interval_s
            )

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "STEP_RAMP timing/stability parameters "
                "must be numeric."
            ) from exc


        positive_float_parameters = {
            "tolerance_mk":
                tolerance_mk,

            "stable_time_s":
                stable_time_s,

            "stability_timeout_s":
                stability_timeout_s,

            "stability_sample_interval_s":
                stability_sample_interval_s,
        }

        for name, value in positive_float_parameters.items():

            if (
                not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} must be finite and "
                    "greater than zero."
                )


        if (
            not math.isfinite(
                resistance_sample_interval_s
            )
            or resistance_sample_interval_s < 0
        ):
            raise ValueError(
                "resistance_sample_interval_s must be "
                "finite and non-negative."
            )


        if stability_timeout_s <= stable_time_s:
            raise ValueError(
                "stability_timeout_s must be greater "
                "than stable_time_s."
            )

        integer_parameters = {
            "autorange_max_attempts":
                autorange_max_attempts,

            "resistance_n_samples":
                resistance_n_samples,

            "resistance_max_attempts":
                resistance_max_attempts,
        }

        for name, value in integer_parameters.items():

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
            ):
                raise TypeError(
                    f"{name} must be an integer."
                )

            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero."
                )


        if (
            resistance_max_attempts
            < resistance_n_samples
        ):
            raise ValueError(
                "resistance_max_attempts must be greater "
                "than or equal to resistance_n_samples."
            )

        if max_std_mk is not None:

            try:
                max_std_mk = float(max_std_mk)

            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "max_std_mk must be numeric."
                ) from exc

            if (
                not math.isfinite(max_std_mk)
                or max_std_mk < 0
            ):
                raise ValueError(
                    "max_std_mk must be finite and "
                    "non-negative."
                )


        if max_slope_mk_per_min is not None:

            try:
                max_slope_mk_per_min = float(
                    max_slope_mk_per_min
                )

            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "max_slope_mk_per_min must be numeric."
                ) from exc

            if (
                not math.isfinite(
                    max_slope_mk_per_min
                )
                or max_slope_mk_per_min < 0
            ):
                raise ValueError(
                    "max_slope_mk_per_min must be finite "
                    "and non-negative."
                )


        if point_measurement_max_attempts is not None:

            if (
                isinstance(
                    point_measurement_max_attempts,
                    bool,
                )
                or not isinstance(
                    point_measurement_max_attempts,
                    int,
                )
            ):
                raise TypeError(
                    "point_measurement_max_attempts "
                    "must be an integer or None."
                )

            if point_measurement_max_attempts <= 0:
                raise ValueError(
                    "point_measurement_max_attempts must "
                    "be greater than zero."
                )

        if not math.isclose(
            normalized_setpoints[-1],
            target_mk,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "The final setpoint must match target_mk."
            )

        if not callable(append_point):
            raise TypeError(
                "append_point must be callable."
            )

        if not callable(finalize_relation):
            raise TypeError(
                "finalize_relation must be callable."
            )

        if not callable(get_mxc_temperature_sample):
            raise TypeError(
                "get_mxc_temperature_sample must be callable."
            )
        # ------------------------------------------------------------------
        # Injected server dependencies
        # ------------------------------------------------------------------

        self.ls = lakeshore
        self.heater_mutex = heater_mutex

        self._append_relation_point = append_point
        self._finalize_relation = finalize_relation
        self._get_mxc_temperature_sample = (
            get_mxc_temperature_sample
        )

        # ------------------------------------------------------------------
        # Immutable acquisition identity / geometry
        # ------------------------------------------------------------------

        self.relation_id = relation_id.strip()
        self.channel_number = channel_number

        self.setpoints_mk = normalized_setpoints
        self.initial_mk = normalized_setpoints[0]
        self.target_mk = target_mk
        self.step_mk = step_mk

        self.tolerance_mk = tolerance_mk

        self.stable_time_s = stable_time_s

        self.stability_timeout_s = (
            stability_timeout_s
        )

        self.stability_sample_interval_s = (
            stability_sample_interval_s
        )

        self.max_std_mk = max_std_mk

        self.max_slope_mk_per_min = (
            max_slope_mk_per_min
        )

        self.autorange_max_attempts = (
            autorange_max_attempts
        )

        self.resistance_n_samples = (
            resistance_n_samples
        )

        self.resistance_sample_interval_s = (
            resistance_sample_interval_s
        )

        self.resistance_max_attempts = (
            resistance_max_attempts
        )

        self.point_measurement_max_attempts = (
            point_measurement_max_attempts
        )

        self.total_points = len(
            self.setpoints_mk
        )

        # ------------------------------------------------------------------
        # Worker lifecycle
        # ------------------------------------------------------------------

        self._abort_event = threading.Event()

        self._thread: threading.Thread | None = None

        # Protects only this controller's private runtime/status state.
        # It is intentionally independent of relation_lock and heater_mutex.
        self._status_lock = threading.RLock()

        # ------------------------------------------------------------------
        # Live runtime status
        # ------------------------------------------------------------------

        self._state = "CREATED"

        # Internal point index is zero-based.
        self._current_point_index: int | None = None

        self._current_setpoint_mk: float | None = None

        # High-level controller temperatures are kept in mK.
        # Conversion to/from K should occur only at the driver boundary.
        self._current_mxc_temperature_mk: float | None = None

        self._stable_time_s = 0.0

        self._resistance_range: int | None = None

        self._last_resistance_ohm: float | None = None
        self._last_resistance_std_ohm: float | None = None

        self._mxc_settling_time_s: float | None = None
        self._sample_settling_time_s: float | None = None

        self._preflight_data: dict | None = None

        self._error: str | None = None

    # ======================================================================
    # Private status helpers
    # ======================================================================

    def _set_state(
        self,
        state: str,
    ) -> None:
        """
        Atomically update the controller state.
        """

        if state not in self.VALID_STATES:
            raise ValueError(
                f"Invalid STEP_RAMP state: {state!r}"
            )

        with self._status_lock:
            self._state = state

    def _set_error(
        self,
        error,
    ) -> None:
        """
        Store the latest controller error as text.
        """

        with self._status_lock:
            self._error = (
                None
                if error is None
                else str(error)
            )

    @classmethod
    def _calculate_settling_time_s(
        cls,
        pause_time_s: float,
        filter_settings: dict,
    ) -> float:
        """
        Calculate the minimum wait after a scanner-channel or
        resistance-range change before accepting a measurement.

        The Lake Shore settling sequence is treated as:

            hardware settling
            + configured change pause
            + firmware-filter settling

        The firmware-filter contribution is included only when the
        firmware filter is enabled.

        Parameters
        ----------
        pause_time_s
            Channel change-pause time reported by INSET?, in seconds.

        filter_settings
            Dictionary returned by LakeShore370.get_filter_settings().
            Expected keys:
                enabled
                settling_time_s
                window_percent

        Returns
        -------
        float
            Required settling time in seconds.

        Raises
        ------
        TypeError
            If filter_settings is not a dictionary or its enabled
            field is not boolean.

        ValueError
            If pause or filter settling values are invalid.
        """

        try:
            pause_time_s = float(pause_time_s)

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "pause_time_s must be numeric."
            ) from exc

        if (
            not math.isfinite(pause_time_s)
            or not (
                cls.MIN_CHANGE_PAUSE_S
                <= pause_time_s
                <= cls.MAX_CHANGE_PAUSE_S
            )
        ):
            raise ValueError(
                "pause_time_s must be finite and between "
                f"{cls.MIN_CHANGE_PAUSE_S:g} and "
                f"{cls.MAX_CHANGE_PAUSE_S:g} seconds."
            )
            
        if not isinstance(filter_settings, dict):
            raise TypeError(
                "filter_settings must be a dictionary."
            )

        if "enabled" not in filter_settings:
            raise ValueError(
                "filter_settings is missing 'enabled'."
            )

        filter_enabled = filter_settings["enabled"]

        if not isinstance(filter_enabled, bool):
            raise TypeError(
                "filter_settings['enabled'] must be boolean."
            )

        if "settling_time_s" not in filter_settings:
            raise ValueError(
                "filter_settings is missing 'settling_time_s'."
            )

        try:
            filter_settling_time_s = float(
                filter_settings["settling_time_s"]
            )

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Filter settling time must be numeric."
            ) from exc

        if (
            not math.isfinite(filter_settling_time_s)
            or filter_settling_time_s < 0
        ):
            raise ValueError(
                "Filter settling time must be finite "
                "and non-negative."
            )

        if not filter_enabled:
            filter_settling_time_s = 0.0

        return (
            cls.HARDWARE_SETTLING_AFTER_CHANGE_S
            + pause_time_s
            + filter_settling_time_s
        )


    def _preflight(self) -> dict:
        """
        Validate the Lake Shore configuration required by STEP_RAMP and
        capture the initial hardware state needed by the controller.

        This method performs read-only checks. It does not change the scan
        channel, sample state, resistance range or temperature setpoint.

        Returns
        -------
        dict
            Snapshot of the relevant initial Lake Shore configuration.

        Raises
        ------
        InterruptedError
            If STEP_RAMP was stopped before or during preflight.

        RuntimeError
            If the Lake Shore configuration is incompatible with STEP_RAMP
            or any required instrument value cannot be read reliably.
        """

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before preflight."
            )

        if not self.ls.connected:
            raise RuntimeError(
                "Lake Shore is not connected."
            )

        # Keep the hardware snapshot coherent. The telemetry thread cannot
        # interleave Lake Shore commands while these values are collected.
        with self.heater_mutex:

            # --------------------------------------------------------------
            # MXC temperature-control configuration
            # --------------------------------------------------------------

            control_settings = self.ls.get_control_settings(
                return_dict=True
            )

            control_mode = self.ls.get_control_mode()

            heater_range  = self.ls.get_control_range()
            heater_status = self.ls.get_heater_status()

            mxc_channel_status = self.ls.get_channel_status(
                6
            )

            mxc_reading_status = self.ls.get_reading_status(
                6
            )

            mxc_temperature_k = self.ls.get_temperature(
                6
            )

            mxc_setpoint_k = (
                self.ls.get_temperature_setpoint()
            )

            # --------------------------------------------------------------
            # Native Lake Shore ramp state
            # --------------------------------------------------------------

            ramp_parameters = self.ls.get_ramp_parameters()

            ramp_active = self.ls.get_ramp_status()

            # --------------------------------------------------------------
            # MXC settling configuration
            # --------------------------------------------------------------

            mxc_pause_time_s = self.ls.get_pause_time(
                6
            )

            mxc_filter_settings = (
                self.ls.get_filter_settings(6)
            )

            # --------------------------------------------------------------
            # Sample-channel configuration
            # --------------------------------------------------------------

            sample_channel_status = (
                self.ls.get_channel_status(
                    self.channel_number
                )
            )

            sample_pause_time_s = (
                self.ls.get_pause_time(
                    self.channel_number
                )
            )

            sample_filter_settings = (
                self.ls.get_filter_settings(
                    self.channel_number
                )
            )

            sample_sensor_settings = (
                self.ls.get_sensor_resistance_settings(
                    channel=self.channel_number,
                    return_dict=True,
                )
            )

        # Do not continue processing if stop was requested while the hardware
        # snapshot was being collected.
        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested during preflight."
            )

        # ==================================================================
        # Validate MXC control
        # ==================================================================

        if not isinstance(control_settings, dict):
            raise RuntimeError(
                "Could not read Lake Shore control settings."
            )

        control_uses_filtered_readings = (
            control_settings.get("filtered_readings")
        )

        if not isinstance(
            control_uses_filtered_readings,
            bool,
        ):
            raise RuntimeError(
                "Invalid filtered-readings value in CSET?."
            )

        if control_uses_filtered_readings:
            raise RuntimeError(
                "STEP_RAMP requires unfiltered PID feedback "
                "(CSET filter = 0)."
            )     

        try:
            controlled_channel = int(
                control_settings["controlled_channel"]
            )

        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "Invalid controlled-channel value in CSET?."
            ) from exc

        if controlled_channel != 6:
            raise RuntimeError(
                "STEP_RAMP requires MXC channel 6 "
                "as the temperature-control channel."
            )

        if control_settings.get("units") != "Kelvin":
            raise RuntimeError(
                "STEP_RAMP requires temperature-control "
                "units to be Kelvin."
            )

        if control_mode != 1:
            raise RuntimeError(
                "STEP_RAMP requires CMODE 1 "
                "(closed-loop PID control)."
            )

        # ==================================================================
        # Validate heater
        # ==================================================================

        if heater_range is None:
            raise RuntimeError(
                "Could not read the MXC heater range."
            )

        try:
            heater_range_code = int(heater_range)

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid MXC heater range: {heater_range!r}."
            ) from exc

        if heater_status is None:
            raise RuntimeError(
                "Could not read MXC heater status (HTRST?)."
            )

        try:
            heater_status_code = int(heater_status)

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid MXC heater status: {heater_status!r}."
            ) from exc

        if heater_status_code not in (0, 1):
            raise RuntimeError(
                f"Unexpected HTRST? value: {heater_status_code}."
            )

        if heater_status_code == 1:
            raise RuntimeError(
                "Lake Shore reports an open MXC heater "
                "(HTRST? = 1)."
            )

        if heater_range_code == 0:
            raise RuntimeError(
                "MXC heater range is OFF."
            )

        if not 1 <= heater_range_code <= 8:
            raise RuntimeError(
                f"Invalid MXC heater range: {heater_range_code}."
            )

        # ==================================================================
        # Validate MXC input / reading
        # ==================================================================

        if mxc_channel_status != 1:
            raise RuntimeError(
                "MXC channel 6 must be enabled."
            )

        if mxc_reading_status is None:
            raise RuntimeError(
                "Could not read RDGST? for MXC channel 6."
            )

        if mxc_reading_status != 0:
            status_flags = self.ls.describe_reading_status(
                mxc_reading_status
            )

            description = (
                " | ".join(status_flags)
                if status_flags
                else f"status {mxc_reading_status}"
            )

            raise RuntimeError(
                "MXC reading is invalid: "
                f"{description}."
            )

        try:
            mxc_temperature_k = float(
                mxc_temperature_k
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Could not read a numeric MXC temperature."
            ) from exc

        if (
            not math.isfinite(mxc_temperature_k)
            or mxc_temperature_k <= 0
        ):
            raise RuntimeError(
                "MXC temperature reading is invalid."
            )

        try:
            mxc_setpoint_k = float(
                mxc_setpoint_k
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Could not read a numeric MXC setpoint."
            ) from exc

        if not math.isfinite(mxc_setpoint_k):
            raise RuntimeError(
                "MXC setpoint is not finite."
            )

        # ==================================================================
        # Validate native-ramp status queries
        #
        # A currently enabled native ramp is not itself a preflight error.
        # The first discrete STEP_RAMP setpoint will disable it through
        # LakeShore370.set_channel_setpoint().
        # ==================================================================

        if not isinstance(ramp_parameters, dict):
            raise RuntimeError(
                "Could not read native Lake Shore ramp parameters."
            )

        if "enabled" not in ramp_parameters:
            raise RuntimeError(
                "Invalid RAMP? result."
            )

        if ramp_active is None:
            raise RuntimeError(
                "Could not read native Lake Shore ramp status."
            )

        native_ramp_enabled = bool(
            ramp_parameters["enabled"]
        )

        native_ramp_active = bool(
            ramp_active
        )

        # ==================================================================
        # Validate settling configuration
        # ==================================================================

        if not isinstance(mxc_filter_settings, dict):
            raise RuntimeError(
                "Could not read FILTER? configuration for CH6."
            )

        mxc_filter_enabled = (
            mxc_filter_settings.get("enabled")
        )

        if not isinstance(mxc_filter_enabled, bool):
            raise RuntimeError(
                "Invalid FILTER? state for CH6."
            )

        if mxc_filter_enabled:
            raise RuntimeError(
                "STEP_RAMP requires the CH6 firmware "
                "filter to be disabled."
            )
        
        if mxc_pause_time_s is None:
            raise RuntimeError(
                "Could not read MXC change-pause time."
            )

        if sample_pause_time_s is None:
            raise RuntimeError(
                f"Could not read CH{self.channel_number} "
                "change-pause time."
            )

        mxc_settling_time_s = (
            self._calculate_settling_time_s(
                pause_time_s=mxc_pause_time_s,
                filter_settings=mxc_filter_settings,
            )
        )

        sample_settling_time_s = (
            self._calculate_settling_time_s(
                pause_time_s=sample_pause_time_s,
                filter_settings=sample_filter_settings,
            )
        )

        # ==================================================================
        # Validate sample resistance configuration
        # ==================================================================

        if sample_channel_status not in (0, 1):
            raise RuntimeError(
                f"Could not determine CH{self.channel_number} "
                "enabled state."
            )

        if not isinstance(sample_sensor_settings, dict):
            raise RuntimeError(
                f"Could not read CH{self.channel_number} "
                "resistance settings."
            )

        try:
            excitation_mode = int(
                sample_sensor_settings["excitation_mode"]
            )

            excitation_range = int(
                sample_sensor_settings["excitation_range"]
            )

            resistance_range = int(
                sample_sensor_settings["resistance_range"]
            )

            internal_autorange = int(
                sample_sensor_settings["autorange"]
            )

            cs_off = int(
                sample_sensor_settings["excitation"]
            )

        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid RDGRNG? configuration for "
                f"CH{self.channel_number}."
            ) from exc

        if excitation_mode not in (0, 1):
            raise RuntimeError(
                "Invalid sample excitation mode."
            )

        maximum_excitation_range = (
            12
            if excitation_mode == 0
            else 22
        )

        if not (
            1
            <= excitation_range
            <= maximum_excitation_range
        ):
            raise RuntimeError(
                "Invalid sample excitation range."
            )

        if not 1 <= resistance_range <= 22:
            raise RuntimeError(
                "Invalid sample resistance range."
            )

        if internal_autorange not in (0, 1):
            raise RuntimeError(
                "Invalid sample internal-autorange state."
            )

        if cs_off not in (0, 1):
            raise RuntimeError(
                "Invalid sample excitation state."
            )

        # ==================================================================
        # Build normalized preflight snapshot
        # ==================================================================

        preflight_data = {
            "control_mode":
                control_mode,

            "heater_range":
                heater_range_code,

            "heater_status":
                heater_status_code,

            "initial_mxc_temperature_mk":
                mxc_temperature_k * 1000.0,

            "initial_mxc_setpoint_mk":
                mxc_setpoint_k * 1000.0,

            "native_ramp_enabled":
                native_ramp_enabled,

            "native_ramp_active":
                native_ramp_active,

            "mxc_pause_time_s":
                float(mxc_pause_time_s),

            "mxc_filter_settings":
                dict(mxc_filter_settings),

            "mxc_settling_time_s":
                mxc_settling_time_s,

            "sample_channel_initially_enabled":
                bool(sample_channel_status),

            "sample_pause_time_s":
                float(sample_pause_time_s),

            "sample_filter_settings":
                dict(sample_filter_settings),

            "sample_settling_time_s":
                sample_settling_time_s,

            "sample_excitation_mode":
                excitation_mode,

            "sample_excitation_range":
                excitation_range,

            "initial_resistance_range":
                resistance_range,

            "sample_internal_autorange_enabled":
                bool(internal_autorange),

            # RDGRNG calls this field "cs off":
            # 0 = excitation ON, 1 = excitation OFF.
            "sample_excitation_on":
                cs_off == 0,
        }

        # ==================================================================
        # Publish relevant live controller state
        # ==================================================================

        with self._status_lock:

            self._current_mxc_temperature_mk = (
                mxc_temperature_k * 1000.0
            )

            self._resistance_range = (
                resistance_range
            )

            self._mxc_settling_time_s = (
                mxc_settling_time_s
            )

            self._sample_settling_time_s = (
                sample_settling_time_s
            )

            self._preflight_data = dict(
                preflight_data
            )

        return preflight_data

    def _log_mxc_heater_checkpoint(
        self,
        *,
        context: str,
    ) -> tuple:
        """
        Read and log the physical MXC heater state without changing it.

        This diagnostic helper must only be called when heater_mutex is
        not already held by the current thread.
        """

        try:
            with self.heater_mutex:
                heater_range = self.ls.get_control_range()
                heater_status = self.ls.get_heater_status()

        except Exception as exc:
            print(
                "⚠️ STEP_RAMP MXC heater checkpoint failed: "
                f"{context}; error={exc}"
            )
            return None, None

        print(
            "🔎 STEP_RAMP MXC heater checkpoint: "
            f"{context}; "
            f"HTRRNG?={heater_range!r}, "
            f"HTRST?={heater_status!r}"
        )

        return heater_range, heater_status
        
    def _assert_mxc_heater_ready(
        self,
        *,
        context: str,
    ) -> None:
        """
        Verify that the MXC heater remains operational during STEP_RAMP.

        HTRRNG? must be greater than zero and HTRST? must report
        no open-heater condition.

        Raises
        ------
        RuntimeError
            If either status cannot be read or the heater is not operational.
        """

        with self.heater_mutex:

            heater_range = self.ls.get_control_range()
            heater_status = self.ls.get_heater_status()

        if heater_range is None:
            raise RuntimeError(
                "Could not read HTRRNG? during "
                f"{context}."
            )

        if heater_status is None:
            raise RuntimeError(
                "Could not read HTRST? during "
                f"{context}."
            )

        try:
            heater_range_code = int(
                heater_range
            )

            heater_status_code = int(
                heater_status
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Invalid MXC heater state during "
                f"{context}: "
                f"HTRRNG?={heater_range!r}, "
                f"HTRST?={heater_status!r}."
            ) from exc

        if heater_status_code not in (0, 1):
            raise RuntimeError(
                "Unexpected MXC heater status during "
                f"{context}: "
                f"HTRST?={heater_status_code}."
            )

        if heater_status_code != 0:
            raise RuntimeError(
                "Lake Shore reports an open-heater condition "
                f"during {context}: "
                f"HTRRNG?={heater_range_code}, "
                f"HTRST?={heater_status_code}."
            )

        if heater_range_code == 0:
            raise RuntimeError(
                "MXC heater range changed to OFF during "
                f"{context}: "
                f"HTRRNG?={heater_range_code}, "
                f"HTRST?={heater_status_code}."
            )

        if not 1 <= heater_range_code <= 8:
            raise RuntimeError(
                "Invalid MXC heater range during "
                f"{context}: HTRRNG?={heater_range_code}."
            )

    def _wait_for_stability(
        self,
        *,
        setpoint_mk: float,
        tolerance_mk: float,
        stable_time_s: float,
        timeout_s: float,
        sample_interval_s: float,
        max_std_mk: float | None = None,
        max_slope_mk_per_min: float | None = None,
    ) -> dict:
        """
        Wait until the MXC temperature is genuinely stable around a setpoint.

        Stability requires the temperature to remain continuously inside
        the requested tolerance band for stable_time_s.

        Optional statistical criteria may additionally limit:
            - temperature standard deviation;
            - absolute temperature slope.

        Only fresh telemetry samples are accepted. The temperature callback
        must return:

            (temperature_mk, sample_monotonic_s)

        where sample_monotonic_s is the time.monotonic() value recorded when
        that temperature sample was actually acquired.

        During this state:
            - the sample channel is forced OFF;
            - scanner channel 6 is selected;
            - autoscan is disabled.

        Long waits never hold heater_mutex and are interruptible through
        _abort_event.

        Returns
        -------
        dict
            Statistics for the stable temperature window.

        Raises
        ------
        InterruptedError
            If STEP_RAMP stop is requested.

        TimeoutError
            If stability is not reached within timeout_s.

        ValueError
            If a stability parameter is invalid.

        RuntimeError
            If the Lake Shore cannot be placed in the required MXC
            measurement state or the telemetry callback is malformed.
        """

        # ==================================================================
        # Validate parameters
        # ==================================================================

        try:
            setpoint_mk = float(setpoint_mk)
            tolerance_mk = float(tolerance_mk)
            stable_time_s = float(stable_time_s)
            timeout_s = float(timeout_s)
            sample_interval_s = float(sample_interval_s)

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "STEP_RAMP stability parameters must be numeric."
            ) from exc

        numeric_parameters = {
            "setpoint_mk": setpoint_mk,
            "tolerance_mk": tolerance_mk,
            "stable_time_s": stable_time_s,
            "timeout_s": timeout_s,
            "sample_interval_s": sample_interval_s,
        }

        for name, value in numeric_parameters.items():

            if not math.isfinite(value):
                raise ValueError(
                    f"{name} must be finite."
                )

        if tolerance_mk <= 0:
            raise ValueError(
                "tolerance_mk must be greater than zero."
            )

        if stable_time_s <= 0:
            raise ValueError(
                "stable_time_s must be greater than zero."
            )

        if timeout_s <= 0:
            raise ValueError(
                "timeout_s must be greater than zero."
            )

        if sample_interval_s <= 0:
            raise ValueError(
                "sample_interval_s must be greater than zero."
            )

        if timeout_s <= stable_time_s:
            raise ValueError(
                "timeout_s must be greater than stable_time_s."
            )

        if max_std_mk is not None:

            try:
                max_std_mk = float(max_std_mk)

            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "max_std_mk must be numeric."
                ) from exc

            if (
                not math.isfinite(max_std_mk)
                or max_std_mk < 0
            ):
                raise ValueError(
                    "max_std_mk must be finite and non-negative."
                )

        if max_slope_mk_per_min is not None:

            try:
                max_slope_mk_per_min = float(
                    max_slope_mk_per_min
                )

            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "max_slope_mk_per_min must be numeric."
                ) from exc

            if (
                not math.isfinite(max_slope_mk_per_min)
                or max_slope_mk_per_min < 0
            ):
                raise ValueError(
                    "max_slope_mk_per_min must be finite "
                    "and non-negative."
                )

        if self._mxc_settling_time_s is None:
            raise RuntimeError(
                "STEP_RAMP preflight must run before "
                "waiting for stability."
            )

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before "
                "stability wait."
            )

        self._set_state("WAIT_STABLE")

        wait_started = time.monotonic()
        deadline = wait_started + timeout_s

        # ==================================================================
        # Enforce the WAIT_STABLE hardware state
        #
        # Sample OFF
        # SCAN 6,0
        # ==================================================================

        # Verify the WAIT_STABLE hardware state without writing anything.
        #
        # The sample channel and scanner are prepared before SETP. Writing
        # INSET or SCAN here would occur after the setpoint change and could
        # override the Lake Shore setpoint-change pause.

        with self.heater_mutex:

            sample_status = self.ls.get_channel_status(
                self.channel_number
            )

            scan_status = self.ls.get_autoscan()

        if sample_status is None:
            raise RuntimeError(
                f"Could not read CH{self.channel_number} "
                "enabled state before MXC stabilization."
            )

        try:
            sample_status = int(sample_status)

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid CH{self.channel_number} enabled state: "
                f"{sample_status!r}."
            ) from exc

        if sample_status != 0:
            raise RuntimeError(
                f"CH{self.channel_number} must already be OFF "
                "before entering WAIT_STABLE."
            )

        if (
            not isinstance(scan_status, (list, tuple))
            or len(scan_status) != 2
        ):
            raise RuntimeError(
                f"Invalid SCAN? result before MXC stabilization: "
                f"{scan_status!r}."
            )

        try:
            active_channel = int(scan_status[0])
            autoscan_enabled = int(scan_status[1])

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Non-numeric SCAN? result before MXC "
                f"stabilization: {scan_status!r}."
            ) from exc

        if active_channel != 6 or autoscan_enabled != 0:
            raise RuntimeError(
                "WAIT_STABLE requires the scanner to have been "
                "prepared as SCAN 6,0 before the setpoint change; "
                f"received SCAN?={scan_status!r}."
            )

        self._assert_mxc_heater_ready(
            context=(
                "WAIT_STABLE verified SCAN 6,0 at "
                f"{setpoint_mk:g} mK"
            )
        )

        # ==================================================================
        # Wait for scanner/filter settling.
        #
        # heater_mutex is deliberately NOT held here.
        # ==================================================================

        remaining_s = deadline - time.monotonic()

        if remaining_s <= 0:
            raise TimeoutError(
                "STEP_RAMP stabilization timeout expired "
                "before MXC settling completed."
            )

        settling_wait_s = min(
            self._mxc_settling_time_s,
            remaining_s,
        )

        if self._abort_event.wait(
            settling_wait_s
        ):
            raise InterruptedError(
                "STEP_RAMP stop requested during "
                "MXC settling."
            )

        if time.monotonic() >= deadline:
            raise TimeoutError(
                "STEP_RAMP stabilization timeout expired "
                "during MXC settling."
            )

        # Do not accept any telemetry sample acquired before the scanner/
        # filter settling period ended.
        accept_samples_after = time.monotonic()

        # ==================================================================
        # Stability window
        # ==================================================================

        samples = deque()

        last_source_timestamp = None

        latest_temperature_mk = None
        latest_mean_mk = None
        latest_std_mk = None
        latest_slope_mk_per_min = None
        latest_mean_error_mk = None

        while True:

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested while "
                    "waiting for MXC stability."
                )

            now = time.monotonic()

            if now >= deadline:

                with self._status_lock:
                    self._stable_time_s = 0.0

                raise TimeoutError(
                    "MXC did not reach STEP_RAMP stability "
                    f"within {timeout_s:g} s. "
                    f"Last temperature="
                    f"{latest_temperature_mk!r} mK, "
                    f"mean={latest_mean_mk!r} mK, "
                    f"std={latest_std_mk!r} mK, "
                    f"slope={latest_slope_mk_per_min!r} "
                    "mK/min."
                )

            self._assert_mxc_heater_ready(
                context=(
                    "WAIT_STABLE at "
                    f"{setpoint_mk:g} mK"
                )
            )

            # --------------------------------------------------------------
            # Obtain latest cached MXC sample
            # --------------------------------------------------------------

            sample = (
                self._get_mxc_temperature_sample()
            )

            if (
                not isinstance(sample, tuple)
                or len(sample) != 2
            ):
                raise RuntimeError(
                    "get_mxc_temperature_sample() must "
                    "return "
                    "(temperature_mk, sample_monotonic_s)."
                )

            temperature_mk, source_timestamp = sample

            # No valid telemetry sample is currently available.
            if (
                temperature_mk is None
                or source_timestamp is None
            ):
                samples.clear()

                with self._status_lock:
                    self._stable_time_s = 0.0

            else:

                try:
                    temperature_mk = float(
                        temperature_mk
                    )

                    source_timestamp = float(
                        source_timestamp
                    )

                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "MXC telemetry callback returned "
                        "non-numeric data."
                    ) from exc

                if (
                    not math.isfinite(temperature_mk)
                    or not math.isfinite(source_timestamp)
                ):
                    raise RuntimeError(
                        "MXC telemetry callback returned "
                        "non-finite data."
                    )

                # ----------------------------------------------------------
                # Process only genuinely new telemetry.
                # ----------------------------------------------------------

                new_sample = (
                    source_timestamp
                    >= accept_samples_after
                    and (
                        last_source_timestamp is None
                        or source_timestamp
                        > last_source_timestamp
                    )
                )

                if new_sample:

                    last_source_timestamp = (
                        source_timestamp
                    )

                    latest_temperature_mk = (
                        temperature_mk
                    )

                    error_mk = (
                        temperature_mk
                        - setpoint_mk
                    )

                    with self._status_lock:
                        self._current_mxc_temperature_mk = (
                            temperature_mk
                        )

                    # ------------------------------------------------------
                    # Leaving the tolerance band immediately destroys the
                    # current stability candidate.
                    # ------------------------------------------------------

                    if abs(error_mk) > tolerance_mk:

                        samples.clear()

                        with self._status_lock:
                            self._stable_time_s = 0.0

                    else:

                        samples.append(
                            (
                                source_timestamp,
                                temperature_mk,
                            )
                        )

                        # --------------------------------------------------
                        # Keep approximately the last stable_time_s while
                        # preserving one sample just before the cutoff.
                        # This ensures the time span can actually cover the
                        # requested stability duration.
                        # --------------------------------------------------

                        cutoff = (
                            source_timestamp
                            - stable_time_s
                        )

                        while (
                            len(samples) >= 2
                            and samples[1][0] <= cutoff
                        ):
                            samples.popleft()

                        candidate_duration_s = (
                            source_timestamp
                            - samples[0][0]
                        )

                        with self._status_lock:
                            self._stable_time_s = (
                                candidate_duration_s
                            )

                        # --------------------------------------------------
                        # At least three independent samples are required
                        # before evaluating dispersion and slope.
                        # --------------------------------------------------

                        if (
                            candidate_duration_s
                            >= stable_time_s
                            and len(samples) >= 3
                        ):

                            temperatures_mk = [
                                item[1]
                                for item in samples
                            ]

                            timestamps_s = [
                                item[0]
                                for item in samples
                            ]

                            mean_mk = statistics.fmean(
                                temperatures_mk
                            )

                            std_mk = statistics.pstdev(
                                temperatures_mk
                            )

                            mean_error_mk = (
                                mean_mk
                                - setpoint_mk
                            )

                            # ----------------------------------------------
                            # Linear regression T(t).
                            #
                            # slope returned in mK/min.
                            # ----------------------------------------------

                            t0 = timestamps_s[0]

                            relative_times_s = [
                                timestamp - t0
                                for timestamp in timestamps_s
                            ]

                            mean_t = statistics.fmean(
                                relative_times_s
                            )

                            denominator = sum(
                                (t - mean_t) ** 2
                                for t in relative_times_s
                            )

                            if denominator <= 0:
                                slope_mk_per_min = float(
                                    "inf"
                                )

                            else:

                                numerator = sum(
                                    (
                                        t - mean_t
                                    )
                                    * (
                                        temperature - mean_mk
                                    )
                                    for t, temperature in zip(
                                        relative_times_s,
                                        temperatures_mk,
                                    )
                                )

                                slope_mk_per_s = (
                                    numerator
                                    / denominator
                                )

                                slope_mk_per_min = (
                                    slope_mk_per_s
                                    * 60.0
                                )

                            latest_mean_mk = mean_mk
                            latest_std_mk = std_mk
                            latest_slope_mk_per_min = (
                                slope_mk_per_min
                            )
                            latest_mean_error_mk = (
                                mean_error_mk
                            )

                            # ----------------------------------------------
                            # Stability criteria
                            # ----------------------------------------------

                            mean_ok = (
                                abs(mean_error_mk)
                                <= tolerance_mk
                            )

                            std_ok = (
                                max_std_mk is None
                                or std_mk <= max_std_mk
                            )

                            slope_ok = (
                                max_slope_mk_per_min is None
                                or abs(slope_mk_per_min)
                                <= max_slope_mk_per_min
                            )

                            if (
                                mean_ok
                                and std_ok
                                and slope_ok
                            ):
                                return {
                                    "stable": True,
                                    "setpoint_mk":
                                        setpoint_mk,

                                    "temperature_mk":
                                        temperature_mk,

                                    "mean_mk":
                                        mean_mk,

                                    "mean_error_mk":
                                        mean_error_mk,

                                    "std_mk":
                                        std_mk,

                                    "slope_mk_per_min":
                                        slope_mk_per_min,

                                    "stable_time_s":
                                        candidate_duration_s,

                                    "n_samples":
                                        len(samples),

                                    "elapsed_s":
                                        (
                                            time.monotonic()
                                            - wait_started
                                        ),
                                }

            # ==============================================================
            # Interruptible polling interval
            # ==============================================================

            remaining_s = (
                deadline - time.monotonic()
            )

            if remaining_s <= 0:
                continue

            sleep_s = min(
                sample_interval_s,
                remaining_s,
            )

            if self._abort_event.wait(sleep_s):
                raise InterruptedError(
                    "STEP_RAMP stop requested while "
                    "waiting for MXC stability."
                )

    def _external_autorange(
        self,
        *,
        max_attempts: int,
    ) -> dict:
        """
        Select an appropriate sample resistance range using
        backend-controlled autoranging.

        The Lake Shore internal autorange remains disabled.

        Range-selection rules reproduce the Model 370 autorange
        criteria while leaving excitation mode/range unchanged:

            R. OVER
                Increase resistance range.

            R. UNDER
                Measurement error. This is a negative-direction
                resistance overload, not an indication that the
                resistance range should be decreased.

            Valid reading, |R| >= full scale
                Increase resistance range.

            Valid reading, |R| < 20 % full scale
                Decrease resistance range.

            Otherwise
                Accept the current resistance range.

        Range changes are performed one step at a time and followed
        by the configured sample settling time.

        Each range decision follows a newly observed, completed
        CH6 -> sample -> CH6 cycle. The final autorange reading
        is not counted as a resistance sample.

        Parameters
        ----------
        max_attempts
            Maximum number of resistance/status measurements used
            while searching for an appropriate range.

        Returns
        -------
        dict
            Information about the selected resistance range and
            final valid reading.

        Raises
        ------
        InterruptedError
            If STEP_RAMP stop is requested.

        RuntimeError
            If the measurement state is invalid, Lake Shore reports
            an unrelated RDGST error, R. UNDER occurs, or a suitable
            resistance range cannot be selected.
        """

        # ==================================================================
        # Validate prerequisites
        # ==================================================================

        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
        ):
            raise TypeError(
                "max_attempts must be an integer."
            )

        if max_attempts <= 0:
            raise ValueError(
                "max_attempts must be greater than zero."
            )

        try:
            mxc_settling_time_s = float(self._mxc_settling_time_s)
            sample_settling_time_s = float(self._sample_settling_time_s)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(
                "STEP_RAMP preflight must provide valid channel settling "
                "times before external autoranging."
            ) from exc

        if any(
            not math.isfinite(value) or value <= 0
            for value in (mxc_settling_time_s, sample_settling_time_s)
        ):
            raise RuntimeError(
                "Channel settling times must be finite and greater than zero."
            )

        # Firmware dwell times during control/sample alternation.
        nominal_cycle_s = (
            mxc_settling_time_s + 5.0
            + sample_settling_time_s + 1.0
        )

        # Allow an in-progress visit plus a full new cycle and an I/O margin.
        sample_visit_timeout_s = 2.0 * nominal_cycle_s + 10.0

        if self._resistance_range is None:
            raise RuntimeError(
                "No initial resistance range is available."
            )

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before autoranging."
            )

        self._set_state("AUTORANGE")

        try:
            current_range = int(
                self._resistance_range
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Invalid current resistance range."
            ) from exc

        if (
            current_range
            not in RESISTANCE_RANGE_FULL_SCALE_OHMS
        ):
            raise RuntimeError(
                f"Resistance range {current_range} "
                "has no full-scale definition."
            )

        # ==================================================================
        # Verify ENABLE_SAMPLE state
        # ==================================================================

        with self.heater_mutex:

            sample_status = (
                self.ls.get_channel_status(
                    self.channel_number
                )
            )

            scan_status = self.ls.get_autoscan()

        try:
            sample_status = int(
                sample_status
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Could not determine CH"
                f"{self.channel_number} enabled state."
            ) from exc

        if sample_status != 1:
            raise RuntimeError(
                f"CH{self.channel_number} must be enabled "
                "before external autoranging."
            )

        if (
            not isinstance(scan_status, (list, tuple))
            or len(scan_status) < 2
        ):
            raise RuntimeError(
                "Could not determine Lake Shore scan state."
            )

        try:

            selected_channel = int(
                scan_status[0]
            )

            autoscan_enabled = int(
                scan_status[1]
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid SCAN? result: {scan_status!r}."
            ) from exc

        if autoscan_enabled != 0:
            raise RuntimeError(
                "Lake Shore autoscan must remain OFF "
                "during external autoranging."
            )

        if selected_channel not in (
            6,
            self.channel_number,
        ):
            raise RuntimeError(
                "Unexpected active scanner channel during "
                "external autoranging: "
                f"expected CH6 or CH{self.channel_number}, "
                f"received CH{selected_channel}."
            )
        # ==================================================================
        # Force software-autorange configuration
        #
        # Preserve excitation mode/range.
        # Internal Lake Shore autorange OFF.
        # Sample excitation ON.
        # ==================================================================

        with self.heater_mutex:

            range_set_ok = (
                self.ls.set_resistance_measurement_range(
                    channel=self.channel_number,
                    resistance_range=current_range,
                    autorange=False,
                    excitation_on=True,
                )
            )

        if not range_set_ok:
            raise RuntimeError(
                f"Could not configure CH"
                f"{self.channel_number} resistance "
                f"range {current_range}."
            )

        self._assert_mxc_heater_ready(
            context=(
                f"after configuring CH{self.channel_number} "
                "for external autoranging"
            )
        )

        with self._status_lock:
            self._resistance_range = (
                current_range
            )

        # Configuration may have changed excitation/autorange
        # even if the resistance-range number did not change.
        if self._abort_event.wait(
            self._sample_settling_time_s
        ):
            raise InterruptedError(
                "STEP_RAMP stop requested during "
                "sample settling before autoranging."
            )

        range_changes = 0

        # ==================================================================
        # Software autorange loop
        # ==================================================================

        for attempt in range(
            1,
            max_attempts + 1,
        ):

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested during "
                    "autoranging."
                )

                        # Wait outside heater_mutex for a new completed sample visit.
            self._wait_for_new_sample_visit(
                timeout_s=sample_visit_timeout_s,
                poll_interval_s=0.2,
            )

            # Atomic: RDGST? -> RDGR? -> RDGST?
            with self.heater_mutex:

                if self.abort_requested():
                    raise InterruptedError(
                        "STEP_RAMP stop requested before autorange readout."
                    )

                reading = (
                    self.ls.read_resistance_with_status(
                        self.channel_number
                    )
                )

            if not isinstance(reading, dict):
                raise RuntimeError(
                    "Lake Shore returned an invalid "
                    "resistance measurement result."
                )

            try:

                status_code = int(
                    reading["status_code"]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                raise RuntimeError(
                    "Resistance measurement did not "
                    "contain a valid status code."
                ) from exc

            if not 0 <= status_code <= 255:
                raise RuntimeError(
                    f"Invalid RDGST status code: "
                    f"{status_code}."
                )

            # --------------------------------------------------------------
            # Separate resistance overload flags from all other errors.
            # --------------------------------------------------------------

            range_status_mask = (
                self.R_OVER_STATUS_BIT
                | self.R_UNDER_STATUS_BIT
            )

            range_status = (
                status_code
                & range_status_mask
            )

            unrelated_status = (
                status_code
                & ~range_status_mask
            )

            if unrelated_status:

                status_flags = reading.get(
                    "status_flags",
                    [],
                )

                description = (
                    " | ".join(status_flags)
                    if status_flags
                    else str(status_code)
                )

                raise RuntimeError(
                    "Lake Shore reported a non-range "
                    "measurement error during autoranging: "
                    f"{description}."
                )

            # --------------------------------------------------------------
            # R. UNDER is NOT a command to decrease the range.
            #
            # Lake Shore defines it as the negative-direction equivalent
            # of R. OVER, normally associated with incorrect lead polarity.
            # --------------------------------------------------------------

            if (
                range_status
                & self.R_UNDER_STATUS_BIT
            ):

                status_flags = reading.get(
                    "status_flags",
                    [],
                )

                description = (
                    " | ".join(status_flags)
                    if status_flags
                    else "R. UNDER"
                )

                raise RuntimeError(
                    "Lake Shore reported resistance underload "
                    "during autoranging: "
                    f"{description}. "
                    "R. UNDER is a negative-direction overload "
                    "and must not be used to decrease the "
                    "resistance range."
                )

            # ==============================================================
            # Determine next range
            # ==============================================================

            new_range = None
            resistance_ohm = None
            full_scale_ohm = (
                RESISTANCE_RANGE_FULL_SCALE_OHMS[
                    current_range
                ]
            )

            # --------------------------------------------------------------
            # Positive resistance overload.
            #
            # RDGR may not be valid here, so no resistance value is
            # required to decide that the range must increase.
            # --------------------------------------------------------------

            if (
                range_status
                == self.R_OVER_STATUS_BIT
            ):

                if (
                    current_range
                    >= self.MAX_RESISTANCE_RANGE
                ):
                    raise RuntimeError(
                        "Resistance remains over-range at "
                        "Lake Shore range 22."
                    )

                new_range = (
                    current_range + 1
                )

            # --------------------------------------------------------------
            # RDGST == 0: use the actual resistance value and the
            # full-scale value of the current range.
            # --------------------------------------------------------------

            elif range_status == 0:

                if not reading.get("valid"):
                    raise RuntimeError(
                        "Resistance reading has zero RDGST "
                        "status but was reported as invalid."
                    )

                resistance_ohm = reading.get(
                    "resistance_ohm"
                )

                try:

                    resistance_ohm = float(
                        resistance_ohm
                    )

                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    raise RuntimeError(
                        "Autorange produced a non-numeric "
                        "resistance reading."
                    ) from exc

                if not math.isfinite(
                    resistance_ohm
                ):
                    raise RuntimeError(
                        "Autorange produced a non-finite "
                        "resistance reading."
                    )

                if resistance_ohm < 0:
                    raise RuntimeError(
                        "Autorange produced a negative "
                        "resistance reading."
                    )

                resistance_magnitude_ohm = resistance_ohm

                low_threshold_ohm = (
                    self.AUTORANGE_LOW_FRACTION
                    * full_scale_ohm
                )

                # ----------------------------------------------------------
                # Lake Shore increases the range when the measurement
                # reaches full scale.
                #
                # RDGST may still be zero because the input has roughly
                # 20 % overrange capability.
                # ----------------------------------------------------------

                if (
                    resistance_magnitude_ohm
                    >= full_scale_ohm
                    and current_range
                    < self.MAX_RESISTANCE_RANGE
                ):

                    new_range = (
                        current_range + 1
                    )

                # ----------------------------------------------------------
                # Below 20 % full scale, decrease the range to improve
                # measurement resolution.
                # ----------------------------------------------------------

                elif (
                    resistance_magnitude_ohm
                    < low_threshold_ohm
                    and current_range
                    > self.MIN_RESISTANCE_RANGE
                ):

                    new_range = (
                        current_range - 1
                    )

                # ----------------------------------------------------------
                # Appropriate range found.
                #
                # At range 1 or range 22 we also accept a valid reading
                # when no further range exists in the required direction.
                # ----------------------------------------------------------

                else:

                    with self._status_lock:
                        self._resistance_range = (
                            current_range
                        )

                    return {
                        "ok":
                            True,

                        "resistance_range":
                            current_range,

                        "resistance_ohm":
                            resistance_ohm,

                        "full_scale_ohm":
                            full_scale_ohm,

                        "range_fraction":
                            (
                                resistance_magnitude_ohm
                                / full_scale_ohm
                            ),

                        "attempts":
                            attempt,

                        "range_changes":
                            range_changes,

                        "status_code":
                            status_code,

                        "status_flags":
                            list(
                                reading.get(
                                    "status_flags",
                                    []
                                )
                            ),
                    }

            else:

                raise RuntimeError(
                    "Unexpected resistance-range "
                    f"status: {status_code}."
                )

            # ==============================================================
            # A range change is required.
            #
            # Do not perform an unverified range change if no measurement
            # attempt remains afterwards.
            # ==============================================================

            if attempt >= max_attempts:
                break

            if (
                new_range
                not in RESISTANCE_RANGE_FULL_SCALE_OHMS
            ):
                raise RuntimeError(
                    f"Calculated invalid resistance "
                    f"range {new_range}."
                )

            # --------------------------------------------------------------
            # Apply exactly one range step.
            #
            # Excitation mode/range are preserved by the driver.
            # Internal autorange remains OFF.
            # --------------------------------------------------------------

            with self.heater_mutex:

                range_set_ok = (
                    self.ls.set_resistance_measurement_range(
                        channel=self.channel_number,
                        resistance_range=new_range,
                        autorange=False,
                        excitation_on=True,
                    )
                )

            if not range_set_ok:
                raise RuntimeError(
                    f"Could not configure CH"
                    f"{self.channel_number} resistance "
                    f"range {new_range}."
                )

            self._assert_mxc_heater_ready(
                context=(
                    f"after changing CH{self.channel_number} "
                    f"resistance range to {new_range}"
                )
            )

            current_range = new_range
            range_changes += 1

            with self._status_lock:
                self._resistance_range = (
                    current_range
                )

            # --------------------------------------------------------------
            # Every range change requires settling.
            #
            # heater_mutex is deliberately NOT held during this wait.
            # --------------------------------------------------------------

            if self._abort_event.wait(
                self._sample_settling_time_s
            ):
                raise InterruptedError(
                    "STEP_RAMP stop requested during "
                    "resistance-range settling."
                )

        # ==================================================================
        # No suitable range found within max_attempts
        # ==================================================================

        raise RuntimeError(
            "External resistance autorange did not converge "
            f"after {max_attempts} attempts. "
            f"Last range={current_range}."
        )

    def _wait_for_new_sample_visit(
        self,
        *,
        timeout_s: float,
        poll_interval_s: float = 0.2,
    ) -> None:
        """
        Wait passively for an observed CH6 -> sample -> CH6 cycle.

        Ignore any sample visit already in progress at entry.
        Do not send SCAN commands or modify channel/PID settings.
        The caller must read resistance after this method returns.
        """
        for name, value in (
            ("timeout_s", timeout_s),
            ("poll_interval_s", poll_interval_s),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric.")

            try:
                valid = math.isfinite(value) and value > 0
            except OverflowError:
                valid = False

            if not valid:
                raise ValueError(f"{name} must be finite and greater than zero.")

        if self.channel_number not in SAMPLE_CHANNELS:
            raise ValueError("The sample channel must be CH9 through CH14.")

        deadline = time.monotonic() + float(timeout_s)
        phase = "WAIT_CONTROL"
        last_scan_status = None

        while True:
            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested while waiting for a new sample visit."
                )

            if time.monotonic() >= deadline:
                break

            # The driver protects each query; do not hold heater_mutex here.
            scan_status = self.ls.get_autoscan()

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested while waiting for a new sample visit."
                )

            if time.monotonic() >= deadline:
                break

            if (
                not isinstance(scan_status, (list, tuple))
                or len(scan_status) != 2
            ):
                raise RuntimeError(
                    f"Invalid SCAN? result while waiting for a sample visit: "
                    f"{scan_status!r}."
                )

            try:
                active_channel = int(scan_status[0])
                autoscan_enabled = int(scan_status[1])
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError(
                    f"Invalid SCAN? result: {scan_status!r}."
                ) from exc

            if autoscan_enabled != 0:
                raise RuntimeError(
                    "Lake Shore autoscan must remain OFF during STEP_RAMP."
                )

            if active_channel not in (6, self.channel_number):
                raise RuntimeError(
                    f"Unexpected active scanner channel: CH{active_channel}. "
                    f"Expected CH6 or CH{self.channel_number}."
                )

            last_scan_status = (active_channel, autoscan_enabled)

            if phase == "WAIT_CONTROL" and active_channel == 6:
                phase = "WAIT_SAMPLE"
            elif phase == "WAIT_SAMPLE" and active_channel == self.channel_number:
                phase = "WAIT_RETURN_TO_CONTROL"
            elif phase == "WAIT_RETURN_TO_CONTROL" and active_channel == 6:
                return

            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                break

            if self._abort_event.wait(min(float(poll_interval_s), remaining_s)):
                raise InterruptedError(
                    "STEP_RAMP stop requested while waiting for a new sample visit."
                )

        raise RuntimeError(
            f"No new completed CH{self.channel_number} visit observed "
            f"within {timeout_s:g} seconds. "
            f"Phase={phase}; last SCAN?={last_scan_status!r}."
        )
    
    def _collect_resistance_samples(
        self,
        *,
        n_samples: int,
        sample_interval_s: float,
        max_attempts: int,
    ) -> dict:
        """
        Collect N valid resistance readings from the selected sample channel.

        Each resistance measurement is acquired through
        read_resistance_with_status(), which performs:

            RDGST? -> RDGR? -> RDGST?

        atomically inside the Lake Shore driver.

        Measurements containing any non-zero RDGST status are rejected.
        Invalid or non-finite resistance values are also rejected.

        The function continues until:
            - n_samples valid readings have been collected, or
            - max_attempts total readings have been attempted.

        The resistance range is not changed here. External range selection
        belongs exclusively to _external_autorange().

        Each reading attempt follows a newly observed, completed
        CH6 -> sample -> CH6 cycle. Equal resistance values from different
        cycles remain valid.

        Parameters
        ----------
        n_samples
            Number of valid resistance samples required.

        sample_interval_s
            Additional delay between resistance-reading attempts.
            A new completed scanner visit is required even when this is zero.

        max_attempts
            Maximum total number of resistance-reading attempts. This must
            be at least n_samples.

        Returns
        -------
        dict
            Resistance statistics and acquisition information.

        Raises
        ------
        InterruptedError
            If STEP_RAMP stop is requested.

        TypeError
            If integer parameters are not integers.

        ValueError
            If acquisition parameters are invalid.

        RuntimeError
            If the sample measurement state is inconsistent or too few valid
            resistance readings can be collected.
        """

        # ==================================================================
        # Validate parameters
        # ==================================================================

        if (
            isinstance(n_samples, bool)
            or not isinstance(n_samples, int)
        ):
            raise TypeError(
                "n_samples must be an integer."
            )

        if n_samples <= 0:
            raise ValueError(
                "n_samples must be greater than zero."
            )

        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
        ):
            raise TypeError(
                "max_attempts must be an integer."
            )

        if max_attempts <= 0:
            raise ValueError(
                "max_attempts must be greater than zero."
            )

        if max_attempts < n_samples:
            raise ValueError(
                "max_attempts must be greater than or equal "
                "to n_samples."
            )

        try:
            sample_interval_s = float(
                sample_interval_s
            )

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "sample_interval_s must be numeric."
            ) from exc

        if (
            not math.isfinite(sample_interval_s)
            or sample_interval_s < 0
        ):
            raise ValueError(
                "sample_interval_s must be finite "
                "and non-negative."
            )

        if self._resistance_range is None:
            raise RuntimeError(
                "No valid resistance range is available."
            )

        try:
            mxc_settling_time_s = float(self._mxc_settling_time_s)
            sample_settling_time_s = float(self._sample_settling_time_s)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(
                "STEP_RAMP preflight must provide valid channel settling "
                "times before resistance acquisition."
            ) from exc

        if any(
            not math.isfinite(value) or value <= 0
            for value in (mxc_settling_time_s, sample_settling_time_s)
        ):
            raise RuntimeError(
                "Channel settling times must be finite and greater than zero."
            )

        # Firmware dwell times during control/sample alternation.
        nominal_cycle_s = (
            mxc_settling_time_s + 5.0
            + sample_settling_time_s + 1.0
        )

        # Allow an in-progress visit plus a full new cycle and an I/O margin.
        sample_visit_timeout_s = 2.0 * nominal_cycle_s + 10.0
        
        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before "
                "resistance measurement."
            )

        self._set_state("MEASURE")

        # ==================================================================
        # Verify measurement state
        #
        # Expected:
        #     sample ON
        #     autoscan OFF
        #     active channel: CH6 or selected sample
        #     internal autorange OFF
        #     excitation ON
        #     resistance range == controller range
        # ==================================================================

        with self.heater_mutex:

            sample_status = self.ls.get_channel_status(
                self.channel_number
            )

            scan_status = self.ls.get_autoscan()

            sensor_settings = (
                self.ls.get_sensor_resistance_settings(
                    channel=self.channel_number,
                    return_dict=True,
                )
            )

        try:
            sample_status = int(sample_status)

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Could not determine CH{self.channel_number} "
                "enabled state."
            ) from exc

        if sample_status != 1:
            raise RuntimeError(
                f"CH{self.channel_number} must be enabled "
                "during resistance measurement."
            )

        if (
            not isinstance(scan_status, (list, tuple))
            or len(scan_status) < 2
        ):
            raise RuntimeError(
                "Could not determine Lake Shore scan state."
            )

        try:
            selected_channel = int(
                scan_status[0]
            )

            autoscan_enabled = int(
                scan_status[1]
            )

        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid SCAN? result: {scan_status!r}."
            ) from exc

        if autoscan_enabled != 0:
            raise RuntimeError(
                "Lake Shore autoscan must remain OFF "
                "during STEP_RAMP resistance measurement."
            )

        if selected_channel not in (6, self.channel_number):
            raise RuntimeError(
                "Unexpected active scanner channel during "
                "resistance measurement: "
                f"expected CH6 or CH{self.channel_number}, "
                f"received CH{selected_channel}."
            )

        if not isinstance(sensor_settings, dict):
            raise RuntimeError(
                f"Could not read CH{self.channel_number} "
                "resistance settings."
            )

        try:
            actual_range = int(
                sensor_settings["resistance_range"]
            )

            internal_autorange = int(
                sensor_settings["autorange"]
            )

            cs_off = int(
                sensor_settings["excitation"]
            )

            expected_range = int(
                self._resistance_range
            )

        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid RDGRNG? configuration for "
                f"CH{self.channel_number}."
            ) from exc

        if actual_range != expected_range:
            raise RuntimeError(
                "Sample resistance range changed unexpectedly: "
                f"expected {expected_range}, "
                f"instrument reports {actual_range}."
            )

        if internal_autorange != 0:
            raise RuntimeError(
                "Lake Shore internal autorange must remain OFF "
                "during STEP_RAMP resistance measurement."
            )

        # RDGRNG field "cs off":
        #     0 -> excitation ON
        #     1 -> excitation OFF
        if cs_off != 0:
            raise RuntimeError(
                f"CH{self.channel_number} excitation must be ON "
                "during resistance measurement."
            )

        # ==================================================================
        # Collect valid resistance samples
        # ==================================================================

        resistance_samples = []

        invalid_samples = 0

        last_invalid_status_code = None
        last_invalid_status_flags = []

        attempts = 0

        while (
            len(resistance_samples) < n_samples
            and attempts < max_attempts
        ):

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested during "
                    "resistance measurement."
                )

            # Wait outside heater_mutex for a new completed sample visit.
            self._wait_for_new_sample_visit(
                timeout_s=sample_visit_timeout_s,
                poll_interval_s=0.2,
            )

            # Atomic: RDGST? -> RDGR? -> RDGST?
            with self.heater_mutex:

                if self.abort_requested():
                    raise InterruptedError(
                        "STEP_RAMP stop requested before resistance readout."
                    )

                attempts += 1

                reading = self.ls.read_resistance_with_status(
                    self.channel_number
                )

            if not isinstance(reading, dict):
                raise RuntimeError(
                    "Lake Shore returned an invalid resistance "
                    "measurement result."
                )

            try:
                status_code = int(
                    reading["status_code"]
                )

            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Resistance measurement did not contain "
                    "a valid status code."
                ) from exc

            if not 0 <= status_code <= 255:
                raise RuntimeError(
                    f"Invalid RDGST status code: "
                    f"{status_code}."
                )

            # --------------------------------------------------------------
            # Any non-zero RDGST status makes this sample invalid.
            # Do not abort the entire acquisition immediately: transient
            # invalid readings may simply be discarded.
            # --------------------------------------------------------------

            if status_code != 0:

                invalid_samples += 1

                last_invalid_status_code = (
                    status_code
                )

                last_invalid_status_flags = list(
                    reading.get(
                        "status_flags",
                        [],
                    )
                )

            elif not reading.get("valid"):

                # The driver may reject a reading for reasons such as an
                # invalid/non-finite RDGR? value even when status parsing
                # itself succeeded.
                invalid_samples += 1

                last_invalid_status_code = (
                    status_code
                )

                last_invalid_status_flags = list(
                    reading.get(
                        "status_flags",
                        [],
                    )
                )

            else:

                resistance_ohm = reading.get(
                    "resistance_ohm"
                )

                try:
                    resistance_ohm = float(
                        resistance_ohm
                    )

                except (TypeError, ValueError):

                    invalid_samples += 1

                    last_invalid_status_code = (
                        status_code
                    )

                    last_invalid_status_flags = [
                        "NON_NUMERIC_RESISTANCE"
                    ]

                else:

                    if not math.isfinite(
                        resistance_ohm
                    ):

                        invalid_samples += 1

                        last_invalid_status_code = (
                            status_code
                        )

                        last_invalid_status_flags = [
                            "NON_FINITE_RESISTANCE"
                        ]

                    else:

                        resistance_samples.append(
                            resistance_ohm
                        )

            # --------------------------------------------------------------
            # Do not sleep after the final required valid reading.
            # --------------------------------------------------------------

            if (
                len(resistance_samples) >= n_samples
            ):
                break

            if attempts >= max_attempts:
                break

            # --------------------------------------------------------------
            # Interruptible delay between reading attempts.
            # heater_mutex is deliberately not held here.
            # --------------------------------------------------------------

            if sample_interval_s > 0:

                if self._abort_event.wait(
                    sample_interval_s
                ):
                    raise InterruptedError(
                        "STEP_RAMP stop requested between "
                        "resistance samples."
                    )

        # ==================================================================
        # Check that enough valid readings were obtained
        # ==================================================================

        if len(resistance_samples) < n_samples:

            if last_invalid_status_flags:

                last_status_description = (
                    " | ".join(
                        last_invalid_status_flags
                    )
                )

            elif last_invalid_status_code is not None:

                last_status_description = str(
                    last_invalid_status_code
                )

            else:

                last_status_description = "unknown"

            raise RuntimeError(
                "Could not collect the requested number of "
                "valid resistance samples. "
                f"Valid={len(resistance_samples)}/{n_samples}, "
                f"attempts={attempts}/{max_attempts}, "
                f"invalid={invalid_samples}, "
                f"last invalid status="
                f"{last_status_description}."
            )

        # ==================================================================
        # Final resistance statistics
        # ==================================================================

        mean_resistance_ohm = statistics.fmean(
            resistance_samples
        )

        if len(resistance_samples) > 1:

            std_resistance_ohm = statistics.pstdev(
                resistance_samples
            )

        else:

            std_resistance_ohm = 0.0

        # ==================================================================
        # Publish live status
        # ==================================================================

        with self._status_lock:

            self._last_resistance_ohm = (
                mean_resistance_ohm
            )

            self._last_resistance_std_ohm = (
                std_resistance_ohm
            )

        # ==================================================================
        # Return acquisition result
        # ==================================================================

        return {
            "mean_resistance_ohm":
                mean_resistance_ohm,

            "std_resistance_ohm":
                std_resistance_ohm,

            "n_samples":
                len(resistance_samples),

            "attempts":
                attempts,

            "invalid_samples":
                invalid_samples,

            "resistance_range":
                expected_range,

            "samples_ohm":
                list(resistance_samples),
        }

    def _restore_mxc_and_disable_sample(
        self,
        *,
        heater_checkpoint_prefix: str | None = None,
    ) -> dict:
        """
        Restore the MXC scanner state and leave the sample measurement
        channel fully inactive.

        Every action is attempted independently:
            - select SCAN 6,0;
            - disable sample excitation and internal autorange;
            - disable the sample channel through INSET;
            - verify the final INSET state.

        The current resistance range and excitation mode/range are
        preserved. Communication failures are collected without preventing
        the remaining restoration actions.

        Restore SCAN 6,0, disable the sample channel through INSET,
        and preserve its current RDGRNG configuration.

        No RDGRNG write is performed while CH6 is controlling.
        """
        errors = []

        if heater_checkpoint_prefix is not None:
            self._log_mxc_heater_checkpoint(
                context=f"{heater_checkpoint_prefix}: entry"
            )

        # select_scan_channel() may poll, so do not hold heater_mutex.
        try:
            scan_ok = self.ls.select_scan_channel(
                6,
                autoscan=False,
            )

            if scan_ok is not True:
                errors.append(
                    "Could not restore SCAN 6,0: "
                    f"command returned {scan_ok!r}."
                )

        except Exception as exc:
            errors.append(
                f"Could not restore SCAN 6,0: {exc}"
            )

        if heater_checkpoint_prefix is not None:
            self._log_mxc_heater_checkpoint(
                context=(
                    f"{heater_checkpoint_prefix}: "
                    "after SCAN 6,0"
                )
            )

        # Read and cache the current resistance range.
        #
        # Do not write RDGRNG here. With SCAN 6,0 and the sample channel
        # disabled through INSET, the sample is not connected to the active
        # measurement path. Writing RDGRNG with excitation_off caused the
        # Lake Shore to disable the MXC heater range.
        try:
            with self.heater_mutex:
                sensor_settings = (
                    self.ls.get_sensor_resistance_settings(
                        channel=self.channel_number,
                        return_dict=True,
                    )
                )

            if not isinstance(sensor_settings, dict):
                raise RuntimeError("invalid RDGRNG? result")

            raw_resistance_range = sensor_settings.get(
                "resistance_range"
            )

            if isinstance(raw_resistance_range, bool):
                raise RuntimeError(
                    "invalid resistance-range value"
                )

            try:
                resistance_range = int(
                    raw_resistance_range
                )

            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError(
                    "invalid resistance-range value"
                ) from exc

            if not 1 <= resistance_range <= 22:
                raise RuntimeError(
                    f"resistance range {resistance_range} "
                    "is outside 1 through 22"
                )

            with self._status_lock:
                self._resistance_range = resistance_range

        except Exception as exc:
            errors.append(
                f"Could not read CH{self.channel_number} "
                f"resistance range: {exc}"
            )

        if heater_checkpoint_prefix is not None:
            self._log_mxc_heater_checkpoint(
            context=(
                f"{heater_checkpoint_prefix}: "
                f"after CH{self.channel_number} RDGRNG read (no write)"
            )
        )

        # Attempt INSET OFF independently of the preceding operations.
        try:
            with self.heater_mutex:
                channel_off_ok = self.ls.set_channel_off(
                    self.channel_number
                )

            if channel_off_ok is not True:
                errors.append(
                    f"Could not disable CH{self.channel_number}: "
                    f"command returned {channel_off_ok!r}."
                )

        except Exception as exc:
            errors.append(
                f"Could not disable CH{self.channel_number}: {exc}"
            )

        if heater_checkpoint_prefix is not None:
            self._log_mxc_heater_checkpoint(
                context=(
                    f"{heater_checkpoint_prefix}: "
                    f"after CH{self.channel_number} INSET OFF"
                )
            )

        # Verify INSET even when set_channel_off() failed or raised.
        try:
            with self.heater_mutex:
                sample_status = self.ls.get_channel_status(
                    self.channel_number
                )

            if isinstance(sample_status, bool):
                raise RuntimeError(
                    "invalid channel-status reply"
                )

            try:
                sample_status = int(
                    sample_status
                )

            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError(
                    "invalid channel-status reply"
                ) from exc

            if sample_status != 0:
                errors.append(
                    f"CH{self.channel_number} remained enabled."
                )

        except Exception as exc:
            errors.append(
                f"Could not verify CH{self.channel_number} "
                f"OFF state: {exc}"
            )

        return {
            "ok": not errors,
            "errors": errors,
        }

    def _reapply_mxc_control_settings(
        self,
        *,
        setpoint_mk: float,
        context: str,
    ) -> dict:
        """
        Reapply the MXC control settings in the same order used by the
        frontend "Write Control Settings" operation.

        The numerical PID values and heater range are read from the
        instrument immediately before being rewritten. CSET and CMODE are
        verified but deliberately not modified.

        This operation is only allowed with:
            - CH6 selected;
            - autoscan OFF;
            - the sample channel OFF.
        """

        try:
            setpoint_mk = float(setpoint_mk)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "setpoint_mk must be numeric."
            ) from exc

        if not math.isfinite(setpoint_mk):
            raise ValueError(
                "setpoint_mk must be finite."
            )

        if not isinstance(context, str) or not context.strip():
            raise ValueError(
                "context must be a non-empty string."
            )

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before MXC control reapplication."
            )

        def wait_between_commands(stage: str) -> None:
            # Reproduce the 150 ms separation used by index.html.
            if self._abort_event.wait(0.15):
                raise InterruptedError(
                    "STEP_RAMP stop requested while reapplying "
                    f"MXC control settings after {stage}."
                )

        with self.heater_mutex:

            # ==============================================================
            # Read and validate the state that will be reapplied
            # ==============================================================

            control_mode_before = self.ls.get_control_mode()

            control_settings_before = self.ls.get_control_settings(
                return_dict=True
            )

            pid_before = self.ls.get_control_parameters()
            heater_range_before = self.ls.get_control_range()
            heater_status_before = self.ls.get_heater_status()
            scan_before = self.ls.get_autoscan()

            sample_status_before = self.ls.get_channel_status(
                self.channel_number
            )

            heater_output_before = (
                self.ls.get_heater_output_percent()
            )

            if control_mode_before != 1:
                raise RuntimeError(
                    f"{context}: CMODE must be 1; "
                    f"received {control_mode_before!r}."
                )

            if not isinstance(control_settings_before, dict):
                raise RuntimeError(
                    f"{context}: could not read CSET."
                )

            if (
                int(control_settings_before["controlled_channel"]) != 6
                or control_settings_before["units"] != "Kelvin"
                or control_settings_before["filtered_readings"] is not False
            ):
                raise RuntimeError(
                    f"{context}: incompatible CSET state: "
                    f"{control_settings_before!r}."
                )

            if scan_before != ["6", "0"]:
                raise RuntimeError(
                    f"{context}: expected SCAN 6,0 before control "
                    f"reapplication; received {scan_before!r}."
                )

            if sample_status_before != 0:
                raise RuntimeError(
                    f"{context}: CH{self.channel_number} must be OFF "
                    "before control reapplication."
                )

            if heater_status_before != 0:
                raise RuntimeError(
                    f"{context}: HTRST? returned "
                    f"{heater_status_before!r}."
                )

            try:
                heater_range_before = int(heater_range_before)

                pid_before = {
                    name: float(pid_before[name])
                    for name in ("P", "I", "D")
                }

                heater_output_before = float(
                    heater_output_before
                )

            except (TypeError, ValueError, KeyError) as exc:
                raise RuntimeError(
                    f"{context}: invalid MXC control readback."
                ) from exc

            if not 1 <= heater_range_before <= 8:
                raise RuntimeError(
                    f"{context}: invalid heater range "
                    f"{heater_range_before}."
                )

            if not all(
                math.isfinite(value)
                for value in pid_before.values()
            ):
                raise RuntimeError(
                    f"{context}: non-finite PID values."
                )

            # ==============================================================
            # Reproduce "Write Control Settings"
            # ==============================================================

            if not self.ls.set_channel_setpoint(
                setpoint_mk,
                channel=6,
                verbose=False,
                units="mK",
            ):
                raise RuntimeError(
                    f"{context}: could not reapply SETP."
                )

            wait_between_commands("SETP")

            if not self.ls.set_control_parameters(
                P=pid_before["P"],
                channel=6,
                verbose=False,
            ):
                raise RuntimeError(
                    f"{context}: could not reapply PID P."
                )

            wait_between_commands("PID P")

            if not self.ls.set_control_parameters(
                I=pid_before["I"],
                channel=6,
                verbose=False,
            ):
                raise RuntimeError(
                    f"{context}: could not reapply PID I."
                )

            wait_between_commands("PID I")

            if not self.ls.set_control_parameters(
                D=pid_before["D"],
                channel=6,
                verbose=False,
            ):
                raise RuntimeError(
                    f"{context}: could not reapply PID D."
                )

            wait_between_commands("PID D")

            # This write is intentional even though the numerical range
            # has not changed.
            if not self.ls.set_control_range(
                str(heater_range_before),
                verbose=False,
            ):
                raise RuntimeError(
                    f"{context}: could not reapply HTRRNG."
                )

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested after MXC control reapplication."
                )

            # ==============================================================
            # Complete readback
            # ==============================================================

            setpoint_after_k = self.ls.get_temperature_setpoint()
            pid_after = self.ls.get_control_parameters()
            heater_range_after = self.ls.get_control_range()
            control_mode_after = self.ls.get_control_mode()

            control_settings_after = self.ls.get_control_settings(
                return_dict=True
            )

            heater_status_after = self.ls.get_heater_status()
            scan_after = self.ls.get_autoscan()

            sample_status_after = self.ls.get_channel_status(
                self.channel_number
            )

            heater_output_after = (
                self.ls.get_heater_output_percent()
            )

        try:
            setpoint_after_k = float(setpoint_after_k)
            heater_range_after = int(heater_range_after)
            heater_output_after = float(heater_output_after)

            pid_after = {
                name: float(pid_after[name])
                for name in ("P", "I", "D")
            }

        except (TypeError, ValueError, KeyError) as exc:
            raise RuntimeError(
                f"{context}: invalid control readback after reapplication."
            ) from exc

        if control_mode_after != 1:
            raise RuntimeError(
                f"{context}: CMODE changed after control reapplication."
            )

        if control_settings_after != control_settings_before:
            raise RuntimeError(
                f"{context}: CSET changed unexpectedly. "
                f"Before={control_settings_before!r}; "
                f"after={control_settings_after!r}."
            )

        if heater_range_after != heater_range_before:
            raise RuntimeError(
                f"{context}: HTRRNG verification failed."
            )

        if heater_status_after != 0:
            raise RuntimeError(
                f"{context}: HTRST? returned "
                f"{heater_status_after!r} after reapplication."
            )

        if scan_after != ["6", "0"]:
            raise RuntimeError(
                f"{context}: scanner changed unexpectedly: "
                f"{scan_after!r}."
            )

        if sample_status_after != 0:
            raise RuntimeError(
                f"{context}: CH{self.channel_number} became enabled "
                "during control reapplication."
            )

        if not math.isclose(
            setpoint_after_k,
            setpoint_mk / 1000.0,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise RuntimeError(
                f"{context}: SETP verification failed."
            )

        for name in ("P", "I", "D"):
            if not math.isclose(
                pid_after[name],
                pid_before[name],
                rel_tol=1e-6,
                abs_tol=1e-6,
            ):
                raise RuntimeError(
                    f"{context}: PID {name} verification failed."
                )

        print(
            "🔄 STEP_RAMP MXC control settings reapplied: "
            f"context={context}; "
            f"SETP={setpoint_mk:g} mK; "
            f"PID={pid_before['P']:g},"
            f"{pid_before['I']:g},"
            f"{pid_before['D']:g}; "
            f"HTRRNG={heater_range_before}; "
            f"HTR before={heater_output_before:.6g}%; "
            f"after={heater_output_after:.6g}%."
        )

        return {
            "setpoint_mk": setpoint_mk,
            "pid": dict(pid_after),
            "heater_range": heater_range_after,
            "heater_output_before": heater_output_before,
            "heater_output_after": heater_output_after,
        }

    def _measure_and_verify_point(
        self,
        *,
        setpoint_mk: float,
        stability_result: dict,
        tolerance_mk: float,
        autorange_max_attempts: int,
        resistance_n_samples: int,
        resistance_sample_interval_s: float,
        resistance_max_attempts: int,
    ) -> dict:
        """
        Measure one complete STEP_RAMP resistance point and verify that the
        MXC temperature remained valid during the sample measurement.

        The function assumes that _wait_for_stability() has already accepted
        the current setpoint.

        Select SCAN 6,0, wait for settling and verify MXC temperature.
        If valid and within tolerance, reselect the sample and acquire.
        Otherwise, restore the instrument and reject the point.

        Sequence
        --------
            1. Measure MXC temperature immediately before sample measurement.
            2. Enable the sample channel.
            3. Select SCAN sample,0.
            4. Perform external resistance autoranging.
            5. Collect N valid resistance readings.
            6. Restore SCAN 6,0.
            7. Disable the sample channel.
            8. Wait for MXC scanner/filter settling.
            9. Measure MXC temperature again.
        10. Verify that temperature stayed within the allowed conditions.

        The point is NOT appended to RELATION_BUFFER here. That belongs to
        the STORE_POINT state in _run().

        Returns
        -------
        dict
            If accepted is True, contains the final measured R(T) candidate.
            If accepted is False, the point must return to WAIT_STABLE and
            be measured again.

        Raises
        ------
        InterruptedError
            If STEP_RAMP stop is requested.

        ValueError
            If parameters are invalid.

        RuntimeError
            If hardware preparation, resistance acquisition or restoration
            fails.
        """

        # ==================================================================
        # Validate parameters and sequencing
        # ==================================================================

        try:
            setpoint_mk = float(setpoint_mk)
            tolerance_mk = float(tolerance_mk)

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "setpoint_mk and tolerance_mk must be numeric."
            ) from exc

        if (
            not math.isfinite(setpoint_mk)
            or not math.isfinite(tolerance_mk)
        ):
            raise ValueError(
                "setpoint_mk and tolerance_mk must be finite."
            )

        if tolerance_mk <= 0:
            raise ValueError(
                "tolerance_mk must be greater than zero."
            )

        if not isinstance(stability_result, dict):
            raise TypeError(
                "stability_result must be a dictionary."
            )

        if not stability_result.get("stable"):
            raise RuntimeError(
                "A successful stability result is required "
                "before measuring a STEP_RAMP point."
            )

        try:
            stable_setpoint_mk = float(
                stability_result["setpoint_mk"]
            )

        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "stability_result does not contain a valid setpoint."
            ) from exc

        if not math.isclose(
            stable_setpoint_mk,
            setpoint_mk,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise RuntimeError(
                "stability_result belongs to a different setpoint."
            )

        if self._mxc_settling_time_s is None:
            raise RuntimeError(
                "STEP_RAMP preflight must run before "
                "measuring a point."
            )

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before "
                "point measurement."
            )

        # ==================================================================
        # INITIAL_MXC_CHECK
        #
        # Sample OFF; SCAN 6,0.
        # _wait_for_stability() has already handled MXC settling.
        #
        # Check temperature before enabling the sample and autoranging.
        # The acquisition baseline is refreshed after external autoranging.
        # ==================================================================

        with self.heater_mutex:

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested before initial MXC reading."
                )

            mxc_before_reading = self.ls.read_temperature_with_status(6)

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested after initial MXC reading."
            )

        if not isinstance(mxc_before_reading, dict):
            raise RuntimeError("Invalid structured initial MXC temperature result.")

        if not mxc_before_reading["valid"]:
            return {
                "accepted": False,
                "reason": "invalid_temperature_before_measurement",
                "details": mxc_before_reading.get("invalid_reason"),
                "status_flags": mxc_before_reading.get("status_flags", []),
            }

        temperature_before_mk = float(mxc_before_reading["temperature_k"]) * 1000.0

        if not math.isfinite(temperature_before_mk):
            return {
                "accepted": False,
                "reason": "invalid_temperature_before_measurement",
                "details": "non_finite_temperature_mk",
            }

        with self._status_lock:
            self._current_mxc_temperature_mk = (
                temperature_before_mk
            )

        # Even though stability was just accepted, the instantaneous reading
        # immediately before switching channels must still be inside tolerance.
        if (
            abs(
                temperature_before_mk
                - setpoint_mk
            )
            > tolerance_mk
        ):
            return {
                "accepted": False,
                "reason": (
                    "temperature_left_tolerance_before_measurement"
                ),
                "temperature_before_mk":
                    temperature_before_mk,
                "setpoint_mk":
                    setpoint_mk,
            }

        # ==================================================================
        # ENABLE_SAMPLE
        # ==================================================================

        # Guard sample preparation with the same restoration path.
        measurement_error = None
        restore_error = None
        autorange_result = None
        resistance_result = None
        point_rejection = None

        try:

            self._set_state("ENABLE_SAMPLE")

            with self.heater_mutex:

                if self.abort_requested():
                    raise InterruptedError(
                        "STEP_RAMP stop requested before enabling the sample."
                    )

                if not self.ls.set_channel_on(self.channel_number):
                    raise RuntimeError(
                        f"Could not enable CH{self.channel_number}."
                    )

                sample_status = self.ls.get_channel_status(self.channel_number)
                if sample_status != 1:
                    raise RuntimeError(
                        f"Could not verify CH{self.channel_number} ON state: "
                        f"received {sample_status!r}."
                    )

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested before selecting the sample."
                )

            # Scanner verification may wait; do not hold heater_mutex here.
            scan_ok = self.ls.select_scan_channel(
                self.channel_number,
                autoscan=False,
            )
            if not scan_ok:
                raise RuntimeError(
                    f"Could not select SCAN {self.channel_number},0."
                )

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested after selecting the sample."
                )

            # Continue with the existing autorange and temperature checks.
            autorange_result = self._external_autorange(
                max_attempts=autorange_max_attempts,
            )

            # CH10 remains the requested measurement channel.
            # During closed-loop control, the Model 370 firmware alternates
            # automatically between CH6 and CH10. Do not send intermediate
            # SCAN commands, because a manual channel selection overrides
            # the firmware-managed control/measurement sequence.
            resistance_result = self._collect_resistance_samples(
                n_samples=resistance_n_samples,
                sample_interval_s=resistance_sample_interval_s,
                max_attempts=resistance_max_attempts,
            )

        except Exception as exc:
            measurement_error = exc

        # ==================================================================
        # RESTORE_MXC
        #
        # Always attempt this sequence, including after a measurement error.
        # ==================================================================

        self._set_state("RESTORE_MXC")

        restore_errors = []

        try:
            restore_result = (
                self._restore_mxc_and_disable_sample()
            )

            if not isinstance(restore_result, dict):
                raise RuntimeError(
                    "invalid restoration result"
                )

            result_errors = restore_result.get("errors")

            if not isinstance(result_errors, list):
                raise RuntimeError(
                    "invalid restoration error list"
                )

            restore_errors.extend(
                str(error)
                for error in result_errors
            )

        except Exception as exc:
            restore_errors.append(
                f"Unexpected restoration failure: {exc}"
            )
            
        # Check CH6 independently, even if sample restoration failed.
        try:
            self._assert_mxc_heater_ready(
                context=(
                    "immediate MXC restoration after "
                    f"CH{self.channel_number} measurement"
                )
            )

        except Exception as exc:
            restore_errors.append(
                f"MXC control verification failed: {exc}"
            )

        if restore_errors:
            restore_error = RuntimeError(
                "MXC/sample restoration failed: "
                + " | ".join(restore_errors)
            )
        # ==================================================================
        # Preserve the original measurement failure, but never hide a
        # simultaneous restore failure.
        # ==================================================================

        if measurement_error is not None:

            if restore_error is not None:
                raise RuntimeError(
                    "STEP_RAMP point measurement failed and "
                    "MXC restoration also failed. "
                    f"Measurement error: {measurement_error}. "
                    f"Restore error: {restore_error}."
                ) from measurement_error

            raise measurement_error

        if restore_error is not None:
            raise restore_error

        # Return only after CH6/sample OFF restoration has succeeded.
        if point_rejection is not None:
            return point_rejection

        # ==================================================================
        # Wait for MXC scanner/filter settling after restoring SCAN 6,0.
        #
        # No heater_mutex is held during this wait.
        # ==================================================================

        self._set_state("SETTLE")

        if self._abort_event.wait(
            self._mxc_settling_time_s
        ):
            raise InterruptedError(
                "STEP_RAMP stop requested during "
                "post-measurement MXC settling."
            )

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested before "
                "post-measurement verification."
            )

        self._assert_mxc_heater_ready(
            context=(
                "post-measurement MXC settling at "
                f"{setpoint_mk:g} mK"
            )
        )
        # ==================================================================
        # T_after
        # ==================================================================

        self._set_state("VERIFY_POINT")

        with self.heater_mutex:

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested before final MXC reading."
                )

            mxc_after_reading = self.ls.read_temperature_with_status(6)

        if self.abort_requested():
            raise InterruptedError(
                "STEP_RAMP stop requested after final MXC reading."
            )

        if not isinstance(mxc_after_reading, dict):
            raise RuntimeError("Invalid structured final MXC temperature result.")

        if not mxc_after_reading["valid"]:
            return {
                "accepted": False,
                "reason": "invalid_temperature_after_measurement",
                "details": mxc_after_reading.get("invalid_reason"),
                "status_flags": mxc_after_reading.get("status_flags", []),
            }

        temperature_after_mk = float(mxc_after_reading["temperature_k"]) * 1000.0

        if not math.isfinite(temperature_after_mk):
            return {
                "accepted": False,
                "reason": "invalid_temperature_after_measurement",
                "details": "non_finite_temperature_mk",
            }

        with self._status_lock:
            self._current_mxc_temperature_mk = (
                temperature_after_mk
            )

        # At this point:
        #   - SCAN 6,0 has already been restored;
        #   - CH10 is OFF;
        #   - the complete CH6 settling time has elapsed;
        #   - a fresh and valid CH6 temperature has been obtained.
        #
        # Only now is it safe to reproduce the frontend
        # "Write Control Settings" sequence.
        self._reapply_mxc_control_settings(
            setpoint_mk=setpoint_mk,
            context=(
                f"after settled CH6 recovery from "
                f"CH{self.channel_number} measurement at "
                f"{setpoint_mk:g} mK"
            ),
        )

        # ==================================================================
        # Verify temperature validity
        # ==================================================================

        after_error_mk = (
            temperature_after_mk
            - setpoint_mk
        )

        temperature_drift_mk = (
            temperature_after_mk
            - temperature_before_mk
        )

        # T_after must still be inside the same tolerance band used to
        # declare the point stable.
        if abs(after_error_mk) > tolerance_mk:

            return {
                "accepted": False,

                "reason":
                    "temperature_left_tolerance_during_measurement",

                "setpoint_mk":
                    setpoint_mk,

                "temperature_before_mk":
                    temperature_before_mk,

                "temperature_after_mk":
                    temperature_after_mk,

                "temperature_drift_mk":
                    temperature_drift_mk,
            }

        # Also reject a point whose before/after drift is larger than the
        # requested stability tolerance, even if both values individually
        # happen to lie inside the setpoint tolerance band.
        if (
            abs(temperature_drift_mk)
            > tolerance_mk
        ):

            return {
                "accepted": False,

                "reason":
                    "temperature_drift_too_large",

                "setpoint_mk":
                    setpoint_mk,

                "temperature_before_mk":
                    temperature_before_mk,

                "temperature_after_mk":
                    temperature_after_mk,

                "temperature_drift_mk":
                    temperature_drift_mk,
            }

        # ==================================================================
        # Build accepted R(T) candidate
        #
        # The X coordinate is measured MXC temperature, never the setpoint.
        # Using the midpoint of T_before and T_after gives a representative
        # temperature for the interval during which resistance was measured.
        # ==================================================================

        measured_temperature_mk = (
            (
                temperature_before_mk
                + temperature_after_mk
            )
            / 2.0
        )

        measured_temperature_k = (
            measured_temperature_mk
            / 1000.0
        )

        return {
            "accepted":
                True,

            "setpoint_mk":
                setpoint_mk,

            "measured_temperature_mk":
                measured_temperature_mk,

            "measured_temperature_k":
                measured_temperature_k,

            "temperature_before_mk":
                temperature_before_mk,

            "temperature_after_mk":
                temperature_after_mk,

            "temperature_drift_mk":
                temperature_drift_mk,

            "mean_resistance_ohm":
                resistance_result[
                    "mean_resistance_ohm"
                ],

            "std_resistance_ohm":
                resistance_result[
                    "std_resistance_ohm"
                ],

            "resistance_range":
                resistance_result[
                    "resistance_range"
                ],

            "resistance_samples":
                resistance_result[
                    "samples_ohm"
                ],

            "resistance_n_samples":
                resistance_result[
                    "n_samples"
                ],

            "resistance_attempts":
                resistance_result[
                    "attempts"
                ],

            "resistance_invalid_samples":
                resistance_result[
                    "invalid_samples"
                ],

            "autorange_attempts":
                autorange_result[
                    "attempts"
                ],

            "autorange_range_changes":
                autorange_result[
                    "range_changes"
                ],

            "stability":
                dict(stability_result),
        }

    def _cleanup(self) -> dict:
        """
        Put the Lake Shore into the safe STEP_RAMP idle configuration.

        Cleanup is best-effort: every cleanup action is attempted even if
        another action fails.

        Final intended state:
            - SCAN 6,0
            - sample channel disabled
            - sample internal autorange OFF
            - native Lake Shore setpoint ramp OFF

        The MXC PID parameters, heater range, MXC excitation settings and
        temperature setpoint are deliberately left unchanged.

        Returns
        -------
        dict
            {
                "ok": bool,
                "errors": list[str],
            }
        """

        errors = []

        # ==================================================================
        # 1. Restore SCAN 6,0 and fully disable the sample.
        # ==================================================================

        try:
            restore_result = (
                self._restore_mxc_and_disable_sample()
            )

            if not isinstance(restore_result, dict):
                raise RuntimeError(
                    "invalid restoration result"
                )

            restore_errors = restore_result.get("errors")

            if not isinstance(restore_errors, list):
                raise RuntimeError(
                    "invalid restoration error list"
                )

            errors.extend(
                str(error)
                for error in restore_errors
            )

        except Exception as exc:
            errors.append(
                "Unexpected sample restoration failure: "
                f"{exc}"
            )

        # ==================================================================
        # 2. Ensure the native Lake Shore ramp is OFF.
        #
        # stop_ramp() holds the present setpoint; it does not modify PID,
        # heater range or the requested STEP_RAMP final setpoint.
        # ==================================================================

        try:

            with self.heater_mutex:

                ramp_result = self.ls.stop_ramp()

            if not isinstance(
                ramp_result,
                dict,
            ):

                errors.append(
                    "Lake Shore returned an invalid "
                    "native-ramp cleanup result."
                )

            elif not ramp_result.get("ok"):

                ramp_error = ramp_result.get(
                    "error",
                    "unknown ramp-stop error",
                )

                errors.append(
                    "Could not disable native Lake Shore ramp: "
                    f"{ramp_error}"
                )

        except Exception as exc:

            errors.append(
                "Could not disable native Lake Shore ramp: "
                f"{exc}"
            )

        # ==================================================================
        # Result
        # ==================================================================

        if errors:

            print(
                "⚠ STEP_RAMP cleanup completed with errors:"
            )

            for error in errors:
                print(
                    f"  - {error}"
                )

        else:

            print(
                "✅ STEP_RAMP cleanup completed: "
                "SCAN 6,0; sample channel OFF and not selected; "
                "native ramp OFF."
            )

        return {
            "ok": not errors,
            "errors": errors,
        }

    # ======================================================================
    # Public lifecycle API
    # ======================================================================

    def is_running(self) -> bool:
        """
        Return True while the worker thread is alive.
        """

        with self._status_lock:
            thread = self._thread

        return (
            thread is not None
            and thread.is_alive()
        )

    def abort_requested(self) -> bool:
        """
        Return whether asynchronous stop has been requested.
        """

        return self._abort_event.is_set()

    def request_stop(self) -> bool:
        """
        Request asynchronous termination of STEP_RAMP.

        This method does not communicate with the Lake Shore and does not
        wait for the worker. The worker must notice the Event, stop its
        current wait/measurement as soon as practical, perform cleanup,
        and terminate.

        Returns
        -------
        bool
            True if a stop request was registered.
            False if the controller was already in a terminal state.
        """

        with self._status_lock:

            if self._state in self.TERMINAL_STATES:
                return False

            self._abort_event.set()

        return True

    def start(self) -> bool:
        """
        Start the STEP_RAMP worker thread.

        Returns
        -------
        bool
            True if the worker was started.
            False if this controller had already been started or its state
            was no longer CREATED.
        """

        with self._status_lock:

            if self._thread is not None:
                return False

            if self._state != "CREATED":
                return False

            self._abort_event.clear()

            thread = threading.Thread(
                target=self._worker_entry,
                daemon=True,
                name=(
                    f"RelationStepRamp-"
                    f"CH{self.channel_number}"
                ),
            )

            self._thread = thread

        try:
            thread.start()

        except Exception:
            with self._status_lock:
                self._thread = None
            raise

        return True

    def join(
        self,
        timeout: float | None = None,
    ) -> bool:
        """
        Wait for the worker thread to finish.

        Parameters
        ----------
        timeout
            Maximum wait time in seconds. None waits indefinitely.

        Returns
        -------
        bool
            True if no worker exists or the worker has finished.
            False if it is still alive after the timeout.
        """

        with self._status_lock:
            thread = self._thread

        if thread is None:
            return True

        thread.join(timeout=timeout)

        return not thread.is_alive()

    def get_status(self) -> dict:
        """
        Return a thread-safe snapshot of the STEP_RAMP live status.

        High-level temperature values are expressed in mK.
        """

        with self._status_lock:

            if self._current_point_index is None:
                current_point = 0

            else:
                # External status is one-based.
                current_point = (
                    self._current_point_index + 1
                )

            thread = self._thread

            return {
                "relation_id":
                    self.relation_id,

                "mode":
                    "STEP_RAMP",

                "state":
                    self._state,

                "channel":
                    self.channel_number,

                "initial_mk":
                    self.initial_mk,

                "target_mk":
                    self.target_mk,

                "step_mk":
                    self.step_mk,

                "current_point":
                    current_point,

                "total_points":
                    self.total_points,

                "current_setpoint_mk":
                    self._current_setpoint_mk,

                "current_mxc_temperature_mk":
                    self._current_mxc_temperature_mk,

                "stable_time_s":
                    self._stable_time_s,

                "resistance_range":
                    self._resistance_range,

                "last_resistance_ohm":
                    self._last_resistance_ohm,

                "last_resistance_std_ohm":
                    self._last_resistance_std_ohm,

                "abort_requested":
                    self._abort_event.is_set(),

                "running": (
                    thread is not None
                    and thread.is_alive()
                ),

                "error":
                    self._error,
            }

    # ======================================================================
    # Relation callbacks
    # ======================================================================

    def _append_point(
        self,
        *,
        tmxc_k: float,
        resistance_ohm: float,
    ) -> bool:
        """
        Append one accepted STEP_RAMP point to the active RELATION.

        The actual RELATION locking and identity verification remain the
        responsibility of tcp_server.py.
        """

        return self._append_relation_point(
            tmxc_k=tmxc_k,
            resistance_ohm=resistance_ohm,
            expected_relation_id=self.relation_id,
            allowed_modes=("STEP_RAMP",),
        )

    def _finalize(
        self,
    ) -> tuple[str | None, int]:
        """
        Finalize this controller's RELATION through the server callback.
        """

        return self._finalize_relation(
            expected_relation_id=self.relation_id
        )

    # ======================================================================
    # Worker entry point
    # ======================================================================

    def _worker_entry(self) -> None:
        """
        Top-level wrapper around the STEP_RAMP execution method.

        Detailed execution is delegated to _run(), which is implemented
        after the remaining STEP_RAMP primitives are available.
        """

        try:
            self._set_state("PREPARE")

            self._run()

            # _run() may explicitly set a terminal state. If it returns
            # normally without doing so, infer the terminal state here.
            with self._status_lock:
                current_state = self._state

            if current_state not in self.TERMINAL_STATES:
                if self._abort_event.is_set():
                    self._set_state("ABORTED")
                else:
                    self._set_state("COMPLETE")

        except Exception as exc:
            self._set_error(exc)
            self._set_state("ERROR")

            print(
                "❌ STEP_RAMP worker failed."
                f"\nReason: {exc}"
            )

    def _run(self) -> None:
        """
        Execute the complete backend-driven STEP_RAMP state machine.

        Sequence for every setpoint:

            PREPARE
            SET_SETPOINT
            WAIT_STABLE
            ENABLE_SAMPLE
            AUTORANGE
            MEASURE
            RESTORE_MXC
            VERIFY_POINT
            STORE_POINT
            NEXT_POINT

        Only successfully verified points are appended to the RELATION.

        Cleanup and RELATION finalization are always attempted on:
            - normal completion,
            - user abort,
            - execution error.

        PREPARE
        ↓
        preflight
        ↓
        sample OFF / excitation OFF / SCAN 6
        ↓
        SET_SETPOINT 700
        ↓
        WAIT_STABLE
        ↓
        ENABLE_SAMPLE
        ↓
        AUTORANGE
        ↓
        MEASURE R1...RN
        ↓
        RESTORE_MXC
        ↓
        VERIFY_POINT
        ├── inválido → WAIT_STABLE otra vez en 700 mK
        │
        └── válido
                ↓
            STORE_POINT
                ↓
            NEXT_POINT
                ↓
        SET_SETPOINT 695
        ...
        SET_SETPOINT 400
        ↓
        STORE_POINT
        ↓
        cleanup
        ↓
        finalize RELATION
        ↓
        COMPLETE

        """

        outcome = "COMPLETE"
        execution_error = None

        try:

            # ==============================================================
            # PREPARE / PREFLIGHT
            # ==============================================================

            self._set_state("PREPARE")

            self._preflight()

            if self.abort_requested():
                raise InterruptedError(
                    "STEP_RAMP stop requested after preflight."
                )

            # ==============================================================
            # Iterate through every discrete setpoint
            # ==============================================================

            for point_index, setpoint_mk in enumerate(
                self.setpoints_mk
            ):

                if self.abort_requested():
                    raise InterruptedError(
                        "STEP_RAMP stop requested before "
                        "next setpoint."
                    )

                # ----------------------------------------------------------
                # Publish current point
                # ----------------------------------------------------------

                with self._status_lock:

                    self._current_point_index = (
                        point_index
                    )

                    self._current_setpoint_mk = (
                        setpoint_mk
                    )

                    self._stable_time_s = 0.0

                # ----------------------------------------------------------
                # Ensure that the sample cannot perturb MXC while changing
                # the temperature setpoint.
                #
                # Desired state:
                #     internal autorange OFF
                #     SCAN 6,0
                # ----------------------------------------------------------

                prepare_result = (
                    self._restore_mxc_and_disable_sample(
                        heater_checkpoint_prefix=(
                            f"point {point_index + 1} PREPARE"
                        )
                    )
                )

                if not prepare_result["ok"]:
                    raise RuntimeError(
                        "Could not prepare the sample channel before "
                        "the STEP_RAMP setpoint change: "
                        + " | ".join(prepare_result["errors"])
                    )

                # ==========================================================
                # SET_SETPOINT
                #
                # set_channel_setpoint() explicitly disables native RAMP
                # before applying SETP, therefore STEP_RAMP never invokes
                # Lake Shore native ramping.
                # ==========================================================

                self._set_state("SET_SETPOINT")

                with self.heater_mutex:
                    setpoint_ok = self.ls.set_channel_setpoint(
                        setpoint_mk,
                        channel=6,
                        verbose=False,
                        units="mK",
                    )

                if not setpoint_ok:
                    raise RuntimeError(
                        "Could not set MXC STEP_RAMP "
                        f"setpoint to {setpoint_mk:g} mK."
                    )
                
                self._log_mxc_heater_checkpoint(
                    context=(
                        f"point {point_index + 1}: "
                        "after SET_SETPOINT"
                    )
                )

                print(
                    "▶ STEP_RAMP "
                    f"point {point_index + 1}/"
                    f"{self.total_points}: "
                    f"setpoint={setpoint_mk:g} mK"
                )

                # ==========================================================
                # The same setpoint may need several complete measurement
                # attempts if post-measurement temperature verification
                # rejects a point.
                # ==========================================================

                point_measurement_attempt = 0

                while True:

                    if self.abort_requested():
                        raise InterruptedError(
                            "STEP_RAMP stop requested while "
                            "processing current point."
                        )

                    point_measurement_attempt += 1

                    if (
                        self.point_measurement_max_attempts
                        is not None
                        and point_measurement_attempt
                        > self.point_measurement_max_attempts
                    ):
                        raise RuntimeError(
                            "STEP_RAMP exceeded the maximum "
                            "number of complete measurement "
                            f"attempts at {setpoint_mk:g} mK."
                        )

                    # ======================================================
                    # WAIT_STABLE
                    # ======================================================

                    stability_result = (
                        self._wait_for_stability(
                            setpoint_mk=setpoint_mk,
                            tolerance_mk=self.tolerance_mk,
                            stable_time_s=self.stable_time_s,
                            timeout_s=(
                                self.stability_timeout_s
                            ),
                            sample_interval_s=(
                                self.stability_sample_interval_s
                            ),
                            max_std_mk=self.max_std_mk,
                            max_slope_mk_per_min=(
                                self.max_slope_mk_per_min
                            ),
                        )
                    )

                    if self.abort_requested():
                        raise InterruptedError(
                            "STEP_RAMP stop requested after "
                            "MXC stabilization."
                        )

                    # ======================================================
                    # ENABLE_SAMPLE
                    # AUTORANGE
                    # MEASURE
                    # RESTORE_MXC
                    # VERIFY_POINT
                    #
                    # All these states are managed internally by
                    # _measure_and_verify_point().
                    # ======================================================

                    point_result = (
                        self._measure_and_verify_point(
                            setpoint_mk=setpoint_mk,
                            stability_result=(
                                stability_result
                            ),
                            tolerance_mk=(
                                self.tolerance_mk
                            ),
                            autorange_max_attempts=(
                                self.autorange_max_attempts
                            ),
                            resistance_n_samples=(
                                self.resistance_n_samples
                            ),
                            resistance_sample_interval_s=(
                                self.resistance_sample_interval_s
                            ),
                            resistance_max_attempts=(
                                self.resistance_max_attempts
                            ),
                        )
                    )

                    if self.abort_requested():
                        raise InterruptedError(
                            "STEP_RAMP stop requested after "
                            "point measurement."
                        )

                    # ------------------------------------------------------
                    # Post-measurement temperature validation failed.
                    #
                    # Do NOT store anything. Return to WAIT_STABLE and
                    # repeat the same setpoint.
                    # ------------------------------------------------------

                    if not point_result.get(
                        "accepted"
                    ):

                        reason = point_result.get(
                            "reason",
                            "unknown reason",
                        )

                        print(
                            "⚠ STEP_RAMP point rejected at "
                            f"{setpoint_mk:g} mK: "
                            f"{reason}. "
                            "Returning to WAIT_STABLE."
                        )

                        with self._status_lock:
                            self._stable_time_s = 0.0

                        continue

                    # ======================================================
                    # STORE_POINT
                    # ======================================================

                    self._set_state("STORE_POINT")

                    measured_temperature_k = float(
                        point_result[
                            "measured_temperature_k"
                        ]
                    )

                    mean_resistance_ohm = float(
                        point_result[
                            "mean_resistance_ohm"
                        ]
                    )

                    if (
                        not math.isfinite(
                            measured_temperature_k
                        )
                        or not math.isfinite(
                            mean_resistance_ohm
                        )
                    ):
                        raise RuntimeError(
                            "Verified STEP_RAMP point contains "
                            "non-finite data."
                        )

                    append_ok = self._append_point(
                        tmxc_k=measured_temperature_k,
                        resistance_ohm=(
                            mean_resistance_ohm
                        ),
                    )

                    if not append_ok:
                        raise RuntimeError(
                            "Could not append verified "
                            "STEP_RAMP point to RELATION."
                        )

                    with self._status_lock:

                        self._last_resistance_ohm = (
                            mean_resistance_ohm
                        )

                        self._last_resistance_std_ohm = (
                            float(
                                point_result[
                                    "std_resistance_ohm"
                                ]
                            )
                        )

                        self._current_mxc_temperature_mk = (
                            float(
                                point_result[
                                    "measured_temperature_mk"
                                ]
                            )
                        )

                        self._resistance_range = int(
                            point_result[
                                "resistance_range"
                            ]
                        )

                    print(
                        "✅ STEP_RAMP point stored: "
                        f"T="
                        f"{point_result['measured_temperature_mk']:.6g} "
                        "mK, "
                        f"R={mean_resistance_ohm:.12g} Ohm, "
                        f"range="
                        f"{point_result['resistance_range']}."
                    )

                    # Before changing to the next setpoint, require the MXC
                    # control loop to recover completely from the sample
                    # measurement cycle.
                    if point_index < self.total_points - 1:

                        print(
                            "⏳ STEP_RAMP waiting for MXC recovery "
                            f"at {setpoint_mk:g} mK before the next "
                            "setpoint."
                        )

                        recovery_result = (
                            self._wait_for_stability(
                                setpoint_mk=setpoint_mk,
                                tolerance_mk=self.tolerance_mk,
                                stable_time_s=self.stable_time_s,
                                timeout_s=(
                                    self.stability_timeout_s
                                ),
                                sample_interval_s=(
                                    self.stability_sample_interval_s
                                ),
                                max_std_mk=self.max_std_mk,
                                max_slope_mk_per_min=(
                                    self.max_slope_mk_per_min
                                ),
                            )
                        )

                        if self.abort_requested():
                            raise InterruptedError(
                                "STEP_RAMP stop requested during "
                                "post-measurement MXC recovery."
                            )

                        print(
                            "✅ STEP_RAMP MXC recovered after sample "
                            "measurement: "
                            f"mean={recovery_result['mean_mk']:.6g} mK, "
                            f"std={recovery_result['std_mk']:.6g} mK, "
                            "slope="
                            f"{recovery_result['slope_mk_per_min']:.6g} "
                            "mK/min."
                        )

                    # Current setpoint is complete.
                    break

                # ==========================================================
                # NEXT_POINT
                # ==========================================================

                if (
                    point_index
                    < self.total_points - 1
                ):
                    self._set_state("NEXT_POINT")

            # ==============================================================
            # All requested points have been stored.
            # ==============================================================

            outcome = "COMPLETE"

        except InterruptedError as exc:

            outcome = "ABORTED"

            print(
                "⏹ STEP_RAMP aborted."
                f"\nReason: {exc}"
            )

        except Exception as exc:

            outcome = "ERROR"
            execution_error = exc

            print(
                "❌ STEP_RAMP execution failed."
                f"\nReason: {exc}"
            )

        # ==================================================================
        # CLEANUP
        #
        # Must happen on COMPLETE, ABORTED and ERROR.
        # ==================================================================

        self._set_state("CLEANUP")

        try:

            cleanup_result = self._cleanup()

        except Exception as exc:

            # _cleanup() itself is designed as best-effort and normally
            # should never escape, but keep a final safety layer here.
            cleanup_result = {
                "ok": False,
                "errors": [
                    f"Unexpected cleanup exception: {exc}"
                ],
            }

        if not cleanup_result.get("ok"):

            cleanup_errors = cleanup_result.get(
                "errors",
                [],
            )

            cleanup_description = (
                " | ".join(
                    str(error)
                    for error in cleanup_errors
                )
                or "unknown cleanup error"
            )

            if execution_error is None:

                execution_error = RuntimeError(
                    "STEP_RAMP cleanup failed: "
                    f"{cleanup_description}"
                )

            else:

                execution_error = RuntimeError(
                    f"{execution_error}; "
                    "cleanup also failed: "
                    f"{cleanup_description}"
                )

            outcome = "ERROR"

        # ==================================================================
        # FINALIZE RELATION
        #
        # Persist all successfully accepted points, including partial data
        # on ABORTED or ERROR runs.
        # ==================================================================

        try:

            finalized_file, finalized_points = (
                self._finalize()
            )

            if finalized_file is None:

                raise RuntimeError(
                    "The STEP_RAMP RELATION could not "
                    "be finalized."
                )

            print(
                "💾 STEP_RAMP relation finalized: "
                f"{finalized_file} "
                f"({finalized_points} points)."
            )

        except Exception as exc:

            if execution_error is None:

                execution_error = RuntimeError(
                    "STEP_RAMP relation finalization "
                    f"failed: {exc}"
                )

            else:

                execution_error = RuntimeError(
                    f"{execution_error}; "
                    "RELATION finalization also failed: "
                    f"{exc}"
                )

            outcome = "ERROR"

        # ==================================================================
        # Publish terminal status
        # ==================================================================

        if outcome == "ERROR":

            self._set_error(
                execution_error
            )

            self._set_state("ERROR")

        elif outcome == "ABORTED":

            self._set_error(None)
            self._set_state("ABORTED")

        else:

            self._set_error(None)
            self._set_state("COMPLETE")