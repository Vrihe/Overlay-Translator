"""
hook-optree.py — PyInstaller hook for optree with isolated_import disabled.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

isolated_import = False

datas = collect_data_files('optree')
binaries = collect_dynamic_libs('optree')
hiddenimports = ['optree._C']
excludedimports = ['optree.integrations']
