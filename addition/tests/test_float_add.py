import unittest

from src.float_add import add_floats


class TestFloatAdd(unittest.TestCase):
    def test_add_floats(self):
        self.assertEqual(add_floats(1.5, 2.5), 4.0)

    def test_add_floats_negative(self):
        self.assertEqual(add_floats(-1.0, 1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
