"""Copy through a temporary destination file and publish without overwriting."""

import os
import shutil
import stat
import tempfile
from pathlib import Path


def existing_copy(destination, size):
    try:
        info = destination.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
        raise FileExistsError(
            f"destination is not a regular file of the expected size: {destination}"
        )
    return True


def copy_file(source, destination, size, source_info, *, on_stage=None):
    """Return True for a new copy, False for an existing size-verified file."""

    def report(stage, path):
        if on_stage is not None:
            on_stage(stage, path)

    report("checking destination", destination)
    if existing_copy(destination, size):
        return False
    temporary = None
    try:
        report("opening source", source)
        with source.open("rb") as input_stream:
            opened = os.fstat(input_stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                source_info.st_dev,
                source_info.st_ino,
                size,
                source_info.st_mtime_ns,
            ):
                raise ValueError("source changed before copying")
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=".c3s-copy-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                report("copying file", source)
                shutil.copyfileobj(input_stream, output, length=1024 * 1024)
                report("flushing copy", destination)
                output.flush()
                copied_size = os.fstat(output.fileno()).st_size
                if copied_size != size:
                    raise ValueError(
                        f"copied size does not match the catalog: expected={size} actual={copied_size}"
                    )
                after = os.fstat(input_stream.fileno())
                if (after.st_size, after.st_mtime_ns) != (size, opened.st_mtime_ns):
                    raise ValueError("source changed during copying")
                os.fchmod(output.fileno(), stat.S_IMODE(source_info.st_mode) & 0o777)
                os.fsync(output.fileno())
        report("publishing file", destination)
        os.utime(temporary, ns=(source_info.st_atime_ns, source_info.st_mtime_ns))
        try:
            # The temporary file is owned by this user on the destination filesystem;
            # this atomic publish does not hardlink the original source inode.
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            if not existing_copy(destination, size):
                raise
            return False
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
