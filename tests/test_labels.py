import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from app import Explorer

class LabelTests(unittest.TestCase):
    def object(self, text):
        app = Explorer.__new__(Explorer)
        app.selected = Mock(return_value={'label_key':'network|device'})
        app.label = Mock(); app.label.get.return_value = text
        app.labels = {}
        app.status = Mock(); app.render = Mock()
        return app
    def test_save_and_clear_are_local_and_private(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.STATE',Path(folder)/'.state'):
            app=self.object('My phone')
            app.save_label()
            file=Path(folder)/'.state/labels.json'
            self.assertEqual(json.loads(file.read_text()),{'network|device':'My phone'})
            self.assertEqual(file.stat().st_mode & 0o777,0o600)
            app.label.get.return_value=''
            app.save_label()
            self.assertEqual(json.loads(file.read_text()),{})
    def test_control_chars_and_long_labels_are_rejected(self):
        for label in ['abc\x00def','x'*81]:
            with tempfile.TemporaryDirectory() as folder, patch('app.STATE',Path(folder)/'.state'):
                self.object(label).save_label()
                self.assertFalse((Path(folder)/'.state').exists())
    def test_no_selection_does_not_write(self):
        app=self.object('Something'); app.selected.return_value=None
        app.save_label(); app.render.assert_not_called()
    def test_export_preserves_evidence_and_marks_user_label(self):
        app=self.object(''); app.labels={'network|device':'Mine'}
        app.snapshot={'devices':[{'label_key':'network|device','role':'Unknown device'}]}
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'export.json'
            with patch('app.filedialog.asksaveasfilename',return_value=str(file)):
                app.export()
            data=json.loads(file.read_text())
            self.assertEqual(data['devices'][0]['role'],'Unknown device')
            self.assertEqual(data['devices'][0]['user_label'],'Mine')
            self.assertEqual(file.stat().st_mode & 0o777,0o600)
            self.assertNotIn('user_label',app.snapshot['devices'][0])
