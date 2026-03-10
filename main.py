import time
import os
import sys
import numpy as np
from PIL import Image, ImageOps, ImageEnhance

# Kivy Configuration
from kivy.config import Config
Config.set('graphics', 'width', '1024')
Config.set('graphics', 'height', '600')
Config.set('graphics', 'fullscreen', 'auto') # Forces Fullscreen
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'show_cursor', '0') # Hides mouse for clean look

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

        # Font Search Logic
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

        # Camera Setup
        self.picam2 = None
        try:
            self.picam2 = Picamera2()
            self.picam2.configure(self.picam2.create_preview_configuration(
                main={"format": "XRGB8888", "size": (800, 600)}
            ))
            self.picam2.start()
        except Exception as e:
            print(f"Hardware Error: {e}")
            self.safe_exit()

        self.root = FloatLayout()
        
        # 1. Camera Preview
        self.img_widget = KivyImage(fit_mode="contain") 
        self.root.add_widget(self.img_widget)

        # 2. Welcome UI (Increased font sizes)
        self.welcome_box = BoxLayout(orientation='vertical', size_hint=(0.9, 0.4),
                                    pos_hint={'center_x': 0.5, 'center_y': 0.70})
        
        self.lbl_main = Label(text="Welcome to XYZ Photobooth", font_size='65sp', 
                              font_name=self.ui_font, color=(1,1,1,1))
        self.lbl_sub = Label(text="Press start to create memories", font_size='35sp', 
                             font_name=self.ui_font, color=(0.8,0.8,0.8,1))
        
        self.welcome_box.add_widget(self.lbl_main)
        self.welcome_box.add_widget(self.lbl_sub)
        self.root.add_widget(self.welcome_box)

        # 3. Start Button (Bigger)
        self.btn_start = Button(text="START", size_hint=(0.3, 0.2),
                                pos_hint={'center_x': 0.5, 'center_y': 0.35},
                                background_normal='', 
                                background_color=(1, 1, 1, 1),
                                color=(0, 0, 0, 1),
                                font_size='50sp', font_name=self.ui_font, bold=True)
        self.btn_start.bind(on_press=self.start_session)
        self.root.add_widget(self.btn_start)

        # 4. Overlay Label (Countdown/Pose - Bigger)
        self.overlay_label = Label(text="", font_size='200sp', color=(1,1,1,1))
        self.root.add_widget(self.overlay_label)

        # 5. Filter Controls
        self.controls = BoxLayout(orientation='vertical', size_hint=(0.25, 0.8),
                                 pos_hint={'right': 0.98, 'center_y': 0.5},
                                 spacing=15, opacity=0)
        self.setup_controls()
        self.root.add_widget(self.controls)

        # 6. Flash Overlay - Fixed for Fullscreen Scaling
        with self.root.canvas.after:
            self.flash_color = Color(1, 1, 1, 0)
            self.flash_rect = Rectangle(size=Window.size, pos=(0,0))
        
        # Re-bind flash rectangle to window size changes
        Window.bind(size=self._update_flash_rect)

        self.is_running = True
        self.photo_count = 0
        self.raw_photos = []
        self.current_strip = None
        
        Clock.schedule_interval(self.update_loop, 1.0 / 30.0)
        return self.root

    def _update_flash_rect(self, instance, value):
        """Ensures the white flash always covers 100% of the window."""
        self.flash_rect.size = value
        self.flash_rect.pos = (0, 0)

    def on_keyboard(self, window, key, scancode, codepoint, modifier):
        if key == 27: # ESC
            self.safe_exit()
            return True
        return False

    def update_loop(self, dt):
        if self.is_running and self.picam2:
            frame = self.picam2.capture_array()
            h, w, _ = frame.shape
            texture = Texture.create(size=(w, h), colorfmt='rgba')
            texture.blit_buffer(frame.tobytes(), colorfmt='bgra', bufferfmt='ubyte')
            texture.flip_vertical()
            self.img_widget.texture = texture

    def add_grain(self, img, intensity=5):
        np_img = np.array(img).astype(np.float32)
        noise = np.random.normal(0, intensity, np_img.shape)
        np_img = np.clip(np_img + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(np_img)

    def apply_filter(self, img, mode):
        work_img = img.copy()
        if mode == "fuji":
            r, g, b = work_img.split()
            work_img = Image.merge("RGB", (r.point(lambda i: i * 1.1), g.point(lambda i: i * 1.05), b.point(lambda i: i * 0.9)))
            return self.add_grain(work_img, intensity=8)
        elif mode == "bw":
            work_img = ImageOps.grayscale(work_img).convert("RGB")
            enhancer = ImageEnhance.Contrast(work_img)
            work_img = enhancer.enhance(1.0)
            r, g, b = work_img.split()
            work_img = Image.merge("RGB", (r.point(lambda i: i * 1.15), g, b))
            return self.add_grain(work_img, intensity=15)
        elif mode == "sepia":
            sepia_matrix = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
            arr = np.array(work_img)
            sepia_arr = np.clip(arr.dot(sepia_matrix.T), 0, 255).astype(np.uint8)
            work_img = Image.fromarray(sepia_arr)
            return self.add_grain(work_img, intensity=8)
        return work_img

    def setup_controls(self):
        self.controls.clear_widgets()
        self.controls.add_widget(Label(text="Filter", font_name=self.ui_font, bold=True, font_size='30sp', size_hint_y=0.2))
        
        for label, mode in [("Retro Fuji", "fuji"), ("Black n White", "bw"), ("Sepia", "sepia")]:
            btn = Button(text=label, font_name=self.ui_font, font_size='24sp', on_press=lambda x, m=mode: self.generate_collage(m))
            self.controls.add_widget(btn)
        
        btn_save = Button(text="SAVE & FINISH", font_name=self.ui_font, font_size='28sp', background_color=get_color_from_hex('#2980b9'), bold=True)
        btn_save.bind(on_press=lambda x: self.save_to_gallery())
        self.controls.add_widget(btn_save)

    def start_session(self, instance):
        self.btn_start.disabled = True
        self.btn_start.opacity = 0
        self.welcome_box.opacity = 0
        self.raw_photos = []
        self.photo_count = 0
        self.run_sequence()

    def run_sequence(self):
        if self.photo_count == 0:
            self.start_countdown(5)
        elif self.photo_count < 4:
            self.overlay_label.text = "Pose Again"
            self.overlay_label.font_name = self.ui_font
            self.overlay_label.font_size = '100sp'
            Clock.schedule_once(lambda dt: self.start_countdown(3), 2.0)
        else:
            self.show_loading()

    def start_countdown(self, seconds):
        self.overlay_label.font_name = "Roboto" 
        self.overlay_label.font_size = '250sp'
        self.count = seconds
        self.overlay_label.text = str(self.count)
        self.count -= 1
        Clock.schedule_interval(self.tick_countdown, 1.0)

    def tick_countdown(self, dt):
        if self.count > 0:
            self.overlay_label.text = str(self.count)
            self.count -= 1
            return True
        else:
            self.overlay_label.text = ""
            self.trigger_flash_and_capture()
            return False

    def trigger_flash_and_capture(self):
        self.flash_color.a = 1
        frame = self.picam2.capture_array()
        img = Image.fromarray(frame)
        b, g, r, a = img.split()
        self.raw_photos.append(Image.merge("RGB", (r, g, b)))
        Clock.schedule_once(self.reset_flash, 0.125)

    def reset_flash(self, dt):
        self.flash_color.a = 0
        self.photo_count += 1
        Clock.schedule_once(lambda dt: self.run_sequence(), 0.5)

    def show_loading(self):
        self.is_running = False
        self.overlay_label.font_name = self.ui_font
        self.overlay_label.font_size = '80sp'
        self.overlay_label.text = "GENERATING..."
        Clock.schedule_once(lambda dt: self.generate_collage("fuji"), 0.5)

    def generate_collage(self, filter_type):
        strip_w, strip_h = 600, 1800
        photo_h = 450
        strip = Image.new('RGB', (strip_w, strip_h), (255, 255, 255))
        for i, img in enumerate(self.raw_photos):
            processed = self.apply_filter(img, filter_type)
            processed = ImageOps.fit(processed, (strip_w, photo_h), Image.Resampling.LANCZOS)
            strip.paste(processed, (0, i * photo_h))
        self.current_strip = strip
        strip.save("temp_preview.jpg")
        self.img_widget.source = "temp_preview.jpg"
        self.img_widget.reload()
        self.img_widget.pos_hint = {'center_x': 0.4, 'center_y': 0.5}
        self.controls.opacity = 1
        self.overlay_label.text = ""

    def save_to_gallery(self, *args):
        canvas = Image.new('RGB', (1200, 1800), (255, 255, 255))
        canvas.paste(self.current_strip, (0, 0))
        canvas.paste(self.current_strip, (600, 0))
        filename = f"booth_{int(time.time())}.jpg"
        canvas.save(os.path.join(self.save_path, filename), quality=95)
        if self.picam2: self.picam2.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def safe_exit(self):
        self.is_running = False
        try:
            if self.picam2:
                self.picam2.stop()
                self.picam2.close()
        except: pass
        os._exit(0)

if __name__ == "__main__":
    PhotoBoothApp().run()