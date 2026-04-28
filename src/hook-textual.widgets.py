# PyInstaller hook to ensure all textual widgets are included
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('textual.widgets')
