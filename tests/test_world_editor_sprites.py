import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'WorldEditor'))
import sprites  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent


class Sprites(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache)
        self.library = sprites.Library(PROJECT, self.cache)

    def test_a_building_is_drawn_from_its_sprite(self):
        picture, origin = self.library.picture('casa1')
        self.assertGreater(picture.width, 150)
        self.assertGreater(picture.height, 100)
        self.assertEqual(picture.mode, 'RGBA')
        self.assertEqual(picture.getpixel((0, 0))[3], 0)  # the corners are see-through
        self.assertTrue((self.cache / 'casa1.png').exists())

    def test_a_unit_faces_the_viewer_and_stands_on_its_origin(self):
        raw = (PROJECT / 'assets' / 'buildingsprites' / 'aldeanohombre.swf').read_bytes()
        back, _ = sprites.compose(raw, 'aldeanohombre', 1)
        front, (x, y) = self.library.picture('aldeanohombre', unit=True)
        self.assertNotEqual(back.tobytes(), front.tobytes())  # another frame than the back view
        self.assertTrue(0 < x < front.width and front.height * 0.7 < y <= front.height)  # the feet

    def test_unknown_pictures_are_remembered_and_the_index_kept(self):
        self.assertIsNone(self.library.picture('no_existe'))
        self.assertIsNone(self.library.picture(''))
        self.library.picture('casa1')
        self.library.save_index()
        again = sprites.Library(PROJECT, self.cache)
        self.assertIs(again.index['no_existe'], False)
        self.assertIsNotNone(again.picture('casa1'))
        self.assertIsNotNone(self.library.thumbnail('1', 'casa1'))


if __name__ == '__main__':
    unittest.main()
