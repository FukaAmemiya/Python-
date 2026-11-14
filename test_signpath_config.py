"""Offline checks for SignPath configuration and PyInstaller version identity."""

import ast
import unittest
from pathlib import Path
from xml.etree import ElementTree

from build_version_info import EXE_NAME, PRODUCT, metadata


class SignPathConfigurationTests(unittest.TestCase):
    def test_windows_product_metadata_for_release(self):
        resource, version = metadata("v1.1.1")
        self.assertEqual(version, "1.1.1.0")
        ast.parse(resource, mode="eval")
        self.assertIn("StringStruct('ProductName', '双站小说下载器 (FukaAmemiya)')", resource)
        self.assertIn("StringStruct('ProductVersion', '1.1.1.0')", resource)
        self.assertIn("StringStruct('OriginalFilename', 'NovelDownloader-Windows-x64.exe')", resource)

    def test_preview_version_and_invalid_versions(self):
        self.assertEqual(metadata("v0.0.0")[1], "0.0.0.0")
        for invalid in ("", "1.2", "v1.2.3.4", "v1.2.3-beta", "../x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    metadata(invalid)

    def test_signpath_xml_artifact_matches_executable(self):
        document = ElementTree.parse(
            Path(__file__).resolve().parent / ".signpath" / "artifact-configuration.xml"
        )
        namespace = "{http://signpath.io/artifact-configuration/v1}"
        binary = document.find(f"{namespace}zip-file/{namespace}pe-file")
        self.assertIsNotNone(binary)
        self.assertEqual(binary.attrib["path"], EXE_NAME)
        self.assertEqual(binary.attrib["product-name"], PRODUCT)
        self.assertEqual(binary.attrib["product-version"], "${version}")
        self.assertEqual(binary.attrib["file-version"], "${version}")
        self.assertIsNotNone(binary.find(f"{namespace}authenticode-sign"))


if __name__ == "__main__":
    unittest.main()
