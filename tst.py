
import shutil

def get_disk_info(disk: str) -> tuple:
    KB = 1024
    MB = 1024 * KB
    GB = 1024 * MB

    return (disk, shutil.disk_usage('C:').free / GB, shutil.disk_usage('C:').total / GB)





