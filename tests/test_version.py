import re

from src.app import VeriTrakkApp
from src.storage import Process, Step, generate_log_pdf_bytes
from src.version import __version__


def test_version_is_x_y_z():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_version_in_the_changelog_header_and_pdf_footer():
    changelog = open("CHANGELOG.md", encoding="utf-8").read()
    assert f"## {__version__} (" in changelog
    assert f"v{__version__}" in VeriTrakkApp.SUB_TITLE
    pdf = generate_log_pdf_bytes(Process("Q", kind="work_quest", steps=[Step("A", 1)]))
    assert f"VeriTrakk {__version__}".encode() in pdf
