"""
D.I.O. UI Package
"""

from dio.ui.dialogs import (
    GridChooserDialog,
    KeySequenceRecorderDialog,
    OmniSearchDialog,
    SettingsOverlayDialog,
    resolve_query_or_url,
)
from dio.ui.widgets import (
    CrashOverlay,
    HibernationOverlay,
    LoadingOverlay,
    MutedIndicator,
    SeamlessSplitter,
    SeamlessSplitterHandle,
    ToastNotification,
)
from dio.ui.window import DIOWindow

__all__ = [
    "DIOWindow",
    "SeamlessSplitter",
    "SeamlessSplitterHandle",
    "LoadingOverlay",
    "MutedIndicator",
    "ToastNotification",
    "HibernationOverlay",
    "CrashOverlay",
    "OmniSearchDialog",
    "KeySequenceRecorderDialog",
    "SettingsOverlayDialog",
    "GridChooserDialog",
    "resolve_query_or_url",
]
