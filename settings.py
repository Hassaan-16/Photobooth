"""
settings.py — All global, adjustable settings for the photobooth app.

Everything here is imported into main.py. Change values in this file
only — you should not need to touch main.py or filters.py to tweak
behaviour.
"""

# ==================================================
# CAMERA SETTINGS
# ==================================================

# Mirror the captured photo horizontally.
# False = original camera orientation (not mirrored).
# True  = flipped, like a "selfie" mirror preview.
MIRROR_CAMERA = False

# ==================================================
# COUNTDOWN TIMER FONT
# ==================================================

# Path to the font file used for the on-screen countdown label
# (the big "3, 2, 1" text). Point this at a Didot .ttf/.otf file.
# See the setup instructions for how to install Didot on the Pi.
COUNTDOWN_FONT_PATH = "assets/fonts/Didot.ttf"

# ==================================================
# BACKGROUND IMAGES
# ==================================================
# Filenames only, relative to the assets/ folder. Swap in a
# different image by changing the filename here — no code edits
# needed in main.py.

# Idle / welcome screen
BG_WELCOME = "welcome.png"
# Filter selection screen — shown on first attempt (retake available)
BG_FILTER_SELECT = "filter.png"
# Filter selection screen — shown after the retake has been used
BG_FILTER_SELECT_NO_RETAKE = "filter_selection_print.png"
# Thank-you / printing screen
BG_THANKYOU = "thankyou.png"

# ==================================================
# OVERLAY SETTINGS
# ==================================================

# Turn the paper/texture overlay on the final printed strip on or off.
OVERLAY_ENABLED = False

# Filename of the overlay image, relative to the assets/ folder.
OVERLAY_PATH = "paper_overlay0.png"

# Overlay strength when OVERLAY_ENABLED is True.
# 0.0 = fully invisible, 1.0 = fully opaque overlay.
OVERLAY_OPACITY = 0.35

# --- GLOBAL ADJUSTABLE SETTINGS ---

# Vertical gap between stacked photos (pixels)
ROW_GAP = 15
# Rounded corner factor for individual photos
CORNER_RADIUS = 10
# Total individual strip canvas width
STRIP_W = 600
# Total strip height
STRIP_H = 1800

# BORDER & GAP CONTROLS (millimetres)
# Left and right borders
BORDER_SIDE_MM = 3.0
# Top and bottom — larger to survive overspray
BORDER_TB_MM = 6.0

# Horizontal shift to compensate for uneven
# printer overspray.
# left --> " - "   right --> " + "
H_OFFSET_MM = 0

# 2mm solid black gap between the two strips
STRIP_GAP_MM = 2.0
# Standard print DPI for 4x6 (1200x1800 px)
DPI = 300

# ----------------------------------
# Print/save options: 0 = do not, 1 = do
PRINT_PIC = 1
# Default: do NOT save a copy of the final print to the gallery folder.
SAVE_PIC = 0

# Seconds to show the "thank you" / goodbye screen before the app
# resets back to the welcome screen for the next user.
GOODBYE_SCREEN_SECONDS = 30.0
