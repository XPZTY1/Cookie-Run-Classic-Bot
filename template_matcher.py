import os

import cv2

from config import TEMPLATE_DIR, MATCH_THRESHOLD

# ---------------------------------------------------------------------------
# ฟังก์ชันหา template
# ---------------------------------------------------------------------------


def find_template(screen, template_name, threshold=MATCH_THRESHOLD):
    """
    หาตำแหน่ง template บนหน้าจอ
    คืนค่า (x, y, w, h) ของกึ่งกลางจุดที่เจอ หรือ None ถ้าไม่เจอ
    """
    template_path = os.path.join(TEMPLATE_DIR, template_name)
    if not os.path.exists(template_path):
        return None

    template = cv2.imread(template_path)
    if template is None:
        return None

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        h, w = template.shape[:2]
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2
        return (center_x, center_y, w, h)

    return None
