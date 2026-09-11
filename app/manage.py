"""Django entry point; IMP-01 / NFR-06."""

import os
import sys

from django.core.management import execute_from_command_line

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    execute_from_command_line(sys.argv)
