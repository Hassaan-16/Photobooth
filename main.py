import time
import os
import sys
import numpy as np
import tkinter as tk
import subprocess  # Required for printing
from PIL import Image, ImageTk, ImageOps, ImageEnhance
from picamera2 import Picamera2

class PhotoBooth:

    def __init__(self, window):
        self.window = window
        self.window.title("Fuji Pi Booth")
        
        # Performance Settings
        self.is_fullscreen = False 
        if self.is_fullscreen:
            self.window.attributes('-fullscreen', True)
        else:
            self.window.geometry("1024x768")
        
        self.window.configure(bg="black")
        self.window.bind('<Escape>', lambda e: self.safe_exit())
        
        self.save_path = "./gallery"
        if not os.path.exists(self.save_path): 
            os.makedirs(self.save_path)

        try:
            self.picam2 = Picamera2()
            self.picam2.configure(self.picam2.create_preview_configuration(
                main={"format": "XRGB8888", "size": (800, 600)}
            ))
            self.picam2.start()
        except Exception as e:
            print(f"Hardware Error: {e}"); self.safe_exit()

        # --- UI ELEMENTS ---
        self.preview_label = tk.Label(window, bg="black")
        self.preview_label.pack(fill="both", expand=True)

        self.overlay_label = tk.Label(window, text="", font=("Arial", 100, "bold"), fg="white", bg="black")
        self.flash_frame = tk.Frame(window, bg="white")

        self.welcome_label = tk.Label(window, text="Welcome to the xyz Photobooth\nPress start to create a memory", 
                                      font=("Arial", 24, "italic"), fg="white", bg="black", justify="center")
        self.welcome_label.place(relx=0.5, rely=0.25, anchor="center")

        self.btn_start = tk.Button(window, text="START", command=self.start_countdown, 
                                   font=("Arial", 30, "bold"), bg="#218112", fg="white", padx=50)
        self.btn_start.place(relx=0.5, rely=0.5, anchor="center")

        self.controls = tk.Frame(window, bg="black")

        self.is_running = True
        self.photo_count = 0
        self.raw_photos = [] 
        self.current_strip = None # Holds a single 2x6 strip
        
        self.update_loop()

    def update_loop(self):
        if self.is_running:
            frame = self.picam2.capture_array()
            img = Image.fromarray(frame)
            b, g, r, a = img.split()
            img = Image.merge("RGB", (r, g, b)).transpose(Image.FLIP_LEFT_RIGHT)
            imgtk = ImageTk.PhotoImage(image=img)
            self.preview_label.imgtk = imgtk
            self.preview_label.configure(image=imgtk)
        self.window.after(10, self.update_loop)

    # --- FILTER LOGIC ---
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
            sepia_arr = arr.dot(sepia_matrix.T)
            sepia_arr = np.clip(sepia_arr, 0, 255).astype(np.uint8)
            work_img = Image.fromarray(sepia_arr)
            enhancer = ImageEnhance.Contrast(work_img)
            work_img = enhancer.enhance(1.0)
            return self.add_grain(work_img, intensity=8)
        
        return work_img

    # --- PRINTING & COLLAGE LOGIC ---
    def generate_collage(self, filter_type):
        # 4x6 at 300 DPI = 1200w x 1800h
        # 2x6 strip = 600w x 1800h
        strip_w, strip_h = 600, 1800
        photo_h = 450 # 1.5 inches each
        
        # Create one 2x6 strip
        strip = Image.new('RGB', (strip_w, strip_h), (255, 255, 255))
        for i, img in enumerate(self.raw_photos):
            processed = self.apply_filter(img, filter_type)
            # Crop/Fit to exactly 2x1.5 inches
            processed = ImageOps.fit(processed, (strip_w, photo_h), Image.Resampling.LANCZOS)
            strip.paste(processed, (0, i * photo_h))
        
        self.current_strip = strip
        self.overlay_label.place_forget()
        
        # UI Preview
        display_img = strip.copy()
        display_img.thumbnail((300, 600))
        imgtk = ImageTk.PhotoImage(image=display_img)
        self.preview_label.imgtk = imgtk
        self.preview_label.configure(image=imgtk)
        self.preview_label.pack_configure(padx=(0, 200))
        self.display_end_buttons()

    def save_and_restart(self):
        # 1. Create 4x6 Master Canvas (1200x1800 at 300DPI)
        # We create it slightly larger (1260x1890) to create a 'Bleed' area
        bleed_w, bleed_h = 1260, 1890
        canvas = Image.new('RGB', (bleed_w, bleed_h), (255, 255, 255))
        
        # Paste the strips with a slight overlap to cover edges
        # Each strip is 600px wide, so we center them on the 1260px canvas
        canvas.paste(self.current_strip, (30, 45)) 
        canvas.paste(self.current_strip, (630, 45))
        
        # 2. Save the final print file
        # file_path = os.path.join(self.save_path, f"print_{int(time.time())}.jpg")
        # canvas.save(file_path, quality=95)
        
        temp_path = "/tmp/booth_print.jpg"
        canvas.save(temp_path, quality=100)

        # 3. Enhanced CUPS Command with Expansion
        try:
            print_cmd = [
                "lp", 
                "-d", "L3250-Series", 
                "-o", "PageSize=4X6FULL",
                "-o", "MediaType=PMPHOTO_NORMAL", # PHOTO mode is required for borderless
                "-o", "fit-to-page",
                "-o", "image-position=center",
                temp_path
            ]
            subprocess.run(print_cmd, check=True)
        except Exception as e:
            print(f"Print error: {e}")

        self.safe_restart()

    # --- CORE FLOW ---
    def start_countdown(self):
        self.btn_start.place_forget()
        self.welcome_label.place_forget()
        self.raw_photos = []
        self.photo_count = 0
        self.next_photo_sequence()

    def next_photo_sequence(self):
        if self.photo_count < 4:
            self.countdown(5)
        else:
            self.show_loading()

    def countdown(self, seconds):
        if seconds > 0:
            self.overlay_label.config(text=str(seconds), fg="white")
            self.overlay_label.place(relx=0.5, rely=0.5, anchor="center")
            self.window.after(1000, lambda: self.countdown(seconds - 1))
        else:
            self.overlay_label.place_forget()
            self.trigger_flash()

    def trigger_flash(self):
        self.flash_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.window.update()
        frame = self.picam2.capture_array()
        img = Image.fromarray(frame)
        b, g, r, a = img.split()
        self.raw_photos.append(Image.merge("RGB", (r, g, b)))
        self.window.after(125, lambda: self.flash_frame.place_forget())
        self.window.after(500, self.finish_capture_step)

    def finish_capture_step(self):
        self.photo_count += 1
        self.next_photo_sequence()

    def show_loading(self):
        self.is_running = False
        self.overlay_label.config(text="GENERATING...", font=("Arial", 40, "bold"), fg="#f1c40f")
        self.overlay_label.place(relx=0.5, rely=0.5, anchor="center")
        self.window.update()
        self.window.after(1000, lambda: self.generate_collage("fuji"))

    def display_end_buttons(self):
        for widget in self.controls.winfo_children():
            widget.destroy()
        self.controls.place(relx=0.85, rely=0.5, anchor="center")
        tk.Label(self.controls, text="Choose Filter", font=("Arial", 16, "bold"), fg="white", bg="black").pack(pady=10)
        tk.Button(self.controls, text="Retro Fuji Film", command=lambda: self.generate_collage("fuji"), bg="#f39c12", fg="white", font=("Arial", 12, "bold"), width=15).pack(pady=5)
        tk.Button(self.controls, text="Black n white", command=lambda: self.generate_collage("bw"), bg="#34495e", fg="white", font=("Arial", 12, "bold"), width=15).pack(pady=5)
        tk.Button(self.controls, text="Sepia", command=lambda: self.generate_collage("sepia"), bg="#8B4513", fg="white", font=("Arial", 12, "bold"), width=15).pack(pady=5)
        tk.Button(self.controls, text="PRINT", command=self.save_and_restart, bg="#2980b9", fg="white", font=("Arial", 15, "bold"), width=15).pack(pady=20)

    def safe_restart(self):
        if hasattr(self, 'picam2'): self.picam2.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def safe_exit(self):
        self.is_running = False
        if hasattr(self, 'picam2'): self.picam2.stop()
        self.window.destroy()
        sys.exit()

if __name__ == "__main__":
    root = tk.Tk()
    app = PhotoBooth(root)
    root.mainloop()