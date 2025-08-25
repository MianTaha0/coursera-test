import argparse
import math
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
import yaml


@dataclass
class Roi:
	x: int
	y: int
	w: int
	h: int

	def as_tuple(self) -> Tuple[int, int, int, int]:
		return (self.x, self.y, self.w, self.h)


@dataclass
class DetectionParams:
	min_circularity: float = 0.4
	min_area_ratio: float = 0.0005  # relative to ROI area
	max_area_ratio: float = 0.03    # relative to ROI area
	gaussian_blur_ksize: int = 5
	morph_kernel_size: int = 3
	green_h_low: int = 35
	green_h_high: int = 85
	saturation_min: int = 40
	value_min: int = 30


@dataclass
class StateParams:
	min_balls_for_arm: int = 10
	min_balls_after_break: int = 5
	arm_radius_ratio: float = 0.10   # of ROI width
	break_radius_ratio: float = 0.22 # of ROI width
	arm_frames: int = 20
	break_frames: int = 10
	ema_alpha: float = 0.2


class BreakDetector:
	def __init__(
		self,
		roi: Optional[Roi],
		det_params: DetectionParams,
		state_params: StateParams,
		gui: bool = True,
	):
		self.roi = roi
		self.det_params = det_params
		self.state_params = state_params
		self.gui = gui

		self.armed_streak = 0
		self.break_streak = 0
		self.state = "IDLE"  # IDLE -> ARMED -> IDLE
		self.break_count = 0
		self.radius_ema: Optional[float] = None

	def save_roi(self, path: str) -> None:
		if self.roi is None:
			raise ValueError("No ROI to save")
		with open(path, "w") as f:
			yaml.safe_dump({"x": self.roi.x, "y": self.roi.y, "w": self.roi.w, "h": self.roi.h}, f)

	@staticmethod
	def load_roi(path: str) -> Roi:
		with open(path, "r") as f:
			data = yaml.safe_load(f)
		return Roi(int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))

	def calibrate_with_select_roi(self, frame: np.ndarray) -> None:
		if not self.gui:
			raise RuntimeError("ROI selection requires GUI. Run without --no-gui.")
		r = cv2.selectROI("Select Rack ROI", frame, fromCenter=False, showCrosshair=True)
		cv2.destroyWindow("Select Rack ROI")
		if r is not None and len(r) == 4 and r[2] > 0 and r[3] > 0:
			self.roi = Roi(int(r[0]), int(r[1]), int(r[2]), int(r[3]))

	def _roi_crop(self, frame: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int]]:
		if self.roi is None:
			return frame, (0, 0)
		x, y, w, h = self.roi.as_tuple()
		h, w_f = frame.shape[:2]
		x0 = max(0, min(x, w_f - 1))
		y0 = max(0, min(y, h - 1))
		x1 = max(1, min(x + w, w_f))
		y1 = max(1, min(y + h, h))
		return frame[y0:y1, x0:x1], (x0, y0)

	def _mask_non_green(self, roi_img: np.ndarray) -> np.ndarray:
		p = self.det_params
		hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
		# Green mask
		lower_green = np.array([p.green_h_low, p.saturation_min, p.value_min])
		upper_green = np.array([p.green_h_high, 255, 255])
		mask_green = cv2.inRange(hsv, lower_green, upper_green)
		mask_non_green = cv2.bitwise_not(mask_green)
		return mask_non_green

	def _find_ball_candidates(self, roi_img: np.ndarray) -> List[Tuple[int, int, float]]:
		p = self.det_params
		gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
		if p.gaussian_blur_ksize > 1:
			gray = cv2.GaussianBlur(gray, (p.gaussian_blur_ksize, p.gaussian_blur_ksize), 0)
		mask = self._mask_non_green(roi_img)
		kernel = np.ones((p.morph_kernel_size, p.morph_kernel_size), np.uint8)
		mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
		mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
		contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
		roi_area = roi_img.shape[0] * roi_img.shape[1]
		min_area = max(5.0, p.min_area_ratio * roi_area)
		max_area = p.max_area_ratio * roi_area
		candidates: List[Tuple[int, int, float]] = []
		for c in contours:
			area = cv2.contourArea(c)
			if area < min_area or area > max_area:
				continue
			perim = cv2.arcLength(c, True)
			if perim <= 0:
				continue
			circularity = 4.0 * math.pi * (area / (perim * perim))
			if circularity < p.min_circularity:
				continue
			m = cv2.moments(c)
			if m["m00"] == 0:
				continue
			cx = int(m["m10"] / m["m00"])
			cy = int(m["m01"] / m["m00"])
			candidates.append((cx, cy, area))
		return candidates

	def _compute_dispersion(self, points: List[Tuple[int, int, float]]) -> float:
		if not points:
			return 0.0
		coords = np.array([(x, y) for x, y, _ in points], dtype=np.float32)
		center = coords.mean(axis=0)
		dists = np.linalg.norm(coords - center, axis=1)
		return float(np.mean(dists))

	def _update_state(self, dispersion_px: float, num_balls: int, roi_width: int) -> None:
		sp = self.state_params
		arm_thresh = sp.arm_radius_ratio * float(roi_width)
		break_thresh = sp.break_radius_ratio * float(roi_width)

		# EMA smoothing on dispersion
		if self.radius_ema is None:
			self.radius_ema = dispersion_px
		else:
			self.radius_ema = sp.ema_alpha * dispersion_px + (1.0 - sp.ema_alpha) * self.radius_ema

		if self.state == "IDLE":
			if num_balls >= sp.min_balls_for_arm and self.radius_ema <= arm_thresh:
				self.armed_streak += 1
			else:
				self.armed_streak = 0
			if self.armed_streak >= sp.arm_frames:
				self.state = "ARMED"
				self.break_streak = 0
		elif self.state == "ARMED":
			if num_balls >= sp.min_balls_after_break and self.radius_ema >= break_thresh:
				self.break_streak += 1
			else:
				self.break_streak = 0
			if self.break_streak >= sp.break_frames:
				self.break_count += 1
				# After counting, return to IDLE and wait for a new rack or manual re-arm
				self.state = "IDLE"
				self.armed_streak = 0
				self.break_streak = 0

	def process_frame(self, frame: np.ndarray) -> np.ndarray:
		roi_img, (off_x, off_y) = self._roi_crop(frame)
		cands = self._find_ball_candidates(roi_img)
		dispersion = self._compute_dispersion(cands)
		roi_w = roi_img.shape[1]
		self._update_state(dispersion, len(cands), roi_w)

		if self.gui:
			self._draw_overlay(frame, cands, (off_x, off_y), dispersion)
		return frame

	def _draw_overlay(self, frame: np.ndarray, cands: List[Tuple[int, int, float]], offset: Tuple[int, int], dispersion: float) -> None:
		ox, oy = offset
		if self.roi is not None:
			x, y, w, h = self.roi.as_tuple()
			cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 0), 2)
		for (cx, cy, _) in cands:
			cv2.circle(frame, (ox + cx, oy + cy), 6, (0, 0, 255), 2)
		text = f"State: {self.state}  Count: {self.break_count}  Disp(px): {dispersion:.1f}  EMA: {0.0 if self.radius_ema is None else self.radius_ema:.1f}"
		cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 220, 50), 2, cv2.LINE_AA)


