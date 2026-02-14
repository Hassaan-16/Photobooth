import time
import os
import sys
import subprocess
import tkinter as tk
from PIL import Image, ImageTk, ImageOps
from picamera2 import Picamera2

class PhotoBooth:
    def __init__(self, window):
        self.window = window
        self.window.title("Smooth Pi Photobooth")
        self.window.attributes('-fullscreen', True)
        self.window.configure(bg="black")
        
        self.window.bind('<Escape>', lambda e: self.safe_exit())
        
        self.save_path = "./gallery"
        if not os.path.exists(self.save_path): os.makedirs(self.save_path)

        # 1. Initialize Picamera2
        try:
            self.picam2 = Picamera2()
            # Requesting BGR here often fixes the color swap on Pi displays
            self.picam2.configure(self.picam2.create_preview_configuration(main={"format": "XRGB8888", "size": (800, 600)}))
            self.picam2.start()
        except Exception as e:
            print(f"Hardware Error: {e}"); self.safe_exit()

        # UI
        self.label = tk.Label(window, bg="black")
        self.label.pack(fill="both", expand=True)

        self.overlay_label = tk.Label(window, text="", font=("Arial", 80, "bold"), fg="yellow", bg="black")
        
        self.btn_start = tk.Button(window, text="START", command=self.start_countdown, 
                                   font=("Arial", 30), bg="#2ecc71", fg="white")
        self.btn_start.pack(side="bottom", fill="x")

        self.is_running = True
        self.photo_count = 0
        self.photos = []
        
        self.update_loop()

    def update_loop(self):
        if self.is_running:
            frame = self.picam2.capture_array()
            # FIX COLOR SWAP: Convert BGR to RGB
            img = Image.fromarray(frame)
            b, g, r, a = img.split() # XRGB8888 gives 4 channels
            img = Image.merge("RGB", (r, g, b)) 
            
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            imgtk = ImageTk.PhotoImage(image=img)
            self.label.imgtk = imgtk
            self.label.configure(image=imgtk)
            
        self.window.after(10, self.update_loop)

    def start_countdown(self):
        self.btn_start.pack_forget()
        self.photos = []
        self.photo_count = 0
        self.next_photo_sequence()

    def next_photo_sequence(self):
        if self.photo_count < 4:
            self.countdown(5)
        else:
            self.generate_collage()

    def countdown(self, seconds):
        if seconds > 0:
            self.overlay_label.config(text=str(seconds))
            self.overlay_label.place(relx=0.5, rely=0.5, anchor="center")
            self.window.after(1000, lambda: self.countdown(seconds - 1))
        else:
            self.overlay_label.place_forget()
            self.take_photo()

    def take_photo(self):
        # Flash and Capture
        frame = self.picam2.capture_array()
        img = Image.fromarray(frame)
        b, g, r, a = img.split()
        rgb_img = Image.merge("RGB", (r, g, b))
        
        # Apply Retro Gold Filter
        self.photos.append(self.apply_retro_filter(rgb_img))
        
        self.photo_count += 1
        # Brief pause to show the user they took a photo, then next one
        self.window.after(500, self.next_photo_sequence)

    def apply_retro_filter(self, img):
        r, g, b = img.split()
        r = r.point(lambda i: i * 1.25) # Extra Warmth
        b = b.point(lambda i: i * 0.6)  # Deep Gold
        return Image.merge("RGB", (r, g, b))

    def generate_collage(self):
        w, h = self.photos[0].size
        collage = Image.new('RGB', (w, h * 4))
        for i, img in enumerate(self.photos):
            collage.paste(img, (0, i * h))
        
        path = f"gallery/collage_{int(time.time())}.jpg"
        collage.save(path)
        
        # Show result
        preview = collage.copy()
        preview.thumbnail((300, 700))
        imgtk = ImageTk.PhotoImage(image=preview)
        self.label.configure(image=imgtk)
        self.label.image = imgtk
        
        tk.Button(self.window, text="PRINT & RESTART", command=self.safe_restart, font=("Arial", 20)).pack(side="bottom")

    def safe_restart(self):
        self.picam2.stop()
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