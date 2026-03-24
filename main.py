import time
import os
import sys
import threading
import subprocess
import numpy as np
from PIL import Image, ImageOps, ImageEnhance

# 1. Kivy System Configuration
from kivy.config import Config
Config.set('graphics', 'width', '1024')
Config.set('graphics', 'height', '600')
Config.set('graphics', 'fullscreen', 'auto')
Config.set('graphics', 'show_cursor', '1') 

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image as KivyImage
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.graphics import Color, Rectangle, Ellipse
from kivy.core.window import Window

from picamera2 import Picamera2

class PhotoBoothApp(App):
    def build(self):
        Window.clearcolor = (0, 0, 0, 1) # Sets the global background to Black
        Window.bind(on_keyboard=self.on_keyboard)

        self.asset_path = os.path.join(os.path.dirname(__file__), "assets")
        self.save_path = os.path.join(os.path.dirname(__file__), "gallery")
        if not os.path.exists(self.save_path): os.makedirs(self.save_path)

        # --- CAMERA HARDWARE ---
        self.picam2 = None
        try:
            self.picam2 = Picamera2()
            self.picam2.configure(self.picam2.create_preview_configuration(
                main={"format": "XRGB8888", "size": (1024, 600)}
            ))
            self.picam2.start()
        except Exception as e:
            print(f"Hardware Error: {e}"); self.safe_exit()

        self.root = FloatLayout()
        
        # 1. Background Manager
        self.bg_manager = KivyImage(source=os.path.join(self.asset_path, 'welcome.png'), 
                                    allow_stretch=True, keep_ratio=False)
        self.root.add_widget(self.bg_manager)

        # 2. Camera Preview / Photo Strip
        # fit_mode="contain" with black background creates the black borders you want
        self.img_widget = KivyImage(fit_mode="contain", size_hint=(1, 1), 
                                    pos_hint={'center_x': 0.5, 'center_y': 0.5},
                                    opacity=0) 
        self.root.add_widget(self.img_widget)

        # 3. Filter Sidebar
        self.filter_layer = FloatLayout(size_hint=(1, 1), opacity=0, disabled=True)
        self.setup_circular_filters()
        self.root.add_widget(self.filter_layer)

        # 4. Status Label (Top Right for "Applying")
        self.status_label = Label(text="", font_size='30sp', color=(1,1,1,1),
                                 size_hint=(None, None), size=(200, 50),
                                 pos_hint={'right': 0.98, 'top': 0.98})
        self.root.add_widget(self.status_label)

        # 5. Countdown Label (Center)
        self.overlay_label = Label(text="", font_size='250sp', color=(1,1,1,1))
        self.root.add_widget(self.overlay_label)

        # 6. Welcome Button Layer (Small button, centered-bottom)
        self.welcome_layer = FloatLayout(size_hint=(1, 1))
        self.btn_start = Button(size_hint=(0.2, 0.15), 
                                pos_hint={'center_x': 0.5, 'center_y': 0.35},
                                background_normal='', background_color=(1, 1, 0, 0.5))
        self.btn_start.bind(on_press=self.start_session)
        self.welcome_layer.add_widget(self.btn_start)
        self.root.add_widget(self.welcome_layer)

        # 7. Flash
        with self.root.canvas.after:
            self.flash_color = Color(1, 1, 1, 0)
            self.flash_rect = Rectangle(size=Window.size, pos=(0,0))

        self.is_running = False
        self.photo_count = 0
        self.raw_photos = []
        
        Clock.schedule_interval(self.update_loop, 1.0 / 30.0)
        return self.root

    def setup_circular_filters(self):
        configs = [
            ('fuji', {'center_x': 0.88, 'center_y': 0.75}),
            ('bw', {'center_x': 0.88, 'center_y': 0.55}),
            ('sepia', {'center_x': 0.88, 'center_y': 0.35})
        ]
        self.filter_btns = []
        for mode, pos in configs:
            btn = Button(size_hint=(None, None), size=(110, 110), pos_hint=pos,
                         background_normal='', background_color=(0,0,0,0))
            with btn.canvas.before:
                Color(1, 1, 0, 0.5)
                btn.shape = Ellipse(size=btn.size, pos=btn.pos)
            btn.bind(pos=self._update_shape, size=self._update_shape)
            btn.bind(on_press=lambda x, m=mode: self.launch_filter_thread(m))
            self.filter_layer.add_widget(btn)
            self.filter_btns.append(btn)

        # Print Button
        self.btn_print = Button(size_hint=(0.2, 0.15), pos_hint={'center_x': 0.88, 'center_y': 0.12},
                                background_normal='', background_color=(1, 1, 0, 0.5))
        self.btn_print.bind(on_press=self.initiate_print_flow)
        self.filter_layer.add_widget(self.btn_print)
        self.filter_btns.append(self.btn_print)

    def _update_shape(self, inst, val):
        inst.shape.pos, inst.shape.size = inst.pos, inst.size

    def start_session(self, instance):
        # Remove the welcome layer so it doesn't block the filter screen later
        if self.welcome_layer in self.root.children:
            self.root.remove_widget(self.welcome_layer)
        
        self.bg_manager.source = "" # Black Background
        self.img_widget.opacity = 1
        self.is_running = True
        self.photo_count = 0
        self.raw_photos = []
        self.run_sequence()

    def run_sequence(self):
        if self.photo_count < 4:
            self.overlay_label.text = "POSE!"
            Clock.schedule_once(self.start_countdown, 1.5)
        else:
            self.show_loading()

    def start_countdown(self, dt):
        self.count = 3
        self.overlay_label.text = str(self.count)
        Clock.schedule_interval(self.tick, 1.0)

    def tick(self, dt):
        self.count -= 1
        if self.count > 0:
            self.overlay_label.text = str(self.count); return True
        else:
            self.overlay_label.text = ""; self.capture_photo(); return False

    def capture_photo(self):
        self.flash_color.a = 1
        frame = self.picam2.capture_array()
        img = Image.fromarray(frame); b, g, r, a = img.split()
        self.raw_photos.append(Image.merge("RGB", (r, g, b)))
        Clock.schedule_once(lambda dt: setattr(self.flash_color, 'a', 0), 0.1)
        self.photo_count += 1
        self.run_sequence()

    def show_loading(self):
        self.is_running = False
        self.status_label.text = "Applying Fuji..."
        threading.Thread(target=self.process_background, args=("fuji",)).start()

    def launch_filter_thread(self, mode):
        for b in self.filter_btns: b.disabled = True
        self.status_label.text = f"Applying {mode}..."
        threading.Thread(target=self.process_background, args=(mode,)).start()

    def process_background(self, mode):
        strip_w, strip_h, photo_h = 600, 1800, 450
        strip = Image.new('RGB', (strip_w, strip_h), (255, 255, 255))
        for i, img in enumerate(self.raw_photos):
            work = img.copy()
            if mode == "bw": work = ImageOps.grayscale(work).convert("RGB")
            elif mode == "sepia":
                sepia = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
                work = Image.fromarray(np.clip(np.array(work).dot(sepia.T), 0, 255).astype(np.uint8))
            res = ImageOps.fit(work, (strip_w, photo_h), Image.Resampling.LANCZOS)
            strip.paste(res, (0, i * photo_h))
        self.current_strip = strip
        strip.save("temp_preview.jpg")
        Clock.schedule_once(self.display_filter_results, 0)

    def display_filter_results(self, dt):
        self.bg_manager.source = os.path.join(self.asset_path, 'filter.png')
        self.img_widget.source = "temp_preview.jpg"; self.img_widget.reload()
        self.status_label.text = ""
        self.filter_layer.opacity, self.filter_layer.disabled = 1, False
        for b in self.filter_btns: b.disabled = False

    def initiate_print_flow(self, instance):
        self.bg_manager.source = os.path.join(self.asset_path, 'thankyou.png')
        self.filter_layer.opacity, self.filter_layer.disabled, self.img_widget.opacity = 0, True, 0
        
        # Test: Save image only
        canvas = Image.new('RGB', (1200, 1800), (255, 255, 255))
        canvas.paste(self.current_strip, (0, 0)); canvas.paste(self.current_strip, (600, 0))
        canvas.save(os.path.join(self.save_path, f"print_{int(time.time())}.jpg"))
        
        Clock.schedule_once(self.reset_to_start, 30.0)

    def reset_to_start(self, dt):
        if self.welcome_layer not in self.root.children:
            self.root.add_widget(self.welcome_layer)
        self.bg_manager.source = os.path.join(self.asset_path, 'welcome.png')
        self.img_widget.source, self.img_widget.opacity, self.is_running = "", 0, False

    def update_loop(self, dt):
        if self.is_running and self.picam2:
            frame = self.picam2.capture_array()
            texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='rgba')
            texture.blit_buffer(frame.tobytes(), colorfmt='bgra', bufferfmt='ubyte')
            texture.flip_vertical(); self.img_widget.texture = texture

    def on_keyboard(self, w, k, s, c, m):
        if k == 27: self.safe_exit(); return True
    def safe_exit(self):
        if self.picam2: self.picam2.stop(); self.picam2.close()
        os._exit(0)

if __name__ == "__main__":
    PhotoBoothApp().run()