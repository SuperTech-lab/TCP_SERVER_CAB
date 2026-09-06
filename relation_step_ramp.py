"""
@author: Victor
"""

import math
import threading

from collections.abc import Callable
from typing import Any

from default_config import SAMPLE_CHANNELS

# Tagging the callback types for clarity. 
# These tags correspond to _append_relation_point() and _
# finalize_relation() from tcp_server.py.
AppendPointCallback      = Callable[..., bool]
FinalizeRelationCallback = Callable[..., tuple[str | None, int]]


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
        "COMPLETE",
        "ABORTED",
        "ERROR",
    }

    TERMINAL_STATES = {
        "COMPLETE",
        "ABORTED",
        "ERROR",
    }

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
        append_point: AppendPointCallback,
        finalize_relation: FinalizeRelationCallback,
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
            Sample resistance channel, normally one of SAMPLE_CHANNELS.

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

        # ------------------------------------------------------------------
        # Injected server dependencies
        # ------------------------------------------------------------------

        self.ls = lakeshore
        self.heater_mutex = heater_mutex

        self._append_relation_point = append_point
        self._finalize_relation = finalize_relation

        # ------------------------------------------------------------------
        # Immutable acquisition identity / geometry
        # ------------------------------------------------------------------

        self.relation_id = relation_id.strip()
        self.channel_number = channel_number

        self.setpoints_mk = normalized_setpoints
        self.initial_mk = normalized_setpoints[0]
        self.target_mk = target_mk
        self.step_mk = step_mk

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
        STEP_RAMP execution logic.

        This is intentionally left unimplemented at this stage.

        It will be completed after:
        - _preflight()
        - settling-time calculation
        - _wait_for_stability()
        - _external_autorange()
        - _collect_resistance_samples()
        - _measure_and_verify_point()
        - _cleanup()

        have been implemented and tested.
        """

        raise NotImplementedError(
            "STEP_RAMP execution has not been "
            "implemented yet."
        )