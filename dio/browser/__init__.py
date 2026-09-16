"""
D.I.O. Browser Package
"""

from dio.browser.interceptor import AdBlockInterceptor
from dio.browser.page import DIOPage
from dio.browser.scripts import make_anti_detection_script, make_dark_mode_script

__all__ = [
    "AdBlockInterceptor",
    "DIOPage",
    "make_dark_mode_script",
    "make_anti_detection_script",
]
