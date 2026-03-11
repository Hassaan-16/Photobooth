import time
import os
import sys
import numpy as np
from PIL import Image, ImageOps, ImageEnhance

# 1. Kivy System Configuration (Waveshare 7-inch)
from kivy.config import Config

Config.set('graphics', 'width', '1024')
Config.set('graphics', 'height', '600')
Config.set('graphics', 'fullscreen', 'auto')
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'show_cursor', '1') 

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image as KivyImage
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.graphics import Color, Rectangle
from kivy.core.window import Window
from kivy.utils import get_color_from_hex

from picamera2 import Picamera2

class PhotoBoothApp(App):

    def build(self):
        Window.clearcolor = (0, 0, 0, 1)
        Window.bind(on_keyboard=self.on_keyboard)

        # --- FONT SETTINGS ---
        possible_paths = [
            "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/times.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
        ]

        self.ui_font = "Roboto" 

        for path in possible_paths:
            if os.path.exists(path):
                self.ui_font = path
                break

        self.save_path = "./gallery"
        if not os.path.exists(self.save_path): 
            os.makedirs(self.save_path)

        # --- CAMERA HARDWARE ---
        self.picam2 = None

        try:
            self.picam2 = Picamera2()
            self.picam2.configure(self.picam2.create_preview_configuration(
                main={"format": "XRGB8888", "size": (800, 600)}
            ))
            self.picam2.start()

        except Exception as e:
            print(f"Hardware Error: {e}"); self.safe_exit()

        # --- ROOT UI ---
        self.root = FloatLayout()
        
        # 1. Camera Preview
        self.img_widget = KivyImage(fit_mode="contain") 
        self.root.add_widget(self.img_widget)

        # 2. Welcome Box
        self.welcome_box = BoxLayout(orientation='vertical', size_hint=(0.9, 0.4),
                                    pos_hint={'center_x': 0.5, 'center_y': 0.70})
        
        self.lbl_main = Label(text="Welcome to XYZ Photobooth", font_size='100sp', 
                              font_name=self.ui_font, color=(1,1,1,1))
        
        self.lbl_sub = Label(text="Press start to create memories", font_size='65sp', 
                             font_name=self.ui_font, color=(0.8,0.8,0.8,1))
        
        self.welcome_box.add_widget(self.lbl_main)
        self.welcome_box.add_widget(self.lbl_sub)
        self.root.add_widget(self.welcome_box)

        # 3. Start Button
        self.btn_start = Button(text="START", size_hint=(0.3, 0.2),
                                pos_hint={'center_x': 0.5, 'center_y': 0.35},
                                background_normal='', background_color=(1, 1, 1, 1),
                                color=(0, 0, 0, 1), font_size='50sp', 
                                font_name=self.ui_font, bold=True)
        
        self.btn_start.bind(on_press=self.start_session)
        self.root.add_widget(self.btn_start)

        # 4. Filter Sidebar (Disabled and Invisible at start)
        self.controls = BoxLayout(orientation='vertical', size_hint=(0.25, 0.8),
                                 pos_hint={'right': 0.98, 'center_y': 0.5},
                                 spacing=15, opacity=0, disabled=True)
        self.setup_controls()
        self.root.add_widget(self.controls)

        # 5. Countdown Label
        self.overlay_label = Label(text="", font_size='250sp', color=(1,1,1,1))
        self.root.add_widget(self.overlay_label)

        # 6. Topmost Flash & Ending Layer
        self.flash_layer = FloatLayout(size_hint=(1,1))
        with self.flash_layer.canvas:
            self.flash_color = Color(1, 1, 1, 0)
            self.flash_rect = Rectangle(size=Window.size, pos=(0,0))
        
        self.collect_label = Label(text="Collect Print from\noutside the booth", 
                                   font_size='125sp', font_name=self.ui_font,
                                   color=(0, 0, 0, 1), halign='center', opacity=0)
        
        self.flash_layer.add_widget(self.collect_label)
        self.root.add_widget(self.flash_layer)

        Window.bind(size=self._update_flash_rect)

        # State Variables
        self.is_running = True
        self.photo_count = 0
        self.raw_photos = []
        self.current_strip = None
        
        Clock.schedule_interval(self.update_loop, 1.0 / 30.0)
        return self.root

    # --- SYSTEM METHODS ---
    def _update_flash_rect(self, instance, value):
        
        self.flash_rect.size = value
        self.flash_rect.pos = (0, 0)

    def on_keyboard(self, window, key, scancode, codepoint, modifier):
        if key == 27: self.safe_exit(); return True
        return False

    def update_loop(self, dt):
        
        if self.is_running and self.picam2:
            frame = self.picam2.capture_array()
            h, w, _ = frame.shape
            texture = Texture.create(size=(w, h), colorfmt='rgba')
            texture.blit_buffer(frame.tobytes(), colorfmt='bgra', bufferfmt='ubyte')
            texture.flip_vertical()
            self.img_widget.texture = texture

    def safe_exit(self):
        if self.picam2: self.picam2.stop(); self.picam2.close()
        os._exit(0)

    # --- PHOTO LOGIC ---
    def apply_filter(self, img, mode):
        
        work_img = img.copy()
        
        if mode == "fuji":
            r, g, b = work_img.split()
            work_img = Image.merge("RGB", (r.point(lambda i: i * 1.1), g.point(lambda i: i * 1.05), b.point(lambda i: i * 0.9)))
        
        elif mode == "bw":
            work_img = ImageOps.grayscale(work_img).convert("RGB")
        
        elif mode == "sepia":
            sepia_matrix = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
            arr = np.array(work_img); sepia_arr = np.clip(arr.dot(sepia_matrix.T), 0, 255).astype(np.uint8)
            work_img = Image.fromarray(sepia_arr)
        
        np_img = np.array(work_img).astype(np.float32)
        noise = np.random.normal(0, 8, np_img.shape)
        
        return Image.fromarray(np.clip(np_img + noise, 0, 255).astype(np.uint8))

    def setup_controls(self):
        
        self.controls.clear_widgets()
        self.controls.add_widget(Label(text="Filter", font_name=self.ui_font, bold=True, font_size='30sp', size_hint_y=0.2))
        
        for label, mode in [("Retro Fuji", "fuji"), ("Black n White", "bw"), ("Sepia", "sepia")]:
            btn = Button(text=label, font_name=self.ui_font, font_size='24sp', on_press=lambda x, m=mode: self.generate_collage(m))
            self.controls.add_widget(btn)
        
        btn_save = Button(text="SAVE & FINISH", font_name=self.ui_font, font_size='28sp', background_color=get_color_from_hex('#2980b9'), bold=True)
        btn_save.bind(on_press=self.show_collection_screen)
        self.controls.add_widget(btn_save)

    def start_session(self, instance):
        self.btn_start.disabled = True
        self.btn_start.opacity = 0
        self.welcome_box.opacity = 0
        self.raw_photos = []
        self.photo_count = 0
        self.run_sequence()

    def run_sequence(self):
        
        if self.photo_count == 0: self.start_countdown(5)
        
        elif self.photo_count < 4:
            self.overlay_label.text = "Pose Again"; self.overlay_label.font_name = self.ui_font; self.overlay_label.font_size = '100sp'
            Clock.schedule_once(lambda dt: self.start_countdown(3), 2.0)
        
        else: self.show_loading()

    def start_countdown(self, seconds):
        
        self.overlay_label.font_name = "Roboto"; self.overlay_label.font_size = '250sp'
        self.count = seconds; self.overlay_label.text = str(self.count); self.count -= 1
        Clock.schedule_interval(self.tick_countdown, 1.0)

    def tick_countdown(self, dt):
        
        if self.count > 0: self.overlay_label.text = str(self.count); self.count -= 1; return True
        
        else: self.overlay_label.text = ""; self.trigger_flash_and_capture(); return False

    def trigger_flash_and_capture(self):
        self.flash_color.a = 1
        frame = self.picam2.capture_array(); img = Image.fromarray(frame); b, g, r, a = img.split()
        self.raw_photos.append(Image.merge("RGB", (r, g, b)))
        Clock.schedule_once(lambda dt: setattr(self.flash_color, 'a', 0), 0.125)
        self.photo_count += 1
        Clock.schedule_once(lambda dt: self.run_sequence(), 0.5)

    def show_loading(self):
        self.is_running = False; self.overlay_label.font_name = self.ui_font; self.overlay_label.font_size = '80sp'; self.overlay_label.text = "GENERATING..."
        Clock.schedule_once(lambda dt: self.generate_collage("fuji"), 0.5)

    def generate_collage(self, filter_type):
        strip_w, strip_h = 600, 1800; photo_h = 450
        strip = Image.new('RGB', (strip_w, strip_h), (255, 255, 255))
        
        for i, img in enumerate(self.raw_photos):
            processed = ImageOps.fit(self.apply_filter(img, filter_type), (strip_w, photo_h), Image.Resampling.LANCZOS)
            strip.paste(processed, (0, i * photo_h))
        
        self.current_strip = strip
        strip.save("temp_preview.jpg")
        self.img_widget.source = "temp_preview.jpg"; self.img_widget.reload(); self.img_widget.pos_hint = {'center_x': 0.4, 'center_y': 0.5}
        
        # ENABLE CONTROLS ONLY NOW
        self.controls.opacity = 1
        self.controls.disabled = False
        self.overlay_label.text = ""

    def show_collection_screen(self, instance):

        canvas = Image.new('RGB', (1200, 1800), (255, 255, 255))
        canvas.paste(self.current_strip, (0, 0)); canvas.paste(self.current_strip, (600, 0))
        canvas.save(os.path.join(self.save_path, f"booth_{int(time.time())}.jpg"), quality=95)
        
        self.flash_color.a = 1; self.collect_label.opacity = 1
        
        # DISABLE CONTROLS AGAIN
        self.controls.opacity = 0
        self.controls.disabled = True
        
        Clock.schedule_once(self.reset_to_start, 20.0)

    def reset_to_start(self, dt):
        self.flash_color.a = 0; self.collect_label.opacity = 0
        self.img_widget.source = ""; self.img_widget.pos_hint = {'center_x': 0.5, 'center_y': 0.5}
        self.welcome_box.opacity = 1; self.btn_start.opacity = 1; self.btn_start.disabled = False
        self.is_running = True

if __name__ == "__main__":
    PhotoBoothApp().run()