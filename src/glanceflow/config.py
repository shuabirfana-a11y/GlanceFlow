"""Central configuration for the Stage 1 safety gate."""

DEFAULT_TIMEZONE = "Asia/Shanghai"
CORE_EVIDENCE_MIN_CONFIDENCE = 0.75
NOTICE_PACKAGE_ID_PATTERN = r"^GF-PKG-\d{4}$"
MAX_USER_PROMPT_LENGTH = 80

# Stage 2 engineering starting values. They are conservative defaults for the
# synthetic baseline, not experimentally optimized production thresholds.
SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
QUALITY_MIN_IMAGE_WIDTH = 640
QUALITY_MIN_IMAGE_HEIGHT = 400
QUALITY_MIN_LAPLACIAN_VARIANCE = 80.0
QUALITY_BLACK_MEAN_MAX = 5.0
QUALITY_BLACK_STD_MAX = 5.0
OCR_MIN_TEXT_CHARACTERS = 2
OCR_PROVIDER_NAME = "rapidocr-onnxruntime"
OCR_PROVIDER_VERSION = "1.2.3"

# Stage 3 engineering rules. End times are not extracted from posters.
DEFAULT_MAIN_EVENT_DURATION_MINUTES = 60
DEFAULT_DEADLINE_EVENT_DURATION_MINUTES = 15
DUPLICATE_TIME_TOLERANCE_MINUTES = 5
CALENDAR_PREFLIGHT_LOOKAROUND_HOURS = 24

