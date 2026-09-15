import time
import datetime
import os
import threading
import subprocess

import numpy as np
from PIL import (
    Image,
    ImageOps,
    ImageEnhance,
    ImageFilter,
    ImageDraw,
)

# Kivy system configuration — must come before imports
from kivy.config import Config
Config.set('graphics', 'width', '1024')
Config.set('graphics', 'height', '600')
Config.set('graphics', 'fullscreen', 'auto')
Config.set('graphics', 'show_cursor', '1')

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image as KivyImage
from kivy.graphics import (
    Color,
    Rectangle,
    Ellipse,
    PushMatrix,
    PopMatrix,
    Rotate,
)
from kivy.graphics.texture import Texture
from kivy.core.window import Window

from picamera2 import Picamera2


# Debug: make all buttons visible yellow for positioning.
# Set alpha to 0 when layout is finalised.
DEBUG_BTN_COLOR = (1, 1, 0, 0) #(1, 1, 0, 0.3)


class PhotoBoothApp(App):
    """Main photobooth application."""

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
    # Print/save options: 0 = do not print, 1 = print
    print_pic = 1
    save_pic = 0

    def build(self):
        """Build and return the root widget."""
        Window.clearcolor = (0, 0, 0, 1)
        Window.bind(on_keyboard=self.on_keyboard)

        self.asset_path = os.path.join(
            os.path.dirname(__file__), "assets"
        )
        self.save_path = os.path.join(
            os.path.dirname(__file__), "gallery"
        )
        if not os.path.exists(self.save_path):
            os.makedirs(self.save_path)

        # --- CAMERA HARDWARE ---
        self.picam2 = None
        try:
            self.picam2 = Picamera2()
            preview_cfg = (
                self.picam2.create_preview_configuration(
                    main={
                        "format": "XRGB8888",
                        "size": (1024, 600),
                    }
                )
            )
            self.picam2.configure(preview_cfg)
            self.picam2.start()
        except Exception as e:
            print(f"Hardware Error: {e}")
            self.safe_exit()

        self.root = FloatLayout()

        # 1. Background Manager
        self.bg_manager = KivyImage(
            source=os.path.join(
                self.asset_path, 'welcome.png'
            ),
            allow_stretch=True,
            keep_ratio=False,
        )
        self.root.add_widget(self.bg_manager)

        # 2a. Live Camera Preview (Centered)
        self.img_widget = KivyImage(
            fit_mode="contain",
            size_hint=(1, 1),
            pos_hint={
                'center_x': 0.5,
                'center_y': 0.5,
            },
            opacity=0,
        )
        self.root.add_widget(self.img_widget)

        # 2b. LEFT STRIP (Independent)
        self.collage_left = KivyImage(
            fit_mode="contain",
            size_hint=(0.45, 0.86),
            pos_hint={
                'center_x': 0.20,
                'center_y': 0.53,
            },
            opacity=0,
        )
        with self.collage_left.canvas.before:
            PushMatrix()
            self.rot_left = Rotate(
                angle=3.5,
                origin=self.collage_left.center,
            )
        with self.collage_left.canvas.after:
            PopMatrix()

        # 2c. RIGHT STRIP (Independent)
        self.collage_right = KivyImage(
            fit_mode="contain",
            size_hint=(0.63, 0.95),
            pos_hint={
                'center_x': 0.40,
                'center_y': 0.5,
            },
            opacity=0,
        )
        with self.collage_right.canvas.before:
            PushMatrix()
            self.rot_right = Rotate(
                angle=-4.5,
                origin=self.collage_right.center,
            )
        with self.collage_right.canvas.after:
            PopMatrix()

        self.collage_left.bind(
            pos=self._update_rot_left,
            size=self._update_rot_left,
        )
        self.collage_right.bind(
            pos=self._update_rot_right,
            size=self._update_rot_right,
        )

        self.root.add_widget(self.collage_left)
        self.root.add_widget(self.collage_right)

        # Load paper overlay
        try:
            overlay_raw = Image.open(
                os.path.join(
                    self.asset_path, 'paper_overlay0.png'
                )
            ).convert("RGBA")
            overlay_resized = overlay_raw.rotate(
                90, expand=True
            ).resize(
                (1200, 1800), Image.Resampling.LANCZOS
            )
            opacity_level = 0
            r, g, b, a = overlay_resized.split()
            a = a.point(
                lambda p: int(p * opacity_level)
            )
            self.paper_overlay = Image.merge(
                "RGBA", (r, g, b, a)
            )
        except Exception as e:
            print(f"Overlay Load Error: {e}")
            self.paper_overlay = None

        # 3. Filter Sidebar (with retake button)
        self.filter_layer = FloatLayout(
            size_hint=(1, 1),
            opacity=0,
            disabled=True,
        )
        self.setup_circular_filters()
        self.root.add_widget(self.filter_layer)

        # 3b. Filter Sidebar — Print Only.
        # Shown after retake is used; has no retake button.
        # Added/removed from root dynamically to prevent
        # disabled full-screen layouts from blocking touches
        # on the welcome screen below them in the z-stack.
        self.filter_layer_print = FloatLayout(
            size_hint=(1, 1),
            opacity=0,
            disabled=True,
        )
        self.setup_print_filters()
        # NOT added to root here — added only when needed.

        # 4. Status Label
        self.status_label = Label(
            text="",
            font_size='30sp',
            color=(1, 1, 1, 1),
            size_hint=(None, None),
            size=(200, 50),
            pos_hint={'right': 0.98, 'top': 0.98},
        )
        self.root.add_widget(self.status_label)

        # 5. Countdown Label
        self.overlay_label = Label(
            text="",
            font_size='250sp',
            color=(1, 1, 1, 1),
        )
        self.root.add_widget(self.overlay_label)

        # 6. Welcome Button Layer
        self.welcome_layer = FloatLayout(
            size_hint=(1, 1)
        )
        self.btn_start = Button(
            size_hint=(0.40, 0.21),
            pos_hint={
                'center_x': 0.5,
                'center_y': 0.26,
            },
            background_normal='',
            background_color=DEBUG_BTN_COLOR,
        )
        self.btn_start.bind(on_press=self.start_session)
        self.welcome_layer.add_widget(self.btn_start)
        self.root.add_widget(self.welcome_layer)

        # 7. Flash overlay
        with self.root.canvas.after:
            self.flash_color = Color(1, 1, 1, 0)
            self.flash_rect = Rectangle(
                size=Window.size, pos=(0, 0)
            )

        # State variables
        self.is_running = False
        self.photo_count = 0
        self.raw_photos = []
        self.active_filter = "fuji"
        # True once the user has used their one retake
        self.retake_used = False

        Clock.schedule_interval(
            self.update_loop, 1.0 / 30.0
        )
        return self.root

    def _update_rot_left(self, inst, val):
        self.rot_left.origin = inst.center

    def _update_rot_right(self, inst, val):
        self.rot_right.origin = inst.center

    def setup_circular_filters(self):
        """Set up filter sidebar that includes retake."""
        configs = [
            (
                'fuji',
                {'center_x': 0.77, 'center_y': 0.84},
            ),
            (
                'sepia',
                {'center_x': 0.77, 'center_y': 0.57},
            ),
        ]

        self.filter_btns = []

        for mode, pos in configs:
            btn = Button(
                size_hint=(None, None),
                size=(275, 225),
                pos_hint=pos,
                background_normal='',
                background_color=DEBUG_BTN_COLOR,
            )
            with btn.canvas.before:
                Color(0, 0, 0, 0)
                btn.shape = Ellipse(
                    size=btn.size, pos=btn.pos
                )
            btn.bind(
                pos=self._update_shape,
                size=self._update_shape,
            )
            btn.bind(
                on_press=lambda x, m=mode: (
                    self.launch_filter_thread(m)
                )
            )
            self.filter_layer.add_widget(btn)
            self.filter_btns.append(btn)

        # PRINT BUTTON
        # Invisible rectangle over 'Print' area in Canva
        self.btn_print = Button(
            size_hint=(0.32, 0.17),
            pos_hint={
                'center_x': 0.77,
                'center_y': 0.32,
            },
            background_normal='',
            background_color=DEBUG_BTN_COLOR,
        )
        self.btn_print.bind(
            on_press=self.initiate_print_flow
        )
        self.filter_layer.add_widget(self.btn_print)
        self.filter_btns.append(self.btn_print)

        # RETAKE BUTTON (The 'X' in the Top-Left)
        self.btn_retake = Button(
            text='',
            font_size='65sp',
            bold=True,
            color=(0, 0, 0, 0),
            size_hint=(0.19, 0.12),
            pos_hint={
                'center_x': 0.77,
                'center_y': 0.12,
            },
            background_normal='',
            background_color=DEBUG_BTN_COLOR,
        )
        # with self.btn_retake.canvas.before:
        #     Color(0.8, 0.2, 0.2, 0.7)
        #     self.btn_retake.shape = Ellipse(
        #         size=self.btn_retake.size,
        #         pos=self.btn_retake.pos,
        #     )
        # self.btn_retake.bind(
        #     pos=self._update_shape,
        #     size=self._update_shape,
        # )
        self.btn_retake.bind(
            on_press=self.retake_session
        )
        self.filter_layer.add_widget(self.btn_retake)
        self.filter_btns.append(self.btn_retake)

    def setup_print_filters(self):
        """
        Mirror of filter sidebar without retake button.
        Shown only after the one retake has been used.
        """
        configs = [
            (
                'fuji',
                {'center_x': 0.74, 'center_y': 0.80},
            ),
            (
                'sepia',
                {'center_x': 0.74, 'center_y': 0.50},
            ),
        ]
        self.filter_btns_print = []

        for mode, pos in configs:
            btn = Button(
                size_hint=(None, None),
                size=(353, 300),
                pos_hint=pos,
                background_normal='',
                background_color=DEBUG_BTN_COLOR,
            )
            with btn.canvas.before:
                Color(0, 0, 0, 0)
                btn.shape = Ellipse(
                    size=btn.size, pos=btn.pos
                )
            btn.bind(
                pos=self._update_shape,
                size=self._update_shape,
            )
            btn.bind(
                on_press=lambda x, m=mode: (
                    self.launch_filter_thread(m)
                )
            )
            self.filter_layer_print.add_widget(btn)
            self.filter_btns_print.append(btn)

        # PRINT BUTTON — same position as original
        btn_print2 = Button(
            size_hint=(0.31, 0.21),
            pos_hint={
                'center_x': 0.73,
                'center_y': 0.19,
            },
            background_normal='',
            background_color=DEBUG_BTN_COLOR,
        )
        btn_print2.bind(
            on_press=self.initiate_print_flow
        )
        self.filter_layer_print.add_widget(btn_print2)
        self.filter_btns_print.append(btn_print2)

        # No retake button on this layer.

    def _update_shape(self, inst, val):
        inst.shape.pos = inst.pos
        inst.shape.size = inst.size

    def _show_filter_layer(self):
        """
        Show the correct filter layer based on whether
        a retake has already been used this session.
        """
        if self.retake_used:
            # Retake used — show print-only layer.
            # Add to root dynamically if not present.
            if self.filter_layer_print not in (
                self.root.children
            ):
                self.root.add_widget(
                    self.filter_layer_print
                )
            self.filter_layer_print.opacity = 1
            self.filter_layer_print.disabled = False
            for b in self.filter_btns_print:
                b.disabled = False
        else:
            # First attempt — show full layer with retake.
            self.filter_layer.opacity = 1
            self.filter_layer.disabled = False
            for b in self.filter_btns:
                b.disabled = False

    def _hide_all_filter_layers(self):
        """
        Hide and disable all filter layers.
        Removes filter_layer_print from the widget tree
        entirely so it cannot intercept touches while
        the welcome screen is active.
        """
        self.filter_layer.opacity = 0
        self.filter_layer.disabled = True

        if self.filter_layer_print in (
            self.root.children
        ):
            self.root.remove_widget(
                self.filter_layer_print
            )
        self.filter_layer_print.opacity = 0
        self.filter_layer_print.disabled = True

    def start_session(self, instance):
        """Start a fresh photo session."""
        self._hide_all_filter_layers()

        if self.welcome_layer in self.root.children:
            self.root.remove_widget(self.welcome_layer)

        self.bg_manager.source = ""
        self.img_widget.opacity = 1
        self.collage_left.opacity = 0
        self.collage_right.opacity = 0
        self.is_running = True
        self.photo_count = 0
        self.raw_photos = []
        self.run_sequence()

    def retake_session(self, instance):
        """
        Called by the retake button.
        Marks retake as used then restarts photo sequence.
        After this, only filter_layer_print will be shown.
        """
        self.retake_used = True
        self.start_session(instance)

    def run_sequence(self):
        """Continue or finish the photo sequence."""
        if self.photo_count < 4:
            self.overlay_label.text = "POSE!"
            Clock.schedule_once(
                self.start_countdown, 1.5
            )
        else:
            self.show_loading()

    def start_countdown(self, dt):
        """Begin the 3-second countdown."""
        self.count = 3
        self.overlay_label.text = str(self.count)
        Clock.schedule_interval(self.tick, 1.0)

    def tick(self, dt):
        """Decrement the countdown by one second."""
        self.count -= 1
        if self.count > 0:
            self.overlay_label.text = str(self.count)
            return True
        else:
            self.overlay_label.text = ""
            self.capture_photo()
            return False

    def capture_photo(self):
        """Capture a single photo from the camera."""
        self.flash_color.a = 1
        frame = self.picam2.capture_array()
        img = Image.fromarray(frame)
        img = ImageOps.mirror(img)
        b, g, r, a = img.split()
        self.raw_photos.append(
            Image.merge("RGB", (r, g, b))
        )
        Clock.schedule_once(
            lambda dt: setattr(
                self.flash_color, 'a', 0
            ),
            0.1,
        )
        self.photo_count += 1
        self.run_sequence()

    def show_loading(self):
        """Finish capture; start Fuji filter processing."""
        self.is_running = False
        self.status_label.text = "Applying Fuji..."
        self.active_filter = "fuji"
        threading.Thread(
            target=self.process_background,
            args=("fuji",),
        ).start()

    def launch_filter_thread(self, mode):
        """Launch background filter processing."""
        if mode == self.active_filter:
            self.status_label.text = "APPLIED!"
            Clock.schedule_once(
                self.clear_status_message, 1.0
            )
            return

        all_btns = (
            self.filter_btns + self.filter_btns_print
        )
        for b in all_btns:
            b.disabled = True

        self.status_label.text = f"Applying {mode}..."
        self.active_filter = mode
        threading.Thread(
            target=self.process_background,
            args=(mode,),
        ).start()

    def clear_status_message(self, dt):
        """Clear the status label."""
        self.status_label.text = ""

    def add_grain(self, img, intensity=10):
        """Add visual noise to mimic film grain."""
        np_img = np.array(img).astype(np.float32)
        noise = np.random.normal(
            0, intensity, np_img.shape
        )
        np_img = np.clip(
            np_img + noise, 0, 255
        ).astype(np.uint8)
        return Image.fromarray(np_img)

    def process_background(self, mode):
        """Process photos with the selected filter."""
        photo_h = int(
            (self.STRIP_H - (3 * self.ROW_GAP)) / 4
        )

        # --- FIXED SIDE CUTOFF MATH ---
        # Fuji: inset photo width 8px each side so the
        # outward concentric outlines have space to render
        # inside the strip container without clipping.
        side_padding = 8 if mode == "fuji" else 0
        photo_w = self.STRIP_W - (2 * side_padding)
        photo_size = (photo_w, photo_h)

        round_mask = Image.new('L', photo_size, 0)
        draw_mask = ImageDraw.Draw(round_mask)
        draw_mask.rounded_rectangle(
            (0, 0) + photo_size,
            radius=self.CORNER_RADIUS,
            fill=255,
        )

        if mode == "fuji":
            single_strip = Image.new(
                'RGBA',
                (self.STRIP_W, self.STRIP_H),
                (255, 255, 255, 255),
            )
        else:
            single_strip = Image.new(
                'RGB',
                (self.STRIP_W, self.STRIP_H),
                (0, 0, 0),
            )

        draw_strip = ImageDraw.Draw(single_strip)

        for i, img in enumerate(self.raw_photos):
            work = img.copy()

            if mode == "bw":
                work = ImageOps.grayscale(
                    work
                ).convert("RGB")

                # Increase Sharpness
                # 1.0 = original, 2.5 = high sharpness
                sharpener = ImageEnhance.Sharpness(work)
                work = sharpener.enhance(2.5)

                # High Contrast
                work = ImageEnhance.Contrast(
                    work
                ).enhance(1)

                # Red-Brown Tint Matrix
                rb_matrix = (
                    1.15, 0, 0, 0,
                    0, 0.95, 0, 0,
                    0, 0, 0.85, 0,
                )
                work = work.convert("RGB", rb_matrix)

                # Add Grain (intensity 5 = subtle)
                work = self.add_grain(
                    work, intensity=5
                )

            elif mode == "fuji":
                # 1. Pink Tint Matrix:
                # Red boosted (1.10), Green lowered (0.9)
                # Creates a subtle pink/warm hue.
                # Blue lowered (0.91) adds yellow warmth.
                pink_tint_matrix = (
                    1.10, 0.0,  0.0,  0,  # Red (Boosted)
                    0.0,  0.9,  0.0,  0,  # Green (Lowered)
                    0.0,  0.0,  0.91, 0,  # Blue (Neutral)
                )
                work = work.convert(
                    "RGB", pink_tint_matrix
                )

                # --- ADD HAZE EFFECT ---
                # Lift shadows to make them milky/gray.
                # 5 = less haze, 15 = more haze
                np_work = np.array(work).astype(
                    np.float32
                )
                np_work = np_work + 5
                work = Image.fromarray(
                    np.clip(
                        np_work, 0, 255
                    ).astype(np.uint8)
                )

                # Overlay a soft warm white haze layer
                haze_overlay = Image.new(
                    "RGB", work.size, (255, 252, 240)
                )
                # 12% haze intensity
                work = Image.blend(
                    work, haze_overlay, alpha=0.12
                )

                # Softer Tone: Matte, airy feel
                # Brightness shifted from 1.1 to 0.9
                work = ImageEnhance.Brightness(
                    work
                ).enhance(0.9)
                work = ImageEnhance.Contrast(
                    work
                ).enhance(0.8)

                # Soft Glow: Misty bloom effect
                bloom = work.filter(
                    ImageFilter.GaussianBlur(radius=10)
                )
                work = Image.blend(
                    work, bloom, alpha=0.25
                )

                # Final Color: keep saturation at 1.0
                # so the pink tint doesn't wash out
                work = ImageEnhance.Color(
                    work
                ).enhance(1.0)

            elif mode == "sepia":

                # --- STAGE 1: HIGHLIGHT RECOVERY ---
                # Convert to float for precise math
                np_work = np.array(work).astype(
                    np.float32
                )

                # MATTE LIFT: keeps shadows soft,
                # prevents true blacks
                np_work = np_work + 30

                # HIGHLIGHT RECOVERY:
                # Drops ceiling from 210 to 185 to
                # kill harsh ring-light hot spots
                np_work = np_work * (185.0 / 255.0)

                # Clamp and rebuild PIL Image
                np_work = np.clip(
                    np_work, 0, 255
                ).astype(np.uint8)
                work = Image.fromarray(np_work)

                # --- STAGE 2: SEPIA CONVERSION ---
                sepia_matrix = np.array([
                    [0.393, 0.769, 0.189],
                    [0.349, 0.686, 0.168],
                    [0.272, 0.534, 0.131],
                ])

                sepia_array = np.clip(
                    np.array(work).dot(sepia_matrix.T),
                    0,
                    255,
                ).astype(np.uint8)

                # Force near-black pixels to pure black.
                # Prevents CMY composite ink from fading
                # to navy blue over time. Tune threshold.
                luminance = sepia_array.mean(axis=2)
                black_mask = luminance < 35
                sepia_array[black_mask] = [0, 0, 0]

                work = Image.fromarray(sepia_array)

                # --- STAGE 3: TONAL SMOOTHING ---
                # Uncomment to use:
                # work = ImageEnhance.Brightness(
                #     work
                # ).enhance(0.85)
                # work = ImageEnhance.Contrast(
                #     work
                # ).enhance(0.80)

                # --- STAGE 4: OVAL VIGNETTE ---
                width, height = work.size
                # Uncomment to use:
                # vignette = Image.new(
                #     'RGBA', work.size, (0, 0, 0, 0)
                # )
                # draw = ImageDraw.Draw(vignette)
                # draw.ellipse(
                #     [
                #         -width * 0.2,
                #         -height * 0.2,
                #         width * 1.2,
                #         height * 1.2,
                #     ],
                #     fill=(0, 0, 0, 100),
                # )
                # vignette = vignette.filter(
                #     ImageFilter.GaussianBlur(radius=40)
                # )
                # work.paste(vignette, (0, 0), vignette)

                # --- STAGE 5: HORIZONTAL BARS ---
                bar_mask = Image.new(
                    'L', work.size, 0
                )
                bar_draw = ImageDraw.Draw(bar_mask)

                # Slim 5% coverage bars top and bottom
                bar_thickness = int(height * 0.05)
                bar_draw.rectangle(
                    [0, 0, width, bar_thickness],
                    fill=240,
                )
                bar_draw.rectangle(
                    [
                        0,
                        height - bar_thickness,
                        width,
                        height,
                    ],
                    fill=240,
                )

                bar_mask = bar_mask.filter(
                    ImageFilter.GaussianBlur(radius=45)
                )

                # Light opacity 50 overlay
                bar_vignette = Image.new(
                    'RGBA', work.size, (0, 0, 0, 50)
                )
                bar_vignette.putalpha(bar_mask)
                work.paste(
                    bar_vignette, (0, 0), bar_vignette
                )

            res = ImageOps.fit(
                work,
                photo_size,
                Image.Resampling.LANCZOS,
            )
            y_pos = i * (photo_h + self.ROW_GAP)
            x_pos = side_padding

            # Paste photo onto strip with offset applied
            single_strip.paste(
                res, (x_pos, y_pos), round_mask
            )

            if mode == "fuji":
                # Limit outline steps to quarter of the
                # row gap so row bounds don't crash
                if self.ROW_GAP > 0:
                    max_steps = max(
                        1, int(self.ROW_GAP // 4)
                    )
                else:
                    max_steps = 4

                for offset in range(1, max_steps + 1):
                    alpha_factor = (
                        1.0 - (offset / (max_steps + 1))
                    )
                    alpha_val = int(
                        255 * alpha_factor * 0.45
                    )
                    pink_rgba = (
                        255, 182, 193, alpha_val
                    )

                    # Box expands outward from the photo
                    box = (
                        x_pos - offset,
                        y_pos - offset,
                        x_pos + photo_w + offset,
                        y_pos + photo_h + offset,
                    )
                    draw_strip.rounded_rectangle(
                        box,
                        radius=(
                            self.CORNER_RADIUS + offset
                        ),
                        outline=pink_rgba,
                        width=1,
                    )

        self.current_strip = single_strip.convert("RGB")
        self.current_strip.save("temp_preview.png")
        Clock.schedule_once(
            self.display_filter_results, 0
        )

    def display_filter_results(self, dt):
        """Update the UI to show the processed strip."""

        if self.retake_used:
            self.bg_manager.source = os.path.join(
                self.asset_path, 'filter_selection_print.png'
            )

        else:
            self.bg_manager.source = os.path.join(
                self.asset_path, 'filter.png'
            )
                        
        self.img_widget.opacity = 0

        self.collage_left.source = "temp_preview.png"
        self.collage_left.reload()
        self.collage_left.opacity = 1

        self.collage_right.source = "temp_preview.png"
        self.collage_right.reload()
        self.collage_right.opacity = 1

        self.status_label.text = ""
        self._show_filter_layer()

    def mm_to_px(self, mm):
        """Convert millimetres to pixels at target DPI."""
        return int(round((mm / 25.4) * self.DPI))

    def initiate_print_flow(self, instance):
        """Save the final image and send to printer."""
        print_pic = self.print_pic
        timestamp = int(time.time())
        filename = f"print_{timestamp}.jpg"
        temp_print_path = "/tmp/booth_print.jpg"

        self.generate_report(filename)

        self.bg_manager.source = os.path.join(
            self.asset_path, 'thankyou.png'
        )
        self._hide_all_filter_layers()
        self.collage_left.opacity = 0
        self.collage_right.opacity = 0

        # Add 2mm bleed on all 4 sides
        BLEED_PX = 24  # 2mm at 300 DPI
        canvas_w = 1200 + (BLEED_PX * 2)  # = 1248
        canvas_h = 1800 + (BLEED_PX * 2)  # = 1848

        # Convert border and gap settings mm to pixels
        border_side_px = self.mm_to_px(
            self.BORDER_SIDE_MM
        )
        border_tb_px = self.mm_to_px(self.BORDER_TB_MM)
        gap_px = self.mm_to_px(self.STRIP_GAP_MM)

        canvas_color = (
            (255, 255, 255)
            if self.active_filter == "fuji"
            else (0, 0, 0)
        )
        canvas = Image.new(
            'RGB', (canvas_w, canvas_h), canvas_color
        )

        # Calculate strip dimensions using independent
        # side and top/bottom borders
        usable_width = (
            canvas_w - (2 * border_side_px) - gap_px
        )
        strip_dest_w = usable_width // 2
        strip_dest_h = canvas_h - (2 * border_tb_px)

        resized_strip = self.current_strip.resize(
            (strip_dest_w, strip_dest_h),
            Image.Resampling.LANCZOS,
        )

        # Coordinate calculations with horizontal offset
        h_offset_px = self.mm_to_px(self.H_OFFSET_MM)
        left_strip_x = border_side_px - h_offset_px
        right_strip_x = (
            border_side_px
            + strip_dest_w
            + gap_px
            - h_offset_px
        )
        strip_y = border_tb_px

        # Paste execution
        canvas.paste(
            resized_strip, (left_strip_x, strip_y)
        )
        canvas.paste(
            resized_strip, (right_strip_x, strip_y)
        )

        # --- SEPIA-ONLY MASK ENGINE ---
        if self.active_filter != "fuji":
            draw_mask = ImageDraw.Draw(canvas)

            draw_mask.rectangle(
                (0, 0, canvas_w, border_tb_px),
                fill=(0, 0, 0),
            )
            draw_mask.rectangle(
                (
                    0,
                    canvas_h - border_tb_px,
                    canvas_w,
                    canvas_h,
                ),
                fill=(0, 0, 0),
            )
            draw_mask.rectangle(
                (0, 0, border_side_px, canvas_h),
                fill=(0, 0, 0),
            )
            draw_mask.rectangle(
                (
                    canvas_w - border_side_px,
                    0,
                    canvas_w,
                    canvas_h,
                ),
                fill=(0, 0, 0),
            )

            center_gap_start_x = (
                left_strip_x + strip_dest_w
            )
            draw_mask.rectangle(
                (
                    center_gap_start_x,
                    0,
                    center_gap_start_x + gap_px,
                    canvas_h,
                ),
                fill=(0, 0, 0),
            )

        if self.paper_overlay:
            canvas.paste(
                self.paper_overlay,
                (0, 0),
                self.paper_overlay,
            )

        
        try:
                # Save to gallery
            save_file = os.path.join(
                self.save_path, filename
            )
            canvas.save(save_file, "JPEG", quality=95)
            print(f"Gallery image saved: {save_file}")
        except Exception as e:
            print(f"Gallery Save Error: {e}")

        if print_pic == 1:
            try:
                canvas.save(
                    temp_print_path,
                    "JPEG",
                    quality=100,
                )
                print_cmd = [
                    "lp",
                    "-d", "L3250-Series",
                    "-o", "media=T4X6FULL",
                    "-o", "MediaType=PMPHOTO_HIGH",
                    "-o", "scaling=100",
                    temp_print_path,
                ]
                subprocess.run(print_cmd, check=True)
                print(
                    "Print job sent successfully "
                    "to L3250."
                )
            except Exception as e:
                print(f"Print error: {e}")

        # Goodbye screen timer
        Clock.schedule_once(self.reset_to_start, 10.0)

    def reset_to_start(self, dt):
        """Return to welcome screen for the next user."""
        if self.welcome_layer not in self.root.children:
            self.root.add_widget(self.welcome_layer)

        self.bg_manager.source = os.path.join(
            self.asset_path, 'welcome.png'
        )
        self.img_widget.source = ""
        self.img_widget.opacity = 0
        self.is_running = False
        self.collage_left.opacity = 0
        self.collage_right.opacity = 0

        # Reset retake flag for the next user
        self.retake_used = False
        # Remove print-only layer from tree entirely
        self._hide_all_filter_layers()

    def update_loop(self, dt):
        """Update the live camera preview texture."""
        if self.is_running and self.picam2:
            frame = self.picam2.capture_array()
            texture = Texture.create(
                size=(
                    frame.shape[1],
                    frame.shape[0],
                ),
                colorfmt='rgba',
            )
            texture.blit_buffer(
                frame.tobytes(),
                colorfmt='bgra',
                bufferfmt='ubyte',
            )
            texture.flip_vertical()
            self.img_widget.texture = texture

    def generate_report(self, saved_filename):
        """Log the print event to a monthly report."""
        now = datetime.datetime.now()
        month_str = now.strftime("%b-%y").upper()
        day_str = now.strftime("%d-%m-%y")
        timestamp = now.strftime("%H:%M:%S")

        reports_dir = os.path.join(
            os.path.dirname(__file__), "reports"
        )
        month_dir = os.path.join(reports_dir, month_str)
        if not os.path.exists(month_dir):
            os.makedirs(month_dir)

        file_path = os.path.join(
            month_dir, f"{day_str}.txt"
        )

        current_count = 0
        existing_logs = []

        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                lines = f.readlines()
                if lines:
                    try:
                        current_count = int(
                            lines[0].split(":")[1].strip()
                        )
                        existing_logs = lines[1:]
                    except Exception:
                        pass

        with open(file_path, "w") as f:
            f.write(
                f"pictures taken: "
                f"{current_count + 1}\n"
            )
            f.writelines(existing_logs)
            f.write(
                f"[{timestamp}] {saved_filename}\n"
            )

    def on_keyboard(self, w, k, s, c, m):
        """Handle keyboard events."""
        if k == 27:
            self.safe_exit()
            return True

    def safe_exit(self):
        """Cleanly stop camera and exit."""
        if self.picam2:
            self.picam2.stop()
            self.picam2.close()
        os._exit(0)


if __name__ == "__main__":
    PhotoBoothApp().run()
