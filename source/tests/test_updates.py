import io, json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from src import desktop_updates as u

class UpdateTests(unittest.TestCase):
    def release(self, **kw):
        return dict(version="1.0.23", url="https://example.com/app.zip", sha256="a"*64, notes="Test", **kw)
    def test_versions(self):
        self.assertGreater(u.version_tuple("1.0.23"),u.version_tuple("1.0.9"))
        for bad in ("x", "1.0", "1.0.2;run"):
            with self.assertRaises(ValueError): u.version_tuple(bad)
    def test_urls(self):
        for bad in ("http://example.com", "file:///test", "https://user:pass@example.com/a"):
            with self.assertRaises(ValueError): u.https_url(bad)
    def test_new_release(self):
        with patch.object(u,"read_https",return_value=json.dumps(self.release()).encode()):
            self.assertEqual(u.check_update("https://example.com/feed")["version"],"1.0.23")
    def test_current(self):
        release=self.release(); release["version"]=u.VERSION
        with patch.object(u,"read_https",return_value=json.dumps(release).encode()):
            self.assertIsNone(u.check_update("https://example.com/feed"))
    def test_bad_hash(self):
        release=self.release(); release["sha256"]="missing"
        with patch.object(u,"read_https",return_value=json.dumps(release).encode()):
            with self.assertRaises(ValueError): u.check_update("https://example.com/feed")
    def test_hash_mismatch_does_not_install(self):
        with patch.object(u,"read_https",return_value=b"wrong"), patch.object(u,"settings_path") as path:
            with self.assertRaises(ValueError): u.install_release(self.release())
            path.assert_not_called()
    def zip(self, extra=None):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w") as z:
            z.writestr("LoadoutRoom1.0.exe",b"MZfixture")
            z.writestr("runtime/pythonw.exe",b"MZfixture")
            z.writestr("app/desktop.py","fixture")
            if extra: z.writestr(extra,"unsafe")
        stream.seek(0); return stream
    def test_renamed_launcher_is_supported(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w") as z:
            z.writestr("LoadoutRoom.exe",b"MZfixture")
            z.writestr("runtime/pythonw.exe",b"MZfixture")
            z.writestr("app/desktop.py","fixture")
        stream.seek(0)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as folder:
            exe=u.extract_release(stream,Path(folder)/"release")
            self.assertEqual(exe.name,"LoadoutRoom.exe")
            self.assertTrue(exe.is_file())
    def test_valid_zip(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as folder:
            exe=u.extract_release(self.zip(),Path(folder)/"release")
            self.assertTrue(exe.is_file())
    def test_traversal_and_absolute_paths_rejected(self):
        for name in ("../outside.txt","/outside.txt","C:/outside.txt","app/../../outside.txt","app/evil:stream"):
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as folder:
                destination=Path(folder)/"release"
                with self.assertRaises(ValueError): u.extract_release(self.zip(name),destination)
                self.assertFalse(destination.exists())
    def test_missing_settings_uses_publisher_feed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as folder, patch.object(u,"settings_path",return_value=Path(folder)/"missing.json"):
            self.assertEqual(u.read_settings(),{"feed":u.DEFAULT_FEED,"check_on_start":True})

if __name__=="__main__": unittest.main()