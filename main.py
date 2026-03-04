import time
import os
import sys
import numpy as np  # Required for grain and sepia matrix
import tkinter as tk
from PIL import Image, ImageTk, ImageOps, ImageEnhance # Added ImageEnhance
from picamera2 import Picamera2

#Standard Photobooth (not camera modded)

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
                                      font=("Arial", 24, "bold"), fg="white", bg="black", justify="center")
        self.welcome_label.place(relx=0.5, rely=0.4, anchor="center")

        self.btn_start = tk.Button(window, text="START", command=self.start_countdown, 
                                   font=("Arial", 30, "bold"), bg="#2ecc71", fg="white", padx=50)
        self.btn_start.place(relx=0.5, rely=0.5, anchor="center")

        self.controls = tk.Frame(window, bg="black")

        self.is_running = True
        self.photo_count = 0
        self.raw_photos = [] 
        self.current_collage = None
        
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
    def add_grain(self, img, intensity=15):
        """Standard grain function with adjustable intensity"""
        np_img = np.array(img).astype(np.float32)
        noise = np.random.normal(0, intensity, np_img.shape)
        np_img = np.clip(np_img + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(np_img)

    def apply_filter(self, img, mode):
        """Advanced filter logic with grain and enhancements"""
        work_img = img.copy()

        if mode == "fuji":
            r, g, b = work_img.split()
            work_img = Image.merge("RGB", (r.point(lambda i: i * 1.1), g.point(lambda i: i * 1.05), b.point(lambda i: i * 0.9)))
            return self.add_grain(work_img, intensity=5)

        elif mode == "bw":
            work_img = ImageOps.grayscale(work_img).convert("RGB")
            enhancer = ImageEnhance.Contrast(work_img)
            work_img = enhancer.enhance(1.0) 
            r, g, b = work_img.split()
            work_img = Image.merge("RGB", (r.point(lambda i: i * 1.05), g, b))
            return self.add_grain(work_img, intensity=10)

        elif mode == "sepia":
            sepia_matrix = np.array([[0.393, 0.769, 0.189], 
                                     [0.349, 0.686, 0.168], 
                                     [0.272, 0.534, 0.131]])
            arr = np.array(work_img)
            sepia_arr = arr.dot(sepia_matrix.T)
            sepia_arr = np.clip(sepia_arr, 0, 255).astype(np.uint8)
            work_img = Image.fromarray(sepia_arr)
            enhancer = ImageEnhance.Contrast(work_img)
            work_img = enhancer.enhance(1.0)
            return self.add_grain(work_img, intensity=5)

        return work_img

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
        # Defaulting to fuji for initial generation
        self.window.after(1000, lambda: self.generate_collage("fuji"))

    def generate_collage(self, filter_type):
        w, h = self.raw_photos[0].size
        collage = Image.new('RGB', (w, h * 4))
        for i, img in enumerate(self.raw_photos):
            processed = self.apply_filter(img, filter_type)
            collage.paste(processed, (0, i * h))
        
        self.current_collage = collage
        self.overlay_label.place_forget()
        
        display_img = collage.copy()
        display_img.thumbnail((350, 700))
        imgtk = ImageTk.PhotoImage(image=display_img)
        self.preview_label.imgtk = imgtk
        self.preview_label.configure(image=imgtk)
        self.preview_label.pack_configure(padx=(0, 200))

        self.display_end_buttons()

    def display_end_buttons(self):
        for widget in self.controls.winfo_children():
            widget.destroy()

        self.controls.place(relx=0.85, rely=0.5, anchor="center")

        tk.Label(self.controls, text="Choose Filter", font=("Arial", 16, "bold"), 
                 fg="white", bg="black").pack(pady=10)

        tk.Button(self.controls, text="Retro Fuji Film", command=lambda: self.generate_collage("fuji"),
                  bg="#f39c12", fg="white", font=("Arial", 12, "bold"), width=15).pack(pady=5)

        tk.Button(self.controls, text="Black n white", command=lambda: self.generate_collage("bw"),
                  bg="#34495e", fg="white", font=("Arial", 12, "bold"), width=15).pack(pady=5)
        
        # New Sepia Button
        tk.Button(self.controls, text="Sepia", command=lambda: self.generate_collage("sepia"),
                  bg="#8B4513", fg="white", font=("Arial", 12, "bold"), width=15).pack(pady=5)

        tk.Button(self.controls, text="PRINT", command=self.save_and_restart,
                  bg="#2980b9", fg="white", font=("Arial", 15, "bold"), width=15).pack(pady=20)

    def save_and_restart(self):
        filename = f"collage_{int(time.time())}.jpg"
        self.current_collage.save(os.path.join(self.save_path, filename))
        self.safe_restart()

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