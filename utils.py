import cv2
import numpy as np
import face_recognition
import base64
import re

def decode_image_bytes(image_data):
    try:
        nparr = np.frombuffer(image_data, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except:
        return None

def decode_base64(base64_string: str):
    if "," in base64_string:
        base64_string = base64_string.split(",")[1]
    return base64.b64decode(base64_string)

def get_encoding_from_image(img):
    height, width = img.shape[:2]
    max_width = 600
    if width > max_width:
        scaling_factor = max_width / float(width)
        new_height = int(height * scaling_factor)
        img = cv2.resize(img, (max_width, new_height))

    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    encodings = face_recognition.face_encodings(rgb_img)
    if len(encodings) > 0:
        return encodings[0].tolist()
    return None

def crop_face(img):
    height, width = img.shape[:2]
    max_width = 800
    if width > max_width:
        scaling_factor = max_width / float(width)
        new_height = int(height * scaling_factor)
        img = cv2.resize(img, (max_width, new_height))

    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_img)
    
    if len(face_locations) == 0:
        return None, "No face detected"
    
    face_loc = max(face_locations, key=lambda f: (f[2] - f[0]) * (f[1] - f[3]))
    top, right, bottom, left = face_loc
    
    height, width, _ = img.shape
    
    pad_h = int((bottom - top) * 0.2)
    pad_w = int((right - left) * 0.2)
    
    new_top = max(0, top - pad_h)
    new_bottom = min(height, bottom + pad_h)
    new_left = max(0, left - pad_w)
    new_right = min(width, right + pad_w)
    
    cropped_face = img[new_top:new_bottom, new_left:new_right]
    cropped_face = cv2.resize(cropped_face, (400, 400))
    
    return cropped_face, "Success"

def validate_liveness(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    spoof_score = 0
    reasons = []

    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    if blur_score < 40: 
        spoof_score += 1
        reasons.append("Too Blurry")
    
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    bright_pixels = sum(hist[245:]) 
    bright_ratio = bright_pixels / (gray.shape[0] * gray.shape[1])
    if bright_ratio > 0.15: 
        spoof_score += 1
        reasons.append("High Glare")

    dark_pixels = sum(hist[:10])
    dark_ratio = dark_pixels / (gray.shape[0] * gray.shape[1])
    if dark_ratio > 0.85: 
        spoof_score += 1
        reasons.append("Too Dark")

    if spoof_score >= 3:
        return False, f"Verification Failed: {reasons[0]}"
    return True, "Live"

def process_image_link(url):
    url = url.strip()
    if "drive.google.com" in url and "/d/" in url:
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return f'https://drive.google.com/uc?export=download&id={match.group(1)}'
    if "dropbox.com" in url and "dl=0" in url:
        return url.replace("dl=0", "dl=1")
    return url
