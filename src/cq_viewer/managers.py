import os
import sys


class ImportManager:
    def __init__(self):
        self.module_names = None

    def __enter__(self):
        self.module_names = sys.modules.keys()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        to_delete = [k for k in sys.modules.keys() if k not in self.module_names]
        for module_name in to_delete:
            del sys.modules[module_name]


class PathManager:
    def __init__(self, file_path):
        self.original_path = None
        self.dir_name = os.path.dirname(file_path)

    def __enter__(self):
        self.original_path = sys.path[:]
        sys.path.append(self.dir_name)
        print("Sys path inside", sys.path)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        sys.path = self.original_path
        return None