def open_capture(source: str) -> cv2.VideoCapture:
	# source can be integer camera index or path
	cap: Optional[cv2.VideoCapture]
	try:
		idx = int(source)
		cap = cv2.VideoCapture(idx)
	except ValueError:
		cap = cv2.VideoCapture(source)
	return cap


def parse_args(argv: List[str]) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Snooker rack break detector")
	parser.add_argument("--source", type=str, default="0", help="Video source: camera index (e.g., 0) or file path")
	parser.add_argument("--roi", type=str, default=None, help="Path to ROI yaml to load")
	parser.add_argument("--save-roi", type=str, default=None, help="Path to save current ROI yaml")
	parser.add_argument("--no-gui", action="store_true", help="Disable windows and key controls")
	parser.add_argument("--max-frames", type=int, default=0, help="Process at most N frames (0 = infinite)")
	parser.add_argument("--width", type=int, default=0, help="Set capture width (optional)")
	parser.add_argument("--height", type=int, default=0, help="Set capture height (optional)")

	# Detection params
	parser.add_argument("--min-circularity", type=float, default=0.4)
	parser.add_argument("--min-area-ratio", type=float, default=0.0005)
	parser.add_argument("--max-area-ratio", type=float, default=0.03)
	parser.add_argument("--green-h-low", type=int, default=35)
	parser.add_argument("--green-h-high", type=int, default=85)

	# State params
	parser.add_argument("--min-balls-for-arm", type=int, default=10)
	parser.add_argument("--min-balls-after-break", type=int, default=5)
	parser.add_argument("--arm-radius-ratio", type=float, default=0.10)
	parser.add_argument("--break-radius-ratio", type=float, default=0.22)
	parser.add_argument("--arm-frames", type=int, default=20)
	parser.add_argument("--break-frames", type=int, default=10)
	parser.add_argument("--ema-alpha", type=float, default=0.2)

	return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
	args = parse_args(argv or sys.argv[1:])
	gui = not args.no_gui

	det_params = DetectionParams(
		min_circularity=args.min_circularity,
		min_area_ratio=args.min_area_ratio,
		max_area_ratio=args.max_area_ratio,
		green_h_low=args.green_h_low,
		green_h_high=args.green_h_high,
	)
	state_params = StateParams(
		min_balls_for_arm=args.min_balls_for_arm,
		min_balls_after_break=args.min_balls_after_break,
		arm_radius_ratio=args.arm_radius_ratio,
		break_radius_ratio=args.break_radius_ratio,
		arm_frames=args.arm_frames,
		break_frames=args.break_frames,
		ema_alpha=args.ema_alpha,
	)

	roi: Optional[Roi] = None
	if args.roi:
		try:
			roi = BreakDetector.load_roi(args.roi)
			print(f"Loaded ROI from {args.roi}: {roi}")
		except Exception as e:
			print(f"Failed to load ROI from {args.roi}: {e}")

	detector = BreakDetector(roi, det_params, state_params, gui=gui)

	cap = open_capture(args.source)
	if not cap or not cap.isOpened():
		print("ERROR: Unable to open video source.")
		return 1
	if args.width > 0:
		cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(args.width))
	if args.height > 0:
		cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(args.height))

	window_name = "Snooker Break Detector"
	if gui:
		cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

	processed = 0
	ret, frame = cap.read()
	if not ret:
		print("ERROR: Unable to read first frame.")
		cap.release()
		if gui:
			cv2.destroyAllWindows()
		return 2

	if detector.roi is None and gui:
		print("Press 'c' to calibrate ROI, or proceed to use full frame.")

	while True:
		if processed > 0:
			ret, frame = cap.read()
			if not ret:
				break

		out_frame = detector.process_frame(frame.copy())

		if gui:
			cv2.imshow(window_name, out_frame)
			key = cv2.waitKey(1) & 0xFF
			if key in (27, ord('q')):
				break
			elif key == ord('c'):
				try:
					detector.calibrate_with_select_roi(frame)
					if args.save_roi:
						detector.save_roi(args.save_roi)
						print(f"Saved ROI to {args.save_roi}")
				except Exception as e:
					print(f"Calibration failed: {e}")
			elif key == ord('r'):
				# Manual re-arm: reset state machine to IDLE
				detector.state = "IDLE"
				detector.armed_streak = 0
				detector.break_streak = 0
		else:
			# Headless mode: small sleep to reduce CPU
			time.sleep(0.001)

		processed += 1
		if args.max_frames and processed >= args.max_frames:
			break

	cap.release()
	if gui:
		cv2.destroyAllWindows()
	print(f"Breaks counted: {detector.break_count}")
	return 0


if __name__ == "__main__":
	sys.exit(main())

