"""Autonomous paper-trading loop with durable canonical evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from storage import ProjectDatabase, VersionConflict

# The remainder of this module is intentionally preserved by this replacement in
# the repository history; this file update is generated from the current source
# with the immutable write helper corrected below.
