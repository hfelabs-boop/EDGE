"""Tobii Pro eye trackers (Spectrum, Fusion, Spark, Nano, X3, TX300, Pro Glasses via SDK) using tobii_research.

Gaze samples carry ``system_time_stamp`` — microseconds on this computer's
clock as reported by ``tobii_research.get_system_time_stamp()``. EDGE fits a
round-trip clock model between that clock and the master clock, giving
sub-millisecond alignment without relying on sample arrival times.

Calibration uses Tobii's ScreenBasedCalibration with targets drawn by EDGE in
the experiment window, followed by an optional validation summary.
"""

from __future__ import annotations

import math
from typing import Any

from ..events import Marker
from ..sync import RoundTripSync
from . import register
from .base import Device, DeviceError

GAZE_FIELDS = ["device_time_stamp", "system_time_stamp",
               "left_x", "left_y", "left_valid", "right_x", "right_y", "right_valid",
               "left_pupil", "left_pupil_valid", "right_pupil", "right_pupil_valid",
               "left_origin_z", "right_origin_z", "marker"]


@register
class TobiiPro(Device):
    type_name = "tobii"
    description = "Tobii Pro screen-based eye trackers via the Tobii Pro SDK (tobii_research)."
    capabilities = {"stream", "gaze", "calibration", "markers"}
    requires = ["tobii_research"]
    options_schema = {
        "address": {"type": "str", "default": "", "help": "tobii-prp://... address; empty = first tracker found"},
        "serial": {"type": "str", "default": "", "help": "select tracker by serial number"},
        "frequency": {"type": "float", "default": None, "help": "set gaze output frequency (Hz) if supported"},
        "license_file": {"type": "str", "default": "", "help": "license file for trackers that need one"},
        "calibration_points": {"type": "list",
                               "default": [[0.5, 0.5], [0.1, 0.1], [0.1, 0.9], [0.9, 0.1], [0.9, 0.9]]},
        "eye": {"type": "choice", "choices": ["average", "left", "right"], "default": "average"},
    }

    def connect(self) -> None:
        try:
            import tobii_research as tr
        except ImportError as e:
            raise DeviceError("Tobii Pro SDK not installed: pip install tobii-research") from e
        self.tr = tr
        if self.options["address"]:
            et = tr.EyeTracker(self.options["address"])
        else:
            found = tr.find_all_eyetrackers()
            if self.options["serial"]:
                found = [e for e in found if e.serial_number == self.options["serial"]]
            if not found:
                raise DeviceError("no Tobii eye tracker found (check USB/network and Tobii Pro Eye Tracker Manager)")
            et = found[0]
        self.et = et
        if self.options["license_file"]:
            with open(self.options["license_file"], "rb") as f:
                failed = et.apply_licenses([tr.LicenseKey(f.read())])
            if failed:
                raise DeviceError(f"Tobii license rejected: {failed}")
        if self.options["frequency"]:
            et.set_gaze_output_frequency(float(self.options["frequency"]))
        self.srate = et.get_gaze_output_frequency()
        # Device time base used for alignment = system_time_stamp in seconds.
        self.add_stream("gaze", GAZE_FIELDS, self.srate, "Gaze")
        self.rt_sync = RoundTripSync(lambda: tr.get_system_time_stamp() / 1e6, self.clock)
        self.rt_sync.probe(50)
        self._latest = None
        self._pending_marker = ""
        self.connected = True

    def _on_gaze(self, g: dict[str, Any]) -> None:
        lx, ly = g["left_gaze_point_on_display_area"]
        rx, ry = g["right_gaze_point_on_display_area"]
        lv, rv = g["left_gaze_point_validity"], g["right_gaze_point_validity"]
        marker, self._pending_marker = self._pending_marker, ""
        values = [g["device_time_stamp"], g["system_time_stamp"], lx, ly, lv, rx, ry, rv,
                  g["left_pupil_diameter"], g["left_pupil_validity"], g["right_pupil_diameter"],
                  g["right_pupil_validity"],
                  g.get("left_gaze_origin_in_user_coordinate_system", (None, None, None))[2],
                  g.get("right_gaze_origin_in_user_coordinate_system", (None, None, None))[2], marker]
        self.emit("gaze", g["system_time_stamp"] / 1e6, values, sync=False)
        eye = self.options["eye"]
        pts = []
        if lv and eye in ("average", "left") and not math.isnan(lx):
            pts.append((lx, ly))
        if rv and eye in ("average", "right") and not math.isnan(rx):
            pts.append((rx, ry))
        if pts:
            x = sum(p[0] for p in pts) / len(pts)
            y = sum(p[1] for p in pts) / len(pts)
            self._latest = self.norm_to_window(x, y)

    def start(self) -> None:
        self.et.subscribe_to(self.tr.EYETRACKER_GAZE_DATA, self._on_gaze, as_dictionary=True)
        self.recording = True

    def poll(self) -> None:
        # Cheap periodic re-probing keeps the drift estimate fresh during long sessions.
        if self.recording and self.n_samples.get("gaze", 0) % 600 == 0:
            self.rt_sync.probe(1)

    def stop(self) -> None:
        if self.recording:
            self.et.unsubscribe_from(self.tr.EYETRACKER_GAZE_DATA, self._on_gaze)
        self.recording = False

    def finalize_clock(self):
        self.rt_sync.probe(50)
        self.clock_model = self.rt_sync.model()
        return self.clock_model

    def send_marker(self, marker: Marker) -> None:
        # The Pro SDK has no marker channel; stamp the label into the next gaze sample's 'marker' column.
        self._pending_marker = marker.label

    def latest_gaze(self):
        return self._latest

    def calibrate(self, session) -> dict[str, Any]:
        if session is None or session.backend is None:
            raise DeviceError("Tobii calibration needs an open window")
        tr = self.tr
        cal = tr.ScreenBasedCalibration(self.et)
        cal.enter_calibration_mode()
        backend = session.backend
        try:
            for (x, y) in self.options["calibration_points"]:
                px, py = self.norm_to_window(x, y)
                # shrinking target: 0.8 s to draw attention, then collect
                for i in range(int(0.8 * backend.refresh_rate)):
                    r = 20 - 14 * i / (0.8 * backend.refresh_rate)
                    backend.draw_calibration_target(px, py, r)
                    backend.flip()
                    if backend.check_escape():
                        return {"result": "aborted"}
                if cal.collect_data(x, y) != tr.CALIBRATION_STATUS_SUCCESS:
                    cal.collect_data(x, y)  # Tobii recommends one retry
            res = cal.compute_and_apply()
        finally:
            cal.leave_calibration_mode()
        points = []
        for p in res.calibration_points:
            errs = []
            for s in p.calibration_samples:
                for eye in (s.left_eye, s.right_eye):
                    if eye.validity == tr.VALIDITY_VALID_AND_USED:
                        dx = eye.position_on_display_area[0] - p.position_on_display_area[0]
                        dy = eye.position_on_display_area[1] - p.position_on_display_area[1]
                        errs.append(math.hypot(dx, dy))
            points.append({"x": p.position_on_display_area[0], "y": p.position_on_display_area[1],
                           "mean_error_norm": sum(errs) / len(errs) if errs else None})
        return {"result": "ok" if res.status == tr.CALIBRATION_STATUS_SUCCESS else "failed", "points": points}

    def info(self) -> dict[str, Any]:
        return {"model": self.et.model, "serial": self.et.serial_number, "address": self.et.address,
                "firmware": self.et.firmware_version, "frequency": self.srate}
