"""Reuse directory metadata within one collection run to reduce filesystem load."""

import stat


class MetadataCache:
    def __init__(self):
        self.source_parents = {}
        self.destination_directories = {}

    def source_file(self, path):
        """Resolve each source directory once, but inspect every file freshly."""
        parent = self.source_parents.get(path.parent)
        if parent is None:
            parent = path.parent.resolve(strict=True)
            self.source_parents[path.parent] = parent
        source = parent / path.name
        info = source.lstat()
        if stat.S_ISLNK(info.st_mode):
            source = source.resolve(strict=True)
            info = source.stat()
        return source, info

    def directory_stat(self, path):
        """Cache existing and absent destination directories for read-only checks."""
        if path not in self.destination_directories:
            try:
                info = path.lstat()
            except FileNotFoundError:
                info = None
            self.destination_directories[path] = info
        return self.destination_directories[path]
