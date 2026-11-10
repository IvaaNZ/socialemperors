"""Verify embedded-label translation preserves the original SWF structure."""

from collections import Counter
from pathlib import Path
import re
import struct
import unittest

from swf_localization import (
    decode_swf, edit_text_offset, encode_tag, iter_tags, localize_swf,
    translate_edit_text, _cstring_end,
)


def flattened_tags(data):
    body, offset = decode_swf(data)
    def walk(stream):
        for code, payload, _ in iter_tags(stream):
            if code == 39:
                yield code, payload[:4]
                yield from walk(payload[4:])
            else:
                yield code, payload
    return list(walk(body[offset:]))


class SwfLocalizationTests(unittest.TestCase):
    def test_original_movie_labels_translate_without_altering_code_or_assets(self):
        original = Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes()
        localized = localize_swf(original, {'Next': 'Avançar'})
        source_tags, translated_tags = flattened_tags(original), flattened_tags(localized)
        self.assertEqual(Counter(code for code, _ in source_tags), Counter(code for code, _ in translated_tags))
        seen_next = False
        for (code, source), (translated_code, translated) in zip(source_tags, translated_tags):
            self.assertEqual(code, translated_code)
            if code == 37:
                source_offset = edit_text_offset(source)
                translated_offset = edit_text_offset(translated)
                self.assertEqual(source_offset, translated_offset)
                if source_offset is not None:
                    self.assertEqual(source[:source_offset], translated[:translated_offset])
                    source_text = source[source_offset:-1].decode('utf-8')
                    translated_text = translated[translated_offset:-1].decode('utf-8')
                    self.assertEqual(
                        re.findall(r'<[^>]+>', source_text),
                        re.findall(r'<[^>]+>', translated_text),
                    )
                    if '>Next<' in source_text:
                        self.assertIn('>Avançar<', translated_text)
                        seen_next = True
                    continue
            self.assertEqual(source, translated)
        self.assertTrue(seen_next)
        # Source is still byte-for-byte identical on disk.
        self.assertEqual(original, Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes())

    def test_longer_label_rebuilds_nested_sprite_and_file_lengths(self):
        # RECT Nbits=1; two zero flags except HasText; empty VariableName.
        payload = b'\x01\x00\x08\x00\x80\x00\x00Next\x00'
        nested = encode_tag(37, payload) + encode_tag(0, b'')
        tags = encode_tag(39, b'\x02\x00\x01\x00' + nested) + encode_tag(0, b'')
        body = b'\x08\x00\x00\x18\x01\x00' + tags
        original = b'FWS\x0a' + struct.pack('<I', len(body) + 8) + body
        result = localize_swf(original, {'Next': 'Próxima etapa: ' + 'a' * 80})
        decoded, _ = decode_swf(result)
        self.assertEqual(struct.unpack_from('<I', result, 4)[0], len(decoded) + 8)
        text_tag = next(payload for code, payload in flattened_tags(result) if code == 37)
        self.assertIn('Próxima etapa: '.encode('utf-8'), text_tag)

    def test_tag_attributes_variables_and_unknown_text_are_preserved(self):
        source = '<p align="center"><font size="18">Next</font></p>'
        self.assertEqual(
            translate_edit_text(source, {'Next': 'Avançar'}),
            '<p align="center"><font size="18">Avançar</font></p>',
        )
        self.assertEqual(translate_edit_text('Uncatalogued mod text', {}), 'Uncatalogued mod text')

    def test_translated_buttons_shrink_to_fit_and_missing_glyphs_keep_source(self):
        def labels(data):
            found = {}
            for code, payload in flattened_tags(data):
                if code == 37 and edit_text_offset(payload) is not None:
                    offset = edit_text_offset(payload)
                    found[struct.unpack_from('<H', payload)[0]] = payload[offset:_cstring_end(payload, offset)].decode('utf-8')
            return found

        original = Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes()
        source = labels(original)
        spanish = labels(localize_swf(original, language='es'))
        # The storage USE button is 42 px wide; USAR at 18 pt would not fit.
        self.assertIn('size="18"', source[3624])
        self.assertIn('USAR', spanish[3624])
        self.assertLess(int(re.search(r'size="(\d+)"', spanish[3624]).group(1)), 18)
        # The countdown font has no G, so SEC stays instead of rendering "SE".
        self.assertEqual(spanish[3614], source[3614])
        self.assertIn('DIA', spanish[3611])


if __name__ == '__main__':
    unittest.main()
