import time
import datetime
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
from kivy.graphics import Color, Rectangle, Ellipse, PushMatrix, PopMatrix, Rotate
from kivy.core.window import Window

from picamera2 import Picamera2

class PhotoBoothApp(App):
    def build(self):
        Window.clearcolor = (0, 0, 0, 1) 
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

        # 2a. Live Camera Preview (Centered)
        self.img_widget = KivyImage(fit_mode="contain", size_hint=(1, 1), 
                                    pos_hint={'center_x': 0.5, 'center_y': 0.5},
                                    opacity=0) 
        self.root.add_widget(self.img_widget)

        # 2b. LEFT STRIP (Independent)
        self.collage_left = KivyImage(fit_mode="contain", size_hint=(0.45, 0.86), 
                                      pos_hint={'center_x': 0.20, 'center_y': 0.53},
                                      opacity=0)
        with self.collage_left.canvas.before:
            PushMatrix()
            self.rot_left = Rotate(angle=3.5, origin=self.collage_left.center)
        with self.collage_left.canvas.after:
            PopMatrix()
            
        # 2c. RIGHT STRIP (Independent)
        self.collage_right = KivyImage(fit_mode="contain", size_hint=(0.63, 0.95), 
                                       pos_hint={'center_x': 0.40, 'center_y': 0.5},
                                       opacity=0)
        with self.collage_right.canvas.before:
            PushMatrix()
            self.rot_right = Rotate(angle=-4.5, origin=self.collage_right.center)
        with self.collage_right.canvas.after:
            PopMatrix()

        # Update rotation origins for both
        self.collage_left.bind(pos=self._update_rot_left, size=self._update_rot_left)
        self.collage_right.bind(pos=self._update_rot_right, size=self._update_rot_right)
        
        self.root.add_widget(self.collage_left)
        self.root.add_widget(self.collage_right)

        # 3. Filter Sidebar
        self.filter_layer = FloatLayout(size_hint=(1, 1), opacity=0, disabled=True)
        self.setup_circular_filters()
        self.root.add_widget(self.filter_layer)

        # 4. Status Label
        self.status_label = Label(text="", font_size='30sp', color=(1,1,1,1),
                                 size_hint=(None, None), size=(200, 50),
                                 pos_hint={'right': 0.98, 'top': 0.98})
        self.root.add_widget(self.status_label)

        # 5. Countdown Label
        self.overlay_label = Label(text="", font_size='250sp', color=(1,1,1,1))
        self.root.add_widget(self.overlay_label)

        # 6. Welcome Button Layer
        self.welcome_layer = FloatLayout(size_hint=(1, 1))
        self.btn_start = Button(size_hint=(0.40, 0.21), 
                                pos_hint={'center_x': 0.5, 'center_y': 0.26},
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
        
        self.active_filter = "fuji" # Fuji is the default starting filter

        Clock.schedule_interval(self.update_loop, 1.0 / 30.0)
        return self.root

    # Update Rotation Helpers
    def _update_rot_left(self, inst, val): self.rot_left.origin = inst.center
    def _update_rot_right(self, inst, val): self.rot_right.origin = inst.center

    def setup_circular_filters(self):
        configs = [
            ('fuji', {'center_x': 0.74, 'center_y': 0.80}),
            ('sepia', {'center_x': 0.74, 'center_y': 0.50})
        ]
        self.filter_btns = []
        for mode, pos in configs:
            btn = Button(size_hint=(None, None), size=(353, 300), pos_hint=pos,
                         background_normal='', background_color=(0,0,0,0))
            with btn.canvas.before:
                Color(1, 1, 0, 0.5)
                btn.shape = Ellipse(size=btn.size, pos=btn.pos)
            btn.bind(pos=self._update_shape, size=self._update_shape)
            btn.bind(on_press=lambda x, m=mode: self.launch_filter_thread(m))
            self.filter_layer.add_widget(btn)
            self.filter_btns.append(btn)

        self.btn_print = Button(size_hint=(0.31, 0.21), pos_hint={'center_x': 0.73, 'center_y': 0.19},
                                background_normal='', background_color=(1, 1, 0, 0.5))
        self.btn_print.bind(on_press=self.initiate_print_flow)
        self.filter_layer.add_widget(self.btn_print)
        self.filter_btns.append(self.btn_print)

    def _update_shape(self, inst, val):
        inst.shape.pos, inst.shape.size = inst.pos, inst.size

    def start_session(self, instance):
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
        img = Image.fromarray(frame)
        img = ImageOps.mirror(img) #flips horizontally
        b, g, r, a = img.split()
        self.raw_photos.append(Image.merge("RGB", (r, g, b)))
        Clock.schedule_once(lambda dt: setattr(self.flash_color, 'a', 0), 0.1)
        self.photo_count += 1
        self.run_sequence()

    def show_loading(self):
        self.is_running = False
        self.status_label.text = "Applying Fuji..."
        self.active_filter = "fuji" # Sync the state
        threading.Thread(target=self.process_background, args=("fuji",)).start()

    def launch_filter_thread(self, mode):
        # 1. Check if the filter is already the active one
        if mode == self.active_filter:
            self.status_label.text = "APPLIED!"
            # Just clear the message after 1 second, no processing needed
            Clock.schedule_once(self.clear_status_message, 1.0)
            return

        # 2. If it's a NEW filter, proceed with processing as usual
        for b in self.filter_btns: 
            b.disabled = True
            
        self.status_label.text = f"Applying {mode}..."
        # Update the state to the new filter
        self.active_filter = mode 
        threading.Thread(target=self.process_background, args=(mode,)).start()

    def clear_status_message(self, dt):
        self.status_label.text = ""

    def process_background(self, mode):
        strip_w, strip_h, photo_h = 564, 1800, 450 
        # 564 instead of 600 here 
        # accomodates the white strip in between
        
        # 1. Generate single strip
        single_strip = Image.new('RGB', (strip_w, strip_h), (255, 255, 255))
        for i, img in enumerate(self.raw_photos):
            work = img.copy()
            if mode == "bw": work = ImageOps.grayscale(work).convert("RGB")
            elif mode == "sepia":
                sepia_matrix = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
                work = Image.fromarray(np.clip(np.array(work).dot(sepia_matrix.T), 0, 255).astype(np.uint8))
            res = ImageOps.fit(work, (strip_w, photo_h), Image.Resampling.LANCZOS)
            single_strip.paste(res, (0, i * photo_h))
        
        self.current_strip = single_strip 
        single_strip.save("temp_preview.png")
        Clock.schedule_once(self.display_filter_results, 0)

    def display_filter_results(self, dt):
        self.bg_manager.source = os.path.join(self.asset_path, 'filter.png')
        self.img_widget.opacity = 0
        
        # Load the same file into both separate widgets
        self.collage_left.source = "temp_preview.png"
        self.collage_left.reload()
        self.collage_left.opacity = 1
        
        self.collage_right.source = "temp_preview.png"
        self.collage_right.reload()
        self.collage_right.opacity = 1
        
        self.status_label.text = ""
        self.filter_layer.opacity, self.filter_layer.disabled = 1, False
        for b in self.filter_btns: b.disabled = False

    def initiate_print_flow(self, instance):
        # 1. Create the unique filename first
        filename = f"print_{int(time.time())}.jpg"
        
        # 2. Update the report with this filename
        self.generate_report(filename)

        # 3. Update UI
        self.bg_manager.source = os.path.join(self.asset_path, 'thankyou.png')
        self.filter_layer.opacity, self.filter_layer.disabled = 0, True
        self.collage_left.opacity = 0
        self.collage_right.opacity = 0
        
        # --- FINAL PRINT LAYOUT SETTINGS ---
        strip_w = 564  
        gap_px = 71    
        
        # Create 4x6 canvas
        canvas = Image.new('RGB', (1200, 1800), (255, 255, 255))
        
        # Paste strips
        canvas.paste(self.current_strip, (0, 0))
        canvas.paste(self.current_strip, (strip_w + gap_px, 0))
        
        # 4. Save using the SAME filename variable from step 1
        save_file = os.path.join(self.save_path, filename)
        canvas.save(save_file, quality=95)
        
        # Optional: Printer command (uncomment if needed)
        # temp_print = "/tmp/to_printer.jpg"
        # canvas.save(temp_print)
        # subprocess.run(["lp", "-d", "EPSON_L3250_Series", "-o", "PageSize=4X6FULL", "-o", "StpBorderless=True", temp_print])

        Clock.schedule_once(self.reset_to_start, 30.0)

    def reset_to_start(self, dt):
        if self.welcome_layer not in self.root.children:
            self.root.add_widget(self.welcome_layer)
        self.bg_manager.source = os.path.join(self.asset_path, 'welcome.png')
        self.img_widget.source, self.img_widget.opacity, self.is_running = "", 0, False
        self.collage_left.opacity = 0
        self.collage_right.opacity = 0

    def update_loop(self, dt):
        if self.is_running and self.picam2:
            frame = self.picam2.capture_array()
            texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='rgba')
            texture.blit_buffer(frame.tobytes(), colorfmt='bgra', bufferfmt='ubyte')
            texture.flip_vertical()
            #texture.flip_horizontal()
            self.img_widget.texture = texture

    def generate_report(self, saved_filename):
        import datetime
        now = datetime.datetime.now()
        month_str = now.strftime("%b-%y").upper() # JAN-26
        day_str = now.strftime("%d-%m-%y")
        timestamp = now.strftime("%H:%M:%S")
        
        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        month_dir = os.path.join(reports_dir, month_str)
        if not os.path.exists(month_dir): os.makedirs(month_dir)
        
        file_path = os.path.join(month_dir, f"{day_str}.txt")
        
        current_count = 0
        existing_logs = []

        # Read current status
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                lines = f.readlines()
                if lines:
                    try:
                        # Extract number from "pictures taken: 10"
                        current_count = int(lines[0].split(":")[1].strip())
                        existing_logs = lines[1:] # Save the old list of filenames
                    except: pass

        # Write updated status
        with open(file_path, "w") as f:
            f.write(f"pictures taken: {current_count + 1}\n") # Increment by 1 session
            f.writelines(existing_logs) # Put back old list
            f.write(f"[{timestamp}] {saved_filename}\n") # Add new filename

    def on_keyboard(self, w, k, s, c, m):
        if k == 27: self.safe_exit(); return True
    def safe_exit(self):
        if self.picam2: self.picam2.stop(); self.picam2.close()
        os._exit(0)

if __name__ == "__main__":
    PhotoBoothApp().run()