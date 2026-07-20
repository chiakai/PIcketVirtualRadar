import unittest

from picket_virtual_radar.config import TouchConfig
from picket_virtual_radar.touch import GestureRecognizer, transform_coordinates


class TouchTests(unittest.TestCase):
    def setUp(self):
        self.config = TouchConfig(
            tap_max_seconds=0.35,
            long_press_seconds=0.7,
            move_tolerance_px=12,
            swipe_min_px=40,
        )

    def test_rotation_270_matches_measured_corners(self):
        self.assertEqual(transform_coordinates(20, 311, 320, 240, 270), (8, 20))
        self.assertEqual(transform_coordinates(0, 8, 320, 240, 270), (311, 0))
        self.assertEqual(transform_coordinates(237, 1, 320, 240, 270), (318, 237))
        self.assertEqual(transform_coordinates(237, 316, 320, 240, 270), (3, 237))

    def test_rotation_90_is_180_degrees_from_rotation_270(self):
        x_270, y_270 = transform_coordinates(20, 311, 320, 240, 270)
        self.assertEqual(
            transform_coordinates(20, 311, 320, 240, 90),
            (319 - x_270, 239 - y_270),
        )

    def test_tap(self):
        recognizer = GestureRecognizer(self.config)
        recognizer.press(100, 100, 1.0)
        gesture = recognizer.release(104, 102, 1.2)
        self.assertEqual(gesture.kind, "tap")

    def test_long_press(self):
        recognizer = GestureRecognizer(self.config)
        recognizer.press(100, 100, 1.0)
        gesture = recognizer.release(102, 101, 1.8)
        self.assertEqual(gesture.kind, "long_press")

    def test_horizontal_swipes(self):
        recognizer = GestureRecognizer(self.config)
        recognizer.press(100, 100, 1.0)
        self.assertEqual(recognizer.release(40, 104, 1.4).direction, "left")
        recognizer.press(100, 100, 2.0)
        self.assertEqual(recognizer.release(160, 96, 2.4).direction, "right")

    def test_vertical_swipes(self):
        recognizer = GestureRecognizer(self.config)
        recognizer.press(100, 150, 1.0)
        self.assertEqual(recognizer.release(104, 80, 1.4).direction, "up")
        recognizer.press(100, 80, 2.0)
        self.assertEqual(recognizer.release(96, 150, 2.4).direction, "down")

    def test_diagonal_motion_is_not_horizontal_swipe(self):
        recognizer = GestureRecognizer(self.config)
        recognizer.press(100, 100, 1.0)
        self.assertIsNone(recognizer.release(150, 155, 1.4))


if __name__ == "__main__":
    unittest.main()
